"""Persisted Idempotency-Key protection (task 2.5).

Same key + same fingerprint in the same (scope, user) replays the original
response; same key + different fingerprint is a conflict; concurrent
requests race on the unique (scope, user_id, key) constraint so only one
business object is created.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

DEFAULT_RETENTION_DAYS = 7


def request_fingerprint(parts: Any) -> str:
    """Stable sha256 over canonically serialized request parameters."""
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyReplay(Exception):
    """Signals an existing result for the same key + fingerprint."""

    def __init__(self, row: dict):
        super().__init__(str(row.get("id")))
        self.row = row


class IdempotencyConflict(Exception):
    """Same key reused with different request content."""


def begin_request(
    conn: Connection,
    scope: str,
    user_id: UUID | str,
    key: str,
    fingerprint: str,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict:
    """Register (or replay) an idempotent request.

    Returns the idempotency_keys row. Callers must check:
    - row has response_status -> replay: respond with the stored result
    - row.request_fingerprint != fingerprint -> 409 conflict
    - otherwise -> run the business logic, then call store_response().
    """
    expires = (
        datetime.now(timezone.utc) + timedelta(days=retention_days)
    ).isoformat()

    inserted = conn.execute(
        text(
            "INSERT INTO idempotency_keys (scope, user_id, key, "
            "request_fingerprint, expires_at) "
            "VALUES (:scope, :user_id, :key, :fp, :expires) "
            "ON CONFLICT (scope, user_id, key) DO NOTHING RETURNING id"
        ),
        {"scope": scope, "user_id": str(user_id), "key": key[:128], "fp": fingerprint, "expires": expires},
    ).scalar()
    if inserted:
        return dict(
            conn.execute(text("SELECT * FROM idempotency_keys WHERE id = :id"), {"id": str(inserted)})
            .mappings()
            .one()
        )

    row = conn.execute(
        text("SELECT * FROM idempotency_keys WHERE scope = :scope AND user_id = :user_id AND key = :key"),
        {"scope": scope, "user_id": str(user_id), "key": key[:128]},
    ).mappings().one()
    row = dict(row)

    if row["expires_at"] is not None:
        expired = row["expires_at"] if row["expires_at"].tzinfo else row["expires_at"].replace(tzinfo=timezone.utc)
        if expired < datetime.now(timezone.utc):
            conn.execute(text("DELETE FROM idempotency_keys WHERE id = :id"), {"id": str(row["id"])})
            fresh = begin_request(conn, scope, user_id, key, fingerprint, retention_days)
            return fresh

    if row["request_fingerprint"] != fingerprint:
        raise IdempotencyConflict()

    if row["response_status"] is not None:
        raise IdempotencyReplay(row)

    # Same key+content, still running: return the pending row; the caller
    # continues and will store the response under the same row.
    return row


def store_response(
    conn: Connection,
    idempotency_id: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    conn.execute(
        text(
            "UPDATE idempotency_keys SET response_status = :status, "
            "response_body = CAST(:body AS jsonb) WHERE id = :id"
        ),
        {"id": str(idempotency_id), "status": status_code, "body": json.dumps(body, ensure_ascii=False, default=str)},
    )
