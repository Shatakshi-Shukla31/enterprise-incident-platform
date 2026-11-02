from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("incident_platform", broker=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    broker_transport_options={"socket_connect_timeout": 2, "visibility_timeout": 600},
    beat_schedule={
        "sla-check": {
            "task": "app.workers.tasks.check_sla",
            "schedule": float(settings.sla_check_interval_seconds),
        },
        "sla-rescore": {
            "task": "app.workers.tasks.rescore_open_incidents",
            "schedule": float(settings.sla_rescore_interval_seconds),
        },
        "reconcile-knowledge": {
            "task": "app.workers.tasks.reconcile_resolved_incidents",
            "schedule": 3600.0,
        },
        "auto-close": {
            "task": "app.workers.tasks.auto_close_resolved",
            "schedule": 3600.0,
        },
    },
)
