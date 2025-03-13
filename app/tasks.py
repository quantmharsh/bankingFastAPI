# tasks.py
from .celery_app import celery_app

@celery_app.task
def send_email_notification(user_email: str, subject: str, body: str):
    # For prototyping, just print the message
    print(f"Simulated Email: To: {user_email}, Subject: {subject}, Body: {body}")
    return f"Email sent to {user_email}"
