"""Read/cancel helpers for persistent async jobs (task 2.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Connection, text


def get_job(conn: Connection, job_id: UUID) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, job_type, resource_type, resource_id, created_by, payload, status, "
            "stage, progress, attempts, last_error, started_at, finished_at, "
            "created_at, updated_at FROM async_jobs WHERE id = :id"
        ),
        {"id": str(job_id)},
    ).mappings().first()
    return dict(row) if row else None


def list_jobs(
    conn: Connection,
    created_by: UUID,
    job_type: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    clauses = ["created_by = :user_id"]
    params: dict = {"user_id": str(created_by), "limit": page_size, "offset": (page - 1) * page_size}
    if job_type:
        clauses.append("job_type = :job_type")
        params["job_type"] = job_type
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = " AND ".join(clauses)
    total = conn.execute(
        text(f"SELECT count(*) FROM async_jobs WHERE {where}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT id, job_type, resource_type, resource_id, payload, status, "
            f"stage, progress, attempts, last_error, started_at, finished_at, "
            f"created_at, updated_at FROM async_jobs WHERE {where} "
            f"ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows], total


def cancel_job(conn: Connection, job_id: UUID, user_id: UUID) -> dict | None:
    """Cancel a pending/running job; returns the updated row or None when the
    job already reached a terminal state (one consistent outcome wins)."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        text(
            "UPDATE async_jobs SET status = 'cancelled', finished_at = :now, "
            "updated_at = :now WHERE id = :id AND created_by = :user_id "
            "AND status IN ('pending', 'running') "
            "RETURNING id, job_type, resource_type, resource_id, payload, status, "
            "stage, progress, attempts, last_error, started_at, finished_at, "
            "created_at, updated_at"
        ),
        {"id": str(job_id), "user_id": str(user_id), "now": now},
    ).mappings().first()
    return dict(row) if row else None
