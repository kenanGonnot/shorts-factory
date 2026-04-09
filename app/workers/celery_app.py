from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "shorts_factory",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=60 * 30,
)
