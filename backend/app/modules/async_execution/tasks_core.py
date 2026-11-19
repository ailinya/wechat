"""Pure-logic core for async job execution (no Celery import at module scope,
so tests can exercise the flow without broker configuration)."""

from __future__ import annotations

import time
import logging
from app.logging_config import safe_text

from celery.exceptions import SoftTimeLimitExceeded

from app.config import Settings
from app.database import session_for, get_engine
from app.modules.async_execution.registry import JobCancelled, JobContext, get_handler, get_engine_handler
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
    started=time.monotonic()

    with session_for(settings) as conn:
        with conn.begin():
            job = async_job_service.get_job(conn, job_id)
            if not job:
                return {"status": "unknown_job"}
            if not async_job_service.claim_job(conn, job_id):
                return {"status": "skipped", "reason": "not_pending"}
    context={'job_id':str(job_id),'job_type':job['job_type'],'resource_id':str(job['resource_id'])}
    logging.getLogger(__name__).info('job.started',extra=context)

    handler = get_handler(job["job_type"])
    engine_handler = get_engine_handler(job["job_type"])
    error: Exception | None = None
    last_error_text: str | None = None
    try:
        if handler is None and engine_handler is None:
            raise LookupError(f"no handler registered for {job['job_type']}")
        for attempt in range(max_attempts):
            try:
                if engine_handler:
                    outcome=engine_handler(get_engine(settings), job)
                else:
                    with session_for(settings) as conn:
                        with conn.begin():
                            handler(JobContext(job_id=job_id, job_type=job["job_type"], payload=job["payload"], conn=conn))
                    outcome=None
                with session_for(settings) as conn:
                    with conn.begin():
                        failed=isinstance(outcome,dict) and outcome.get('status')=='failed'
                        async_job_service.finish_job(conn,job_id,'failed' if failed else 'succeeded',last_error=safe_text(outcome.get('error') or 'business_execution_failed') if failed else None)
                        final=async_job_service.get_job(conn,job_id)
                logging.getLogger(__name__).info('job.finished',extra={**context,'status':final['status'],'duration_ms':round((time.monotonic()-started)*1000,2)})
                return {'status':final['status']}
            except JobCancelled:
                # Cancellation already wrote the terminal state; nothing further
                # to do and no new artifacts were committed.
                return {"status": "cancelled"}
            except SoftTimeLimitExceeded:
                last_error_text = "timeout: job exceeded soft time limit"
                break
            except Exception as exc:  # noqa: BLE001 - business failures are data
                error = exc
                last_error_text = safe_text(f"{type(exc).__name__}: {exc}")[:500]
                if attempt < max_attempts - 1 and backoff:
                    time.sleep(backoff)
    except LookupError as exc:
        last_error_text = safe_text(str(exc))[:500]

    with session_for(settings) as conn:
        with conn.begin():
            async_job_service.finish_job(conn, job_id, "failed", last_error=last_error_text)
    logging.getLogger(__name__).warning('job.failed',extra={**context,'duration_ms':round((time.monotonic()-started)*1000,2)})
    return {"status": "failed", "error": last_error_text}


def reap_stale_jobs_once(settings: Settings | None = None) -> dict:
    settings = settings or Settings.model_validate({})
    from app.services.runtime_service import recover_once
    return recover_once(get_engine(settings),settings)


def dispatch_outbox_once(settings: Settings | None = None) -> dict:
    settings = settings or Settings.model_validate({})
    with session_for(settings) as conn:
        result = outbox_service.dispatch_pending(conn, settings)
        conn.commit()
    return result
