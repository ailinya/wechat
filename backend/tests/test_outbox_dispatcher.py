"""Outbox dispatcher tests (task 2.4): transactional publish, delivery
failure handling, and redelivery without duplicate side effects."""

from __future__ import annotations

import os
import os
import uuid

import pytest
from sqlalchemy import text

from app.config import Settings
from app.services import async_job_service, outbox_service


TEST_URL = os.environ.get("TEST_DATABASE_URL")


def _settings_for_tests() -> Settings:
    # Includes DATABASE_URL so execute_job can reach the isolated test DB.
    return Settings.model_validate(
        {
            "APP_SECRET_KEY": "t" * 40,
            "DATABASE_URL": TEST_URL,
            "JOB_MAX_ATTEMPTS": 2,
            "JOB_RETRY_BACKOFF_SECONDS": 0,
        }
    )


def test_publish_rollback_discards_event(db_engine) -> None:
    from sqlalchemy.orm import Session

    with pytest.raises(RuntimeError):
        with Session(db_engine) as session:
            with session.begin():
                conn = session.connection()
                outbox_service.publish_event(
                    conn, "tests.event", "tests", str(uuid.uuid4()), {"task": "noop"}
                )
                raise RuntimeError("business transaction failed")  # rolls back everything
    with Session(db_engine) as session:
        total = session.execute(text("SELECT count(*) FROM outbox_events WHERE event_type = 'tests.event'")).scalar_one()
    assert total == 0


def test_publish_commit_persists_event(db_engine) -> None:
    from sqlalchemy.orm import Session

    aggregate = str(uuid.uuid4())
    with Session(db_engine) as session:
        with session.begin():
            conn = session.connection()
            outbox_service.publish_event(
                conn, "tests.event", "tests", aggregate, {"task": "noop"}
            )
        total = session.execute(
            text("SELECT count(*) FROM outbox_events WHERE event_type = 'tests.event' AND aggregate_id = :a"),
            {"a": aggregate},
        ).scalar_one()
    assert total == 1


def test_delivery_failure_keeps_event_pending_and_counts_attempts(db_engine) -> None:
    from sqlalchemy.orm import Session

    aggregate = str(uuid.uuid4())
    with Session(db_engine) as session:
        with session.begin():
            outbox_service.publish_event(
                session.connection(), "tests.event", "tests", aggregate, {"task": "noop"}
            )

    settings = _settings_for_tests()
    attempts = []

    def failing_deliver(settings, event):
        attempts.append(event["id"])
        raise ConnectionError("broker down")

    with Session(db_engine) as session:
        result = outbox_service.dispatch_pending(session.connection(), settings, deliver_fn=failing_deliver)
        session.commit()
    assert len(attempts) == 1
    assert result["failed"] and not result["dispatched"]

    with Session(db_engine) as session:
        row = session.execute(
            text("SELECT status, attempts, last_error FROM outbox_events WHERE aggregate_id = :a"),
            {"a": aggregate},
        ).one()
    assert row.status == "pending" and row.attempts == 1
    assert "broker down" in row.last_error

    # Reaching the attempt limit parks the event as failed.
    with Session(db_engine) as session:
        outbox_service.dispatch_pending(session.connection(), settings, deliver_fn=failing_deliver)
        outbox_service.dispatch_pending(session.connection(), settings, deliver_fn=failing_deliver)
        session.commit()
        row = session.execute(
            text("SELECT status, attempts FROM outbox_events WHERE aggregate_id = :a"),
            {"a": aggregate},
        ).one()
    assert row.status == "failed" and row.attempts >= 2


def test_redelivery_after_crash_has_single_side_effect(db_engine) -> None:
    """Deliver succeeds but the confirm crashes -> the event stays pending and
    is redelivered; the consumer (execute_job) claims the job exactly once, so
    the business side effect happens once."""
    from sqlalchemy.orm import Session

    from app.modules.async_execution.registry import register_handler
    from app.modules.async_execution.tasks_core import execute_job

    job = None
    aggregate = str(uuid.uuid4())
    with Session(db_engine) as session:
        with session.begin():
            conn = session.connection()
            job = async_job_service.create_job(conn, "tests.redeliver", "tests", aggregate)
            outbox_service.publish_event(
                conn, "tests.job", "tests", aggregate,
                {"task": "app.modules.async_execution.tasks.run_async_job", "kwargs": {"job_id": job["id"]}},
            )

    effects = []
    register_handler("tests.redeliver", lambda ctx: effects.append(ctx.job_id))
    settings = _settings_for_tests()

    delivered = []

    def crashing_deliver(settings, event):
        delivered.append(event["id"])
        # The task really runs (side effect happens)...
        payload = event["payload"]
        task_name = payload["task"] if isinstance(payload, dict) else __import__("json").loads(payload)["task"]
        assert task_name.endswith("run_async_job")
        execute_job(job["id"], settings)
        # ...but the process dies before the dispatcher confirms.
        raise ConnectionError("crashed after delivery")

    with Session(db_engine) as session:
        outbox_service.dispatch_pending(session.connection(), settings, deliver_fn=crashing_deliver)
        session.commit()

    with Session(db_engine) as session:
        job_row = session.execute(
            text("SELECT status FROM async_jobs WHERE id = :id"), {"id": job["id"]}
        ).scalar_one()
        event_row = session.execute(
            text("SELECT status FROM outbox_events WHERE aggregate_id = :a"), {"a": aggregate}
        ).scalar_one()
    assert job_row == "succeeded"  # side effect already applied
    assert event_row == "pending"  # confirm never happened

    # Broker recovers: redelivery runs the consumer again, claim semantics
    # skip the finished job, and the event is finally confirmed.
    with Session(db_engine) as session:
        result = outbox_service.dispatch_pending(
            session.connection(), settings,
            deliver_fn=lambda s, e: execute_job(job["id"], s),
        )
        session.commit()
    assert len(result["dispatched"]) == 1
    with Session(db_engine) as session:
        effects_count = session.execute(
            text(
                "SELECT count(*) FROM async_jobs WHERE id = :id AND status = 'succeeded'"
            ),
            {"id": job["id"]},
        ).scalar_one()
        job_row = session.execute(
            text("SELECT attempts FROM async_jobs WHERE id = :id"), {"id": job["id"]}
        ).scalar_one()
    assert effects_count == 1
    assert job_row == 1  # only the first delivery claimed the job
