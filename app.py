from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from groq import Groq
from pathlib import Path
from datetime import datetime
from functools import wraps
from threading import Thread
import random
import os
import logging
from logging.handlers import RotatingFileHandler

# ---------------- LOAD .env ----------------
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

print("FILE EXISTS:", env_path.exists())
print("GROQ KEY LOADED:", os.getenv("GROQ_API_KEY") is not None)

# ---------------- FLASK APP ----------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'reachup-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reachup.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ---------------- LOGGING SETUP ----------------
if not os.path.exists('logs'):
    os.mkdir('logs')

file_handler = RotatingFileHandler('logs/reachup.log', maxBytes=10240000, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('========== ReachUp AI Startup ==========')

# ---------------- MAIL SETUP ----------------
mail = Mail(app)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', True)
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@reachupal.com')

# ---------------- EXTENSIONS ----------------
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------------- GROQ CLIENT (LAZY INITIALIZATION) ----------------
MODEL = "llama-3.3-70b-versatile"

def get_groq_client():
    """Initialize Groq client lazily - only when needed"""
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


# ---------------- USER MODEL ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    business_type = db.Column(db.String(100), default="Photography")
    city = db.Column(db.String(100), default="Lahore")
    plan = db.Column(db.String(20), default="trial")
    trial_start = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    generations_used = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)
    brand_name = db.Column(db.String(100), default="")
    photography_style = db.Column(db.String(100), default="")
    client_type = db.Column(db.String(100), default="")
    instagram_tone = db.Column(db.String(100), default="")
    language_preference = db.Column(db.String(50), default="English only")
    sample_captions = db.Column(db.Text, default="")
    onboarding_done = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- HELPERS ----------------
def get_unique_seed():
    return f"{datetime.now().strftime('%H%M%S%f')}-{random.randint(1000, 9999)}"

def get_plan_limits(plan):
    limits = {
        "trial": 20,
        "starter": 200,
        "pro": 999999
    }
    return limits.get(plan, 0)

def check_user_access():
    if current_user.plan == "trial":
        days_used = (datetime.utcnow() - current_user.trial_start).days
        if days_used > 7:
            return False, "trial_expired"
    limit = get_plan_limits(current_user.plan)
    if current_user.generations_used >= limit:
        return False, "limit_reached"
    return True, "ok"

def increment_usage():
    current_user.generations_used += 1
    db.session.commit()

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def get_user_brand_profile():
    tone_instructions = {
        "Professional": "Use formal, polished language. No slang. Authoritative but warm.",
        "Friendly": "Use casual, conversational language. Feel like a friend talking.",
        "Emotional": "Use deeply emotional storytelling. Touch the heart. Make people feel.",
        "Poetic": "Use metaphors, poetic language, lyrical flow. Beautiful and artistic."
    }

    client_instructions = {
        "Middle Class": "Focus on value, affordability, memories. Relatable and warm.",
        "Upper Middle": "Focus on quality, professionalism, beautiful results. Aspirational.",
        "Elite": "Focus on exclusivity, luxury, perfection. Premium and sophisticated.",
        "All Types": "Balance between warmth and professionalism."
    }

    language_instructions = {
        "English Only": "Write ONLY in English. No Urdu words at all.",
        "Urdu Only": "Write ONLY in Urdu (Roman Urdu is fine). No English except brand names.",
        "Mix of Both": "Mix English and Urdu naturally. Roman Urdu mixed with English works great."
    }

    tone_guide = tone_instructions.get(
        current_user.instagram_tone, "Professional and warm"
    )
    client_guide = client_instructions.get(
        current_user.client_type, "Warm and relatable"
    )
    language_guide = language_instructions.get(
        current_user.language_preference, "Write in English"
    )

    profile = f"""
========== USER BRAND PROFILE ==========
Brand Name: {current_user.brand_name or current_user.name}
Photography Style: {current_user.photography_style or 'General'}
Typical Clients: {current_user.client_type or 'General'}
Instagram Tone: {current_user.instagram_tone or 'Professional'}
Language: {current_user.language_preference or 'English Only'}
City: {current_user.city}
Business Type: {current_user.business_type}

========== HOW TO WRITE FOR THIS USER ==========
TONE GUIDE: {tone_guide}
CLIENT GUIDE: {client_guide}
LANGUAGE GUIDE: {language_guide}
"""

    if current_user.sample_captions:
        profile += f"""
========== THEIR WRITING STYLE ==========
Learn from these captions they loved before.
Replicate their exact vocabulary, sentence length, and emotional depth:

{current_user.sample_captions}

IMPORTANT: Your output must feel like THIS person wrote it.
Not like a generic AI caption.
=========================================
"""
    else:
        profile += """
=========================================
"""
    return profile


