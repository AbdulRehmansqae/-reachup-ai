from app import app, db, User

with app.app_context():
    user = User.query.filter_by(email="abdulrehmansqae@gmail.com").first()
    user.is_admin = True
    db.session.commit()
    print("Done!")