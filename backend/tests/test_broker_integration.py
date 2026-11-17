"""Broker integration tests with the real Redis instance (task 2.10).

The docker-compose Redis must be reachable (REDIS_URL or repo .env). These
tests enqueue real Celery messages but never require a running worker:
- broker reachable: dispatch_pending delivers and confirms the event
- broker unreachable: the event stays pending with a recorded failure
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.services import outbox_service

TEST_URL = os.environ.get("TEST_DATABASE_URL")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _redis_url() -> str | None:
    if os.environ.get("REDIS_URL"):
        return os.environ["REDIS_URL"]
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("REDIS_PORT="):
                return f"redis://127.0.0.1:{line.split('=', 1)[1].strip()}/0"
    return None


REDIS_URL = _redis_url()

pytestmark = pytest.mark.skipif(
    not (TEST_URL and REDIS_URL), reason="TEST_DATABASE_URL / Redis not available"
)


def _settings(broker: str) -> Settings:
    return Settings.model_validate(
        {"APP_SECRET_KEY": "t" * 40, "DATABASE_URL": TEST_URL, "REDIS_URL": broker}
    )


def _publish(db_engine, aggregate: str, task: str) -> None:
    with Session(db_engine) as session:
        with session.begin():
            outbox_service.publish_event(
                session.connection(), "tests.broker", "tests", aggregate,
                {"task": task, "kwargs": {}},
            )


def _event_status(db_engine, aggregate: str) -> str:
    with Session(db_engine) as session:
        return session.execute(
            text("SELECT status FROM outbox_events WHERE aggregate_type = 'tests' AND aggregate_id = :a"),
            {"a": aggregate},
        ).scalar_one()


def test_dispatch_confirms_against_real_broker(db_engine) -> None:
    import uuid

    aggregate = str(uuid.uuid4())
    _publish(db_engine, aggregate, "app.modules.async_execution.tasks.reap_stale_jobs")

    settings = _settings(REDIS_URL)
    with Session(db_engine) as session:
        result = outbox_service.dispatch_pending(session.connection(), settings)
        session.commit()
    assert len(result["dispatched"]) == 1
    assert _event_status(db_engine, aggregate) == "dispatched"

    # The message sits in the queue until a worker consumes it; clean it up so
    # the local broker does not accumulate dead test messages.
    import redis as redis_lib

    client = redis_lib.Redis.from_url(REDIS_URL)
    client.delete("async_jobs")


def test_unreachable_broker_keeps_event_pending(db_engine) -> None:
    import uuid

    aggregate = str(uuid.uuid4())
    _publish(db_engine, aggregate, "app.modules.async_execution.tasks.reap_stale_jobs")

    dead_broker = "redis://127.0.0.1:1/0"  # nothing listens here
    settings = _settings(dead_broker)
    with Session(db_engine) as session:
        result = outbox_service.dispatch_pending(session.connection(), settings)
        session.commit()
    assert result["failed"] and not result["dispatched"]
    assert _event_status(db_engine, aggregate) == "pending"

    with Session(db_engine) as session:
        row = session.execute(
            text("SELECT attempts, last_error FROM outbox_events WHERE aggregate_id = :a"),
            {"a": aggregate},
        ).one()
    assert row.attempts == 1 and "broker down" in (row.last_error or "") or row.last_error