# ---------------- EMAIL HELPERS ----------------
def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
            app.logger.info(f"[EMAIL] OK Sent to: {msg.recipients}")
        except Exception as e:
            app.logger.error(f"[EMAIL] X Failed: {str(e)}")

def send_email(subject, recipients, text_body, html_body):
    msg = Message(subject, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    Thread(target=send_async_email, args=(app, msg)).start()

def send_welcome_email(user):
    subject = "Welcome to ReachUp AI!"
    html_body = f'''<html><body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #6C63FF;">Welcome to ReachUp AI, {user.name}!</h2>
    <p>You are now part of a community of wedding photographers using AI to get more bookings.</p>
    <h3>Your 7-Day Free Trial Includes:</h3>
    <ul>
    <li>AI Caption Generator</li>
    <li>Smart Hashtag Engine</li>
    <li>Monthly Content Calendar</li>
    <li>Ad Copy Generator</li>
    <li>DM Response Generator</li>
    <li>Posting Time Optimizer</li>
    <li>Competitor Analysis</li>
    </ul>
    <p><strong>You have 20 AI generations to use.</strong></p>
    <h3>Quick Start:</h3>
    <ol>
    <li>Login to your account</li>
    <li>Complete your profile (5 minutes)</li>
    <li>Generate your first caption</li>
    </ol>
    <p><a href="http://localhost:5000/login" style="background-color: #6C63FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Login Now</a></p>
    <p>Have questions? Reply to this email. We are here to help!</p>
    <p>Happy creating,<br><strong>ReachUp AI Team</strong></p>
    </div></body></html>'''
    
    text_body = f"Welcome to ReachUp AI, {user.name}!\n\nYour 7-day free trial is active with 20 AI generations.\n\nLogin: http://localhost:5000/login\n\nReachUp AI Team"
    send_email(subject, [user.email], text_body, html_body)

def send_trial_expiring_email(user):
    days_left = 7 - (datetime.utcnow() - user.trial_start).days
    subject = f"Your ReachUp AI Trial Expires in {days_left} Days"
    html_body = f'''<html><body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #6C63FF;">Time to Upgrade?</h2>
    <p>Hi {user.name},</p>
    <p>Your <strong>7-day free trial expires in {days_left} days</strong>.</p>
    <h3>Starter Plan - PKR 8,000/month</h3>
    <ul>
    <li>200 generations per month</li>
    <li>All 7 features included</li>
    <li>Email support</li>
    </ul>
    <h3>Pro Plan - PKR 15,000/month</h3>
    <ul>
    <li>Unlimited generations</li>
    <li>All 7 features</li>
    <li>Priority support</li>
    </ul>
    <p><a href="http://localhost:5000/pricing" style="background-color: #6C63FF; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">View Pricing</a></p>
    <p>Best,<br><strong>ReachUp AI Team</strong></p>
    </div></body></html>'''
    
    text_body = f"Your trial expires in {days_left} days. Upgrade now: http://localhost:5000/pricing\n\nReachUp AI Team"
    send_email(subject, [user.email], text_body, html_body)

def send_upgrade_confirmation_email(user, plan):
    subject = f"ReachUp AI {plan.capitalize()} Plan Request Received"
    html_body = f'''<html><body style="font-family: Arial, sans-serif; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #6C63FF;">Upgrade Request Received!</h2>
    <p>Hi {user.name},</p>
    <p>We received your upgrade request for the <strong>{plan.capitalize()} Plan</strong>.</p>
    <h3>Next Steps:</h3>
    <p>Our team will contact you within <strong>24 hours</strong> with payment details.</p>
    <p>Payment methods we accept:</p>
    <ul>
    <li>JazzCash</li>
    <li>Easypaisa</li>
    <li>Bank Transfer</li>
    <li>Credit/Debit Card</li>
    </ul>
    <p>Once you pay, you will have instant access!</p>
    <p>Questions? Reply to this email!</p>
    <p>Best,<br><strong>ReachUp AI Team</strong></p>
    </div></body></html>'''
    
    text_body = f"Your upgrade request for {plan} plan received! We will contact you in 24 hours.\n\nReachUp AI Team"
    send_email(subject, [user.email], text_body, html_body)


# ==================== ROUTES ====================

# ---------------- HOME ----------------
@app.route("/")
def home():
    if current_user.is_authenticated:
        return render_template("index.html", user=current_user)
    return redirect(url_for('landing'))

# ---------------- LANDING PAGE ----------------
@app.route("/landing")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template("landing.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        business_type = request.form.get("business_type")
        city = request.form.get("city")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            app.logger.warning(f"[REGISTER] Failed - Email already exists: {email}")
            flash("Email already registered. Please login.")
            return redirect(url_for('login'))

        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            business_type=business_type,
            city=city
        )
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"[REGISTER] OK New user registered: {email} ({name}) from {city}, {business_type}")
        
        # send_welcome_email(new_user)
        # app.logger.info(f"[EMAIL] OK Welcome email triggered for: {email}")
        
        login_user(new_user)
        return redirect(url_for('home'))

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            app.logger.info(f"[LOGIN] OK User logged in: {email} ({user.name})")
            login_user(user)
            return redirect(url_for('home'))
        app.logger.warning(f"[LOGIN] X Failed - Invalid credentials: {email}")
        flash("Invalid email or password.")

    return render_template("login.html")


