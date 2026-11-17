"""Async job state service (task 2.3).

All transitions are conditional updates so that cancellation and completion
race to exactly one consistent terminal state, and a restarted process can
reconstruct everything from the async_jobs table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def create_job(
    conn: Connection,
    job_type: str,
    resource_type: str,
    resource_id: UUID | str,
    payload: dict[str, Any] | None = None,
    created_by: UUID | str | None = None,
) -> dict:
    job_id = str(uuid4())
    row = conn.execute(
        text(
            "INSERT INTO async_jobs (id, job_type, resource_type, resource_id, "
            "created_by, payload, status) "
            "VALUES (:id, :job_type, :resource_type, :resource_id, :created_by, "
            "CAST(:payload AS jsonb), 'pending') "
            "RETURNING id, job_type, resource_type, resource_id, created_by, "
            "payload, status, stage, progress, attempts, last_error, "
            "started_at, finished_at, created_at, updated_at"
        ),
        {
            "id": job_id,
            "job_type": job_type,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "created_by": str(created_by) if created_by else None,
            "payload": "{}" if not payload else __import__("json").dumps(payload),
        },
    ).mappings().one()
    return dict(row)


def get_job(conn: Connection, job_id: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM async_jobs WHERE id = :id"), {"id": str(job_id)}
    ).mappings().first()
    return dict(row) if row else None


def is_active(conn: Connection, job_id: str) -> bool:
    row = conn.execute(
        text("SELECT status FROM async_jobs WHERE id = :id"), {"id": str(job_id)}
    ).scalar()
    return row == "running"


def claim_job(conn: Connection, job_id: str) -> bool:
    """pending -> running for one delivery; False when the job was cancelled
    while pending or already claimed by another worker."""
    row = conn.execute(
        text(
            "UPDATE async_jobs SET status = 'running', attempts = attempts + 1, "
            "started_at = COALESCE(started_at, now()), updated_at = now() "
            "WHERE id = :id AND status = 'pending' RETURNING id"
        ),
        {"id": str(job_id)},
    ).scalar()
    return row is not None


def finish_job(conn: Connection, job_id: str, status: str, last_error: str | None = None) -> bool:
    """Move a running job to one terminal state; loses the race against an
    already-written terminal state (e.g. a concurrent cancellation)."""
    assert status in TERMINAL_STATES
    row = conn.execute(
        text(
            "UPDATE async_jobs SET status = CAST(:status AS varchar), last_error = :err, "
            "finished_at = now(), updated_at = now(), progress = "
            "CASE WHEN CAST(:status AS varchar) = 'succeeded' THEN 100 ELSE progress END "
            "WHERE id = :id AND status IN ('pending', 'running') RETURNING id"
        ),
        {"id": str(job_id), "status": status, "err": last_error},
    ).scalar()
    return row is not None


def update_progress(conn: Connection, job_id: str, stage: str, progress: int) -> None:
    conn.execute(
        text(
            "UPDATE async_jobs SET stage = :stage, progress = :progress, "
            "updated_at = now() WHERE id = :id AND status = 'running'"
        ),
        {"id": str(job_id), "stage": stage[:64], "progress": int(progress)},
    )


def reap_stale_jobs(conn: Connection, timeout_minutes: int) -> list[dict]:
    """Fail jobs whose worker vanished (running past the stale timeout); the
    outbox/job remains queryable and the caller may re-accept a new attempt."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    rows = conn.execute(
        text(
            "UPDATE async_jobs SET status = 'failed', last_error = 'worker interrupted', "
            "finished_at = now(), updated_at = now() "
            "WHERE status = 'running' AND updated_at < :cutoff "
            "RETURNING id, job_type"
        ),
        {"cutoff": cutoff},
    ).mappings().all()
    return [dict(r) for r in rows]
