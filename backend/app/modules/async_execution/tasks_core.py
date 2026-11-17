"""Pure-logic core for async job execution (no Celery import at module scope,
so tests can exercise the flow without broker configuration)."""

from __future__ import annotations

import time

from celery.exceptions import SoftTimeLimitExceeded

from app.config import Settings
from app.database import session_for
from app.modules.async_execution.registry import JobCancelled, JobContext, get_handler
from app.services import async_job_service, outbox_service


def execute_job(job_id: str, settings: Settings | None = None) -> dict:
    """Claim and execute one async job with bounded retries.

    Cancellation boundary: claim only succeeds for pending jobs, handlers
    must call ``context.checkpoint()`` between side effects, and finish_job
    loses the race against a concurrent cancellation, so a cancelled job
    never produces further artifacts.
    """
    settings = settings or Settings.model_validate({})  # falls back to env
    max_attempts = settings.job_max_attempts
    backoff = settings.job_retry_backoff_seconds

    with session_for(settings) as conn:
        with conn.begin():
            job = async_job_service.get_job(conn, job_id)
            if not job:
                return {"status": "unknown_job"}
            if not async_job_service.claim_job(conn, job_id):
                return {"status": "skipped", "reason": "not_pending"}

    handler = get_handler(job["job_type"])
    error: Exception | None = None
    last_error_text: str | None = None
    try:
        if handler is None:
            raise LookupError(f"no handler registered for {job['job_type']}")
        for attempt in range(max_attempts):
            try:
                with session_for(settings) as conn:
                    with conn.begin():
                        handler(JobContext(job_id=job_id, job_type=job["job_type"], payload=job["payload"], conn=conn))
                with session_for(settings) as conn:
                    with conn.begin():
                        async_job_service.finish_job(conn, job_id, "succeeded")
                return {"status": "succeeded"}
            except JobCancelled:
                # Cancellation already wrote the terminal state; nothing further
                # to do and no new artifacts were committed.
                return {"status": "cancelled"}
            except SoftTimeLimitExceeded:
                last_error_text = "timeout: job exceeded soft time limit"
                break
            except Exception as exc:  # noqa: BLE001 - business failures are data
                error = exc
                last_error_text = f"{type(exc).__name__}: {exc}"[:500]
                if attempt < max_attempts - 1 and backoff:
                    time.sleep(backoff)
    except LookupError as exc:
        last_error_text = str(exc)[:500]

    with session_for(settings) as conn:
        with conn.begin():
            async_job_service.finish_job(conn, job_id, "failed", last_error=last_error_text)
    return {"status": "failed", "error": last_error_text}


def reap_stale_jobs_once(settings: Settings | None = None) -> dict:
    settings = settings or Settings.model_validate({})
    with session_for(settings) as conn:
        with conn.begin():
            reaped = async_job_service.reap_stale_jobs(conn, settings.job_stale_timeout_minutes)
    return {"reaped": len(reaped), "jobs": [r["id"] for r in reaped]}


def dispatch_outbox_once(settings: Settings | None = None) -> dict:
    settings = settings or Settings.model_validate({})
    with session_for(settings) as conn:
        result = outbox_service.dispatch_pending(conn, settings)
        conn.commit()
    return result
