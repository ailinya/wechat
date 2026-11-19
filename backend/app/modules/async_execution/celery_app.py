"""Celery application for async job execution (task 2.3).

The broker is Redis; job state lives in PostgreSQL (async_jobs), so the
Celery result backend stays unused and restarted processes can always
reconstruct the current state from the database.
"""

from __future__ import annotations

from celery import Celery

from app.config import load_settings
from celery.signals import setup_logging


@setup_logging.connect
def structured_celery_logging(**kwargs):
    from app.logging_config import configure_logging
    configure_logging(load_settings().log_level)


def create_celery_app(settings=None) -> Celery:
    settings = settings or load_settings()
    app = Celery(
        "wetchat",
        broker=settings.redis_url,
        backend=None,
        include=["app.modules.async_execution.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=False,
        task_soft_time_limit=settings.job_soft_time_limit_seconds,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        broker_connection_timeout=3,
        broker_transport_options={'socket_connect_timeout':3,'socket_timeout':3,'visibility_timeout':600},
        task_routes={"app.modules.async_execution.*": {"queue": "async_jobs"}},
    )
    app.conf.beat_schedule = {
        "reap-stale-jobs": {
            "task": "app.modules.async_execution.tasks.reap_stale_jobs",
            "schedule": 300.0,
        },
        "dispatch-outbox": {
            "task": "app.modules.async_execution.tasks.dispatch_outbox",
            "schedule": 5.0,
        },
        "schedule-collection-runs": {
            "task": "app.modules.async_execution.tasks.schedule_collection_runs",
            "schedule": 60.0,
        },
        "schedule-creation-rules": {
            "task": "app.modules.async_execution.tasks.schedule_creation_rules",
            "schedule": 60.0,
        },
        'schedule-publications': {
            'task': 'app.modules.async_execution.tasks.schedule_publications',
            'schedule': 30.0,
        },
    }
    app.conf.beat_schedule['deliver-notifications'] = {'task': 'app.modules.async_execution.tasks.deliver_notifications', 'schedule': 30.0}
    app.conf.wetchat_settings = settings
    return app


# Built lazily so importing this module never requires runtime configuration
# (tests import tasks_core only). `celery -A ...celery_app:celery_app` still
# resolves through the module __getattr__ below.
_celery_app = None


def get_celery_app() -> Celery:
    global _celery_app
    if _celery_app is None:
        _celery_app = create_celery_app()
    return _celery_app


def __getattr__(name: str):
    if name == "celery_app":
        return get_celery_app()
    raise AttributeError(name)
