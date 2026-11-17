"""Async job execution tests (task 2.3): state transitions, retries,
cancellation boundary and stale reaping, all against the isolated test DB."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.modules.async_execution import registry
from app.modules.async_execution.registry import JobContext
from app.services import async_job_service

TEST_URL = os.environ.get("TEST_DATABASE_URL")

TEST_SETTINGS = Settings.model_validate(
    {"APP_SECRET_KEY": "t" * 40, "DATABASE_URL": TEST_URL}
)


@pytest.fixture
def db(db_engine):
    session = Session(bind=db_engine, expire_on_commit=False)
    yield session
    session.close()


def _conn(session):
    return session.connection()


def _make_job(session, job_type="tests.demo"):
    job = async_job_service.create_job(
        _conn(session), job_type, "tests", "00000000-0000-0000-0000-000000000001"
    )
    session.commit()
    return job


def test_job_lifecycle_transitions(db) -> None:
    job = _make_job(db)
    conn = _conn(db)

    assert job["status"] == "pending"
    assert async_job_service.claim_job(conn, job["id"])
    assert not async_job_service.claim_job(conn, job["id"])  # double claim rejected
    assert async_job_service.get_job(conn, job["id"])["attempts"] == 1
    db.commit()

    assert async_job_service.finish_job(_conn(db), job["id"], "succeeded")
    assert not async_job_service.finish_job(_conn(db), job["id"], "failed")  # terminal already
    db.commit()
    assert async_job_service.get_job(_conn(db), job["id"])["status"] == "succeeded"


def test_claim_rejected_after_cancel(db) -> None:
    job = _make_job(db)
    async_job_service.finish_job(_conn(db), job["id"], "cancelled")
    db.commit()
    assert not async_job_service.claim_job(_conn(db), job["id"])


def test_run_task_success_updates_state(db) -> None:
    job = _make_job(db, "tests.ok")
    ran = []
    registry.register_handler("tests.ok", lambda ctx: ran.append(ctx.job_id))

    from app.modules.async_execution.tasks_core import execute_job

    result = execute_job(job["id"], TEST_SETTINGS)
    assert result["status"] == "succeeded"
    assert ran == [job["id"]]
    row = async_job_service.get_job(_conn(db), job["id"])
    assert row["status"] == "succeeded" and row["progress"] == 100


def test_run_task_failure_records_reason(db) -> None:
    job = _make_job(db, "tests.fail")

    def boom(ctx):
        raise RuntimeError("external service down")

    registry.register_handler("tests.fail", boom)
    from app.modules.async_execution.tasks_core import execute_job

    result = execute_job(job["id"], TEST_SETTINGS)
    assert result["status"] == "failed"
    assert "external service down" in result["error"]
    row = async_job_service.get_job(_conn(db), job["id"])
    assert row["status"] == "failed" and "external service down" in row["last_error"]


def test_unknown_job_type_fails_clearly(db) -> None:
    job = _make_job(db, "tests.nohandler")
    from app.modules.async_execution.tasks_core import execute_job

    result = execute_job(job["id"], TEST_SETTINGS)
    assert result["status"] == "failed"
    assert "no handler" in result["error"]


def test_cancelled_mid_run_produces_no_more_side_effects(db_engine, db) -> None:
    job = _make_job(db, "tests.cancel")
    effects = []

    def handler(ctx: JobContext):
        effects.append("step1")
        # Simulate a user cancelling from another process mid-run.
        with Session(db_engine) as other:
            async_job_service.finish_job(other.connection(), job["id"], "cancelled")
            other.commit()
        ctx.checkpoint()
        effects.append("step2")

    registry.register_handler("tests.cancel", handler)
    from app.modules.async_execution.tasks_core import execute_job

    result = execute_job(job["id"], TEST_SETTINGS)
    assert result["status"] == "cancelled"
    assert effects == ["step1"]
    assert async_job_service.get_job(_conn(db), job["id"])["status"] == "cancelled"


def test_stale_running_jobs_are_reaped(db) -> None:
    job = _make_job(db)
    conn = _conn(db)
    async_job_service.claim_job(conn, job["id"])
    # Backdate the updated_at so the job looks abandoned.
    conn.execute(
        text("UPDATE async_jobs SET updated_at = now() - interval '2 hours' WHERE id = :id"),
        {"id": job["id"]},
    )
    db.commit()

    reaped = async_job_service.reap_stale_jobs(_conn(db), TEST_SETTINGS.job_stale_timeout_minutes)
    db.commit()
    assert [r["id"] for r in reaped] == [job["id"]]
    row = async_job_service.get_job(_conn(db), job["id"])
    assert row["status"] == "failed"
    assert "worker interrupted" in row["last_error"]
