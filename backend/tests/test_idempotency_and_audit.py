"""Idempotency service tests (task 2.5) and audit masking tests (task 2.7)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.services import audit_service, idempotency_service
from app.services.idempotency_service import IdempotencyConflict, IdempotencyReplay, request_fingerprint


@pytest.fixture
def user_id(db_engine):
    from sqlalchemy.orm import Session

    uid = str(uuid.uuid4())
    with Session(db_engine) as session:
        session.execute(
            text(
                "INSERT INTO users (id, account, name, status, password_hash) "
                "VALUES (:id, :account, 'U', 'active', 'x')"
            ),
            {"id": uid, "account": f"idem-{uid[:8]}"},
        )
        session.commit()
    return uid


def _begin(engine, user, key, payload):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        row = idempotency_service.begin_request(
            session.connection(), "tests.scope", user, key,
            request_fingerprint(payload),
        )
        session.commit()
    return row


def test_same_key_same_content_replays(db_engine, user_id) -> None:
    payload = {"account": "a", "password": "s3cret"}
    first = _begin(db_engine, user_id, "key-1", payload)

    # Store a response for the first row, then replay.
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        idempotency_service.store_response(
            session.connection(), first["id"], 201, {"id": "created-1"}
        )
        session.commit()

    with pytest.raises(IdempotencyReplay) as excinfo:
        _begin(db_engine, user_id, "key-1", payload)
    assert excinfo.value.row["response_body"] == {"id": "created-1"}


def test_same_key_different_content_conflicts(db_engine, user_id) -> None:
    _begin(db_engine, user_id, "key-2", {"a": 1})
    with pytest.raises(IdempotencyConflict):
        _begin(db_engine, user_id, "key-2", {"a": 2})


def test_concurrent_same_key_creates_one_row(db_engine, user_id) -> None:
    fingerprint = request_fingerprint({"same": True})
    from sqlalchemy.orm import Session

    results = []
    with Session(db_engine) as session:
        for _ in range(2):
            row = idempotency_service.begin_request(
                session.connection(), "tests.concurrent", user_id, "key-3", fingerprint
            )
            results.append(row["id"])
        session.commit()
    assert results[0] == results[1]  # second call found the same pending row

    with Session(db_engine) as session:
        count = session.execute(
            text(
                "SELECT count(*) FROM idempotency_keys "
                "WHERE scope = 'tests.concurrent' AND user_id = :u AND key = 'key-3'"
            ),
            {"u": user_id},
        ).scalar_one()
    assert count == 1


def test_expired_key_can_be_reused(db_engine, user_id) -> None:
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session

    key = "key-old"
    _begin(db_engine, user_id, key, {"old": True})
    with Session(db_engine) as session:
        session.execute(
            text(
                "UPDATE idempotency_keys SET expires_at = :past "
                "WHERE scope = 'tests.scope' AND user_id = :u AND key = :k"
            ),
            {"past": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "u": user_id, "k": key},
        )
        session.commit()

    row = _begin(db_engine, user_id, key, {"new": True})  # different content ok after expiry
    assert row["request_fingerprint"] == request_fingerprint({"new": True})


def test_expired_pending_key_with_same_content_is_reusable(db_engine, user_id) -> None:
    """Expired rows are deleted and a fresh registration is allowed."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.orm import Session

    key = "key-expired-same"
    _begin(db_engine, user_id, key, {"x": 1})
    with Session(db_engine) as session:
        session.execute(
            text(
                "UPDATE idempotency_keys SET expires_at = :past "
                "WHERE scope = 'tests.scope' AND user_id = :u AND key = :k"
            ),
            {"past": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "u": user_id, "k": key},
        )
        session.commit()
    row = _begin(db_engine, user_id, key, {"x": 1})
    assert row["request_fingerprint"] == request_fingerprint({"x": 1})


def test_fingerprint_is_stable_and_content_sensitive() -> None:
    assert request_fingerprint({"a": 1, "b": 2}) == request_fingerprint({"b": 2, "a": 1})
    assert request_fingerprint({"a": 1}) != request_fingerprint({"a": 2})


def test_audit_masks_sensitive_fields() -> None:
    detail = {
        "account": "admin",
        "password": "hunter2",
        "session_token": "abc",
        "nested": {"api_key": "xyz", "note": "safe"},
        "list": [{"secret_value": "hide"}, "plain"],
    }
    masked = audit_service.mask(detail)
    assert masked["password"] == "***"
    assert masked["session_token"] == "***"
    assert masked["nested"]["api_key"] == "***"
    assert masked["nested"]["note"] == "safe"
    assert masked["list"][0]["secret_value"] == "***"
    assert masked["list"][1] == "plain"
    assert masked["account"] == "admin"


def test_record_operation_writes_masked_row(db_engine, user_id) -> None:
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        log_id = audit_service.record_operation(
            session.connection(),
            user_id=user_id,
            action="tests.action",
            object_type="tests",
            result="denied",
            detail={"password": "never-store", "size": 10},
        )
        session.commit()
    with Session(db_engine) as session:
        row = session.execute(
            text("SELECT result, detail FROM operation_logs WHERE id = :id"), {"id": log_id}
        ).one()
    assert row.result == "denied"
    assert row.detail["password"] == "***"
    assert row.detail["size"] == 10