# ---------------- LOGOUT ----------------
@app.route("/logout")
@login_required
def logout():
    app.logger.info(f"[LOGOUT] OK User logged out: {current_user.email}")
    logout_user()
    return redirect(url_for('login'))


# ---------------- CHAT ----------------
@app.route("/chat", methods=["POST"])
@login_required
def chat():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[CHAT] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        message = data.get("message", "")

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": message}]
        )

        increment_usage()
        app.logger.info(f"[CHAT] OK Used by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "reply": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[CHAT] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- CAPTION ----------------
@app.route("/generate-caption", methods=["POST"])
@login_required
def generate_caption():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[CAPTION] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        desc = data.get("description", "")
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are a creative Instagram expert who knows this photographer personally.
Unique session: {seed}

Write a UNIQUE and FRESH Instagram caption for this specific photo:
"{desc}"

Critical rules:
- Write ONLY in {current_user.language_preference}
- Match the {current_user.instagram_tone} tone exactly
- Style must match their sample captions if provided
- Make it feel like THEY wrote it — not a generic AI
- Specific to {current_user.city} culture if relevant
- End with engaging question
- Include subtle call to action for bookings
- Maximum 150 words
- No hashtags
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[CAPTION] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "caption": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[CAPTION] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- HASHTAGS ----------------
@app.route("/generate-hashtags", methods=["POST"])
@login_required
def generate_hashtags():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[HASHTAGS] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        type_ = data.get("type", "")
        city = data.get("city", current_user.city)
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are a hashtag strategy expert.
Generate 25 UNIQUE Instagram hashtags for:
Business type: {type_}
City: {city}
Session: {seed}

Mix exactly:
- 8 small niche hashtags under 50K posts — very specific to {type_} in {city}
- 10 medium hashtags 50K to 500K posts — relevant to {type_}
- 5 large hashtags above 500K posts — broad reach
- 2 location hashtags specific to {city}

Important:
- Every generation must produce DIFFERENT hashtags
- Avoid overused generic hashtags
- Relevant to {current_user.client_type} type clients

Return only hashtags separated by spaces. Nothing else.
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[HASHTAGS] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "hashtags": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[HASHTAGS] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- AD COPY ----------------
@app.route("/generate-ad", methods=["POST"])
@login_required
def generate_ad():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[AD COPY] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        service = data.get("service", "")
        audience = data.get("audience", "")
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are a high converting ad copywriter.
Write a UNIQUE Facebook/Instagram ad for:
Service: {service}
Target audience: {audience}
Session: {seed}

Rules:
- Write in {current_user.language_preference}
- Match {current_user.instagram_tone} tone
- Speak directly to {current_user.client_type} clients
- Reference {current_user.city} if relevant
- Create emotional connection with {audience}
- Add urgency without being pushy
- Clear call to action
- Maximum 80 words
- No hashtags
- Every generation must feel DIFFERENT and FRESH
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[AD COPY] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "ad_copy": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[AD COPY] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- CONTENT CALENDAR ----------------
@app.route("/generate-calendar", methods=["POST"])
@login_required
def generate_calendar():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[CALENDAR] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        business_type = data.get("business_type", current_user.business_type)
        city = data.get("city", current_user.city)
        month = data.get("month", "")
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

Create a UNIQUE 4-week social media content calendar for:
Business: {business_type}
City: {city}
Month: {month}
Style: {current_user.photography_style}
Session: {seed}

For each week give exactly 4 post ideas.
Format each post exactly like this:
DAY: Monday
TYPE: Reel
TIME: 8 PM
IDEA: [specific idea relevant to {business_type} in {month}]

Rules:
- Ideas must match {current_user.photography_style} photography style
- Target {current_user.client_type} type clients
- Write ideas in {current_user.language_preference}
- Seasonal relevance to {month}
- Mix content types: Reels, Carousels, Photos, Stories
- Every calendar must be DIFFERENT — never repeat same ideas
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[CALENDAR] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "calendar": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[CALENDAR] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- DM RESPONSE ----------------
@app.route("/generate-dm", methods=["POST"])
@login_required
def generate_dm():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[DM] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        inquiry_type = data.get("inquiry_type", "")
        client_message = data.get("client_message", "")
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are an expert at converting social media inquiries into bookings.
Session: {seed}

A potential client sent this EXACT message:
"{client_message}"

Inquiry type: {inquiry_type}

Write a perfect DM response that:
- Write in {current_user.language_preference}
- Match {current_user.instagram_tone} tone
- Directly addresses what the client ACTUALLY said
- Feels warm and personal — from {current_user.brand_name or current_user.name}
- Professional and confident
- Creates excitement about working together
- Asks ONE smart qualifying question to move forward
- Maximum 100 words
- Response must be specific to what they asked — not generic
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[DM] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "dm_response": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[DM] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- POSTING TIME ----------------
@app.route("/best-posting-time", methods=["POST"])
@login_required
def best_posting_time():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[POSTING TIME] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        business_type = data.get("business_type", current_user.business_type)
        target_audience = data.get("target_audience", "")
        city = data.get("city", current_user.city)
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are a social media algorithm expert.

Give the best Instagram and Facebook posting times for:
Business: {business_type}
Target audience: {target_audience}
City: {city}
Client type: {current_user.client_type}

Format your response exactly like this:

INSTAGRAM:
Best days:
Top time 1:
Top time 2:
Top time 3:
Worst days:
Why these times work for {city} audience:

FACEBOOK:
Best days:
Top time 1:
Top time 2:
Top time 3:
Worst days:
Why these times work for {city} audience:

PRO TIP for {current_user.photography_style} photographers targeting {current_user.client_type} clients:

Keep it specific to {city} timezone and culture.
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )

        increment_usage()
        app.logger.info(f"[POSTING TIME] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "posting_times": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[POSTING TIME] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- COMPETITOR ANALYSIS ----------------
@app.route("/competitor-analysis", methods=["POST"])
@login_required
def competitor_analysis():
    try:
        has_access, reason = check_user_access()
        if not has_access:
            app.logger.warning(f"[COMPETITOR] X Access denied ({reason}): {current_user.email}")
            return jsonify({"error": reason}), 403

        data = request.json
        competitor_handle = data.get("competitor_handle", "")
        your_business = data.get("your_business", current_user.business_type)
        city = data.get("city", current_user.city)
        seed = get_unique_seed()
        brand_profile = get_user_brand_profile()

        prompt = f"""
{brand_profile}

You are a social media strategy expert.
Analyze this competitor for {current_user.brand_name or current_user.name}'s {your_business} business in {city}:
Competitor handle: {competitor_handle}
Session: {seed}

Give analysis in this exact format:

COMPETITOR: {competitor_handle}
ESTIMATED PROFILE:
Posting frequency:
Content style:
Likely audience:
Estimated engagement rate:

THEIR LIKELY STRENGTHS:
1.
2.
3.

THEIR LIKELY WEAKNESSES:
1.
2.
3.

HOW {current_user.brand_name or current_user.name} CAN BEAT THEM:
1.
2.
3.

CONTENT IDEAS TO OUTPERFORM {competitor_handle}:
1.
2.
3.

{current_user.brand_name or current_user.name}'s COMPETITIVE ADVANTAGE IN {city}:
"""

        client = get_groq_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0
        )

        increment_usage()
        app.logger.info(f"[COMPETITOR] OK Generated by: {current_user.email} (Usage: {current_user.generations_used})")

        return jsonify({
            "analysis": response.choices[0].message.content
        })

    except Exception as e:
        app.logger.error(f"[COMPETITOR] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- PRICING PAGE ----------------
@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


# ---------------- UPGRADE REQUEST ----------------
@app.route("/upgrade-request", methods=["POST"])
@login_required
def upgrade_request():
    try:
        data = request.json
        plan = data.get("plan", "")

        app.logger.info(f"[UPGRADE REQUEST] OK {current_user.email} ({current_user.name}) requested {plan} plan")
        
        # send_upgrade_confirmation_email(current_user, plan)
        # app.logger.info(f"[EMAIL] OK Upgrade confirmation email triggered for: {current_user.email}")

        return jsonify({
            "message": f"Thank you! We received your request for the {plan} plan. We will contact you within 24 hours on {current_user.email} with payment details."
        })

    except Exception as e:
        app.logger.error(f"[UPGRADE REQUEST] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- CHECK ACCESS ----------------
@app.route("/check-access")
@login_required
def check_access():
    days_used = (datetime.utcnow() - current_user.trial_start).days
    days_remaining = max(0, 7 - days_used)

    return jsonify({
        "plan": current_user.plan,
        "generations_used": current_user.generations_used,
        "generations_limit": get_plan_limits(current_user.plan),
        "days_remaining": days_remaining,
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin
    })


# ---------------- ONBOARDING ----------------
@app.route("/onboarding", methods=["POST"])
@login_required
def onboarding():
    try:
        data = request.json
        current_user.brand_name = data.get("brand_name", "")
        current_user.photography_style = data.get("photography_style", "")
        current_user.client_type = data.get("client_type", "")
        current_user.instagram_tone = data.get("instagram_tone", "")
        current_user.language_preference = data.get("language_preference", "")
        current_user.sample_captions = data.get("sample_captions", "")
        current_user.onboarding_done = True
        db.session.commit()

        app.logger.info(f"[ONBOARDING] OK Completed by: {current_user.email} ({current_user.brand_name})")

        return jsonify({"message": "Profile saved successfully"})

    except Exception as e:
        app.logger.error(f"[ONBOARDING] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- GET PROFILE ----------------
@app.route("/get-profile")
@login_required
def get_profile():
    return jsonify({
        "brand_name": current_user.brand_name,
        "photography_style": current_user.photography_style,
        "client_type": current_user.client_type,
        "instagram_tone": current_user.instagram_tone,
        "language_preference": current_user.language_preference,
        "sample_captions": current_user.sample_captions,
        "onboarding_done": current_user.onboarding_done,
        "city": current_user.city,
        "business_type": current_user.business_type
    })


# ---------------- UPDATE PROFILE ----------------
@app.route("/update-profile", methods=["POST"])
@login_required
def update_profile():
    try:
        data = request.json
        current_user.brand_name = data.get("brand_name", current_user.brand_name)
        current_user.photography_style = data.get("photography_style", current_user.photography_style)
        current_user.client_type = data.get("client_type", current_user.client_type)
        current_user.instagram_tone = data.get("instagram_tone", current_user.instagram_tone)
        current_user.language_preference = data.get("language_preference", current_user.language_preference)
        current_user.sample_captions = data.get("sample_captions", current_user.sample_captions)
        current_user.city = data.get("city", current_user.city)
        current_user.business_type = data.get("business_type", current_user.business_type)
        db.session.commit()

        app.logger.info(f"[UPDATE PROFILE] OK Updated by: {current_user.email}")

        return jsonify({"message": "Profile updated successfully"})

    except Exception as e:
        app.logger.error(f"[UPDATE PROFILE] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ---------------- TEST TRIAL EMAIL ----------------
@app.route("/test-trial-email")
@login_required
def test_trial_email():
    send_trial_expiring_email(current_user)
    app.logger.info(f"[TEST] Trial expiring email sent to {current_user.email}")
    return jsonify({"message": "Trial expiring email sent!"})


# ---------------- ADMIN PANEL ----------------
@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    users = User.query.order_by(User.id.desc()).all()

    total_users = len(users)
    trial_users = len([u for u in users if u.plan == 'trial'])
    starter_users = len([u for u in users if u.plan == 'starter'])
    pro_users = len([u for u in users if u.plan == 'pro'])
    monthly_revenue = (starter_users * 8000) + (pro_users * 15000)

    app.logger.info(f"[ADMIN] OK Admin panel accessed by: {current_user.email}")

    return render_template("admin.html",
        users=users,
        total_users=total_users,
        trial_users=trial_users,
        starter_users=starter_users,
        pro_users=pro_users,
        monthly_revenue=monthly_revenue
    )


@app.route("/admin/upgrade-user", methods=["POST"])
@login_required
@admin_required
def admin_upgrade_user():
    try:
        data = request.json
        user_id = data.get("user_id")
        plan = data.get("plan")

        user = User.query.get(int(user_id))
        if user:
            user.plan = plan
            user.generations_used = 0
            db.session.commit()
            app.logger.info(f"[ADMIN] OK Upgraded user {user.email} to {plan} plan (Admin: {current_user.email})")
            return jsonify({"message": f"User upgraded to {plan} successfully"})

        app.logger.warning(f"[ADMIN] X Upgrade failed - User {user_id} not found (Admin: {current_user.email})")
        return jsonify({"error": "User not found"}), 404

    except Exception as e:
        app.logger.error(f"[ADMIN] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/admin/delete-user", methods=["POST"])
@login_required
@admin_required
def admin_delete_user():
    try:
        data = request.json
        user_id = data.get("user_id")

        user = User.query.get(int(user_id))
        if user and not user.is_admin:
            db.session.delete(user)
            db.session.commit()
            app.logger.warning(f"[ADMIN] OK Deleted user {user.email} (Admin: {current_user.email})")
            return jsonify({"message": "User deleted successfully"})

        app.logger.warning(f"[ADMIN] X Delete failed - Cannot delete user {user_id} (Admin: {current_user.email})")
        return jsonify({"error": "Cannot delete this user"}), 400

    except Exception as e:
        app.logger.error(f"[ADMIN] ERROR - {current_user.email}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ==================== DATABASE + RUN ====================
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)