"""Tests for the async-execution database setup (task 2.1).

Covers the migration contract: idempotency keys are unique per
(scope, user), stored objects cannot be double-registered, and job
status values are constrained.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def schema_engine():
    """Migrated empty schema without seeded accounts (no seeding needed here)."""
    from conftest import reset_schema

    reset_schema()
    engine = create_engine(TEST_URL)
    yield engine
    engine.dispose()


def _insert_job(engine, **overrides):
    values = {
        "job_type": "collection.fetch",
        "resource_type": "collection_task",
        "resource_id": str(uuid.uuid4()),
    }
    values.update(overrides)
    sets = ", ".join(f"{k} = :{k}" for k in values)
    with engine.connect() as conn:
        conn.execute(
            text(f"INSERT INTO async_jobs ({', '.join(values)}) VALUES ({sets})"),
            values,
        )
        conn.commit()


def test_async_jobs_reject_unknown_status(schema_engine) -> None:
    with pytest.raises(Exception):
        _insert_job(schema_engine, status="finished")


def test_idempotency_key_unique_per_scope_and_user(schema_engine) -> None:
    user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
    with schema_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, account, name, status, password_hash) "
                "VALUES (:id, 'idem-a', 'A', 'active', 'x')"
            ),
            {"id": user_a},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, account, name, status, password_hash) "
                "VALUES (:id, 'idem-b', 'B', 'active', 'x')"
            ),
            {"id": user_b},
        )
        conn.commit()

    row = {
        "scope": "articles.create",
        "key": "client-key-1",
        "request_fingerprint": "f" * 64,
        "response_status": 201,
    }
    with schema_engine.connect() as conn:
        for user in (user_a, user_b):
            conn.execute(
                text(
                    "INSERT INTO idempotency_keys (scope, user_id, key, "
                    "request_fingerprint, response_status, expires_at) "
                    "VALUES (:scope, :user_id, :key, :fp, :status, now() + interval '1 day')"
                ),
                {**row, "user_id": user, "fp": row["request_fingerprint"], "status": row["response_status"]},
            )
        conn.commit()

    # Same user + scope + key -> violates the unique constraint
    with pytest.raises(Exception):
        with schema_engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO idempotency_keys (scope, user_id, key, "
                    "request_fingerprint, response_status, expires_at) "
                    "VALUES (:scope, :user_id, :key, :fp, :status, now() + interval '1 day')"
                ),
                {**row, "user_id": user_a, "fp": row["request_fingerprint"], "status": row["response_status"]},
            )
            conn.commit()


def test_stored_objects_cannot_be_double_registered(schema_engine) -> None:
    uploader = str(uuid.uuid4())
    with schema_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, account, name, status, password_hash) "
                "VALUES (:id, 'uploader', 'U', 'active', 'x')"
            ),
            {"id": uploader},
        )
        conn.commit()

    insert = text(
        "INSERT INTO stored_objects (bucket, object_key, size_bytes, "
        "content_type, sha256, uploader_id) VALUES (:bucket, :key, 10, "
        "'image/png', :sha, :uploader) ON CONFLICT (bucket, object_key) "
        "DO NOTHING RETURNING id"
    )
    payload = {"bucket": "attachments", "key": "2026/11/a.png", "sha": "a" * 64, "uploader": uploader}
    with schema_engine.connect() as conn:
        first = conn.execute(insert, payload).scalar()
        conn.commit()
    with schema_engine.connect() as conn:
        second = conn.execute(insert, payload).scalar()
        conn.commit()

    assert first is not None and second is None
    with schema_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM stored_objects WHERE bucket = :b AND object_key = :k"),
            {"b": "attachments", "k": "2026/11/a.png"},
        ).scalar_one()
    assert count == 1


def test_outbox_and_operation_logs_defaults(schema_engine) -> None:
    with schema_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO outbox_events (event_type, aggregate_type, aggregate_id) "
                "VALUES ('collection.completed', 'collection_task', :id)"
            ),
            {"id": str(uuid.uuid4())},
        )
        conn.execute(
            text(
                "INSERT INTO operation_logs (action, object_type, result) "
                "VALUES ('users.create', 'user', 'success')"
            )
        )
        conn.commit()
        outbox = conn.execute(
            text("SELECT status, attempts FROM outbox_events")
        ).one()
        log = conn.execute(
            text("SELECT result, detail FROM operation_logs")
        ).one()
    assert outbox.status == "pending" and outbox.attempts == 0
    assert log.result == "success" and log.detail == {}
