from celery import Celery

from app.config import settings

celery_app = Celery(
    "tg_notify",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="tg_notify",
    broker_connection_retry_on_startup=True,
)
