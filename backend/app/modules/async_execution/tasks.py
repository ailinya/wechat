"""Celery task wrappers (worker entrypoints for tasks_core functions)."""

from __future__ import annotations

from app.modules.async_execution.celery_app import celery_app
from app.modules.async_execution.registry import register_handler
from app.services import async_job_service
from app.modules.async_execution.tasks_core import dispatch_outbox_once, execute_job, reap_stale_jobs_once

# Importing the collection module registers the collection.run handler and
# defines the Beat scheduling task.
from app.modules.collection import tasks as _collection_tasks  # noqa: F401


@celery_app.task(name="app.modules.async_execution.tasks.run_async_job")
def run_async_job(job_id: str) -> dict:
    return execute_job(job_id)


@celery_app.task(name="app.modules.async_execution.tasks.reap_stale_jobs")
def reap_stale_jobs() -> dict:
    return reap_stale_jobs_once()


@celery_app.task(name="app.modules.async_execution.tasks.dispatch_outbox")
def dispatch_outbox() -> dict:
    return dispatch_outbox_once()

def _system_healthcheck(ctx) -> None:
    """Built-in smoke handler: verifies DB access and progress reporting.
    Used by operators (and phase acceptance) to prove the worker pipeline."""
    from sqlalchemy import text

    async_job_service.update_progress(ctx.conn, ctx.job_id, "checking", 50)
    ctx.conn.execute(text("SELECT 1"))


register_handler("system.healthcheck", _system_healthcheck)

from app.modules.async_execution.registry import register_engine_handler
from app.services.wechat_sync_worker import sync_job
from app.services.publishing_worker import publish_job, schedule_once
from app.services.wechat_draft_worker import draft_job, recover_stale
from app.database import get_engine
from app.config import load_settings

register_engine_handler('account.sync', sync_job)
register_engine_handler('publish.execute', publish_job)
register_engine_handler('wechat.draft', draft_job)


@celery_app.task(name='app.modules.async_execution.tasks.schedule_publications')
def schedule_publications():
    settings = load_settings()
    with get_engine(settings).begin() as conn:
        recover_stale(conn, settings.job_stale_timeout_minutes)
    return schedule_once(get_engine(settings), settings)


@celery_app.task(name='app.modules.async_execution.tasks.deliver_notifications')
def deliver_notifications():
    from app.services.notification_service import deliver
    with get_engine(load_settings()).begin() as conn:
        return {'delivered': deliver(conn)}
