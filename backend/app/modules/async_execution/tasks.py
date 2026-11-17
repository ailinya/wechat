"""Celery task wrappers (worker entrypoints for tasks_core functions)."""

from __future__ import annotations

from app.modules.async_execution.celery_app import celery_app
from app.modules.async_execution.registry import register_handler
from app.services import async_job_service
from app.modules.async_execution.tasks_core import dispatch_outbox_once, execute_job, reap_stale_jobs_once


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
