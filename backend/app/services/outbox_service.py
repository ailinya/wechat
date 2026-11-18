"""Transactional outbox: publish, dispatch, confirm (task 2.4).

publish_event runs inside the caller's business transaction, so a rollback
also discards the message. The dispatcher claims pending events with
FOR UPDATE SKIP LOCKED, delivers, and only then marks them dispatched;
a crash before the confirm leaves the event pending for redelivery, which
is safe because consumers (run_async_job) are idempotent by claim
semantics.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def publish_event(
    conn: Connection,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    payload: dict[str, Any] | None = None,
) -> str:
    row = conn.execute(
        text(
            "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id, payload) "
            "VALUES (:event_type, :aggregate_type, :aggregate_id, CAST(:payload AS jsonb)) "
            "RETURNING id"
        ),
        {
            "event_type": event_type,
            "aggregate_type": aggregate_type,
            "aggregate_id": str(aggregate_id),
            "payload": json.dumps(payload or {}, default=str),
        },
    ).scalar_one()
    return str(row)


def claim_batch(conn: Connection, batch_size: int = 20) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, event_type, payload FROM outbox_events "
            "WHERE status = 'pending' AND available_at <= now() "
            "AND (event_type <> 'material.ready' OR payload ? 'task') "
            "ORDER BY created_at LIMIT :batch FOR UPDATE SKIP LOCKED"
        ),
        {"batch": batch_size},
    ).mappings().all()
    return [dict(r) for r in rows]


def mark_dispatched(conn: Connection, event_id: str) -> None:
    conn.execute(
        text(
            "UPDATE outbox_events SET status = 'dispatched', dispatched_at = now() "
            "WHERE id = :id"
        ),
        {"id": event_id},
    )


def mark_delivery_failure(conn: Connection, event_id: str, error: str, backoff_seconds: int, max_attempts: int) -> None:
    """Record the failed attempt; after max_attempts the event stops being
    retried automatically and is parked as 'failed' for operators."""
    conn.execute(
        text(
            "UPDATE outbox_events SET attempts = attempts + 1, last_error = :err, "
            "status = CASE WHEN attempts + 1 >= :max_attempts THEN 'failed' ELSE status END, "
            "available_at = now() + make_interval(secs => :backoff * (attempts + 1)) "
            "WHERE id = :id"
        ),
        {"id": event_id, "err": error[:500], "max_attempts": max_attempts, "backoff": backoff_seconds},
    )


def deliver(settings, event: dict) -> None:
    """Send the event's task to the broker; the payload carries the task name.

    A broker app is built from the dispatcher's settings so the REDIS_URL of
    the running process is authoritative (tests point it at the local Redis).
    """
    payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
    task_name = payload.get("task")
    if not task_name:
        raise ValueError(f"outbox event {event['id']} has no task to deliver")
    from app.modules.async_execution.celery_app import create_celery_app

    create_celery_app(settings).send_task(task_name, kwargs=payload.get("kwargs") or {})


def dispatch_pending(conn: Connection, settings, deliver_fn=None) -> dict:
    """One dispatcher pass: claim, deliver, confirm. Redelivery-safe."""
    deliver_fn = deliver_fn or deliver
    max_attempts = settings.job_max_attempts
    backoff = settings.job_retry_backoff_seconds

    dispatched: list[str] = []
    failed: list[str] = []
    for event in claim_batch(conn):
        try:
            deliver_fn(settings, event)
        except Exception as exc:  # noqa: BLE001 - delivery failures are data
            mark_delivery_failure(conn, str(event["id"]), f"{type(exc).__name__}: {exc}", backoff, max_attempts)
            failed.append(str(event["id"]))
            continue
        mark_dispatched(conn, str(event["id"]))
        dispatched.append(str(event["id"]))
    return {"dispatched": dispatched, "failed": failed}
