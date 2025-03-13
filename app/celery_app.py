# celery_app.py
import os
from celery import Celery

# Use Redis running on localhost (default port 6379)
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("banking_tasks", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

# Optional Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
# This will automatically discover tasks in the module "app.tasks"
celery_app.autodiscover_tasks(["app.tasks"], force=True)
