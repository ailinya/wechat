"""Schema tests for task 3.2 (collection tables & constraints).

DDL-shape tests run everywhere by capturing the migration's op.execute calls.
Constraint-behaviour tests need a real PostgreSQL (TEST_DATABASE_URL) and skip
otherwise, matching the conftest convention so the default suite stays isolated.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0003_collection.py"
)
TEST_URL = os.environ.get("TEST_DATABASE_URL")


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0003_collection", MIGRATION)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


@pytest.fixture
def ddl() -> str:
    mod = _load_migration()
    recorder = _RecordingOp()
    mod.op = recorder
    mod.upgrade()
    return "\n".join(recorder.statements)


# --- DDL shape (no database required) ---

def test_all_five_tables_created(ddl: str) -> None:
    for table in (
        "collection_sources",
        "collection_tasks",
        "collection_task_sources",
        "collection_runs",
        "collection_results",
    ):
        assert f"CREATE TABLE {table}" in ddl, table


def test_status_vocabularies_enforced_by_check(ddl: str) -> None:
    assert "'active', 'paused', 'archived'" in ddl  # task status
    assert "'pending', 'running', 'succeeded', 'partial', 'failed'" in ddl  # run status
    assert "'pending', 'parsed', 'failed'" in ddl  # parse status
    assert "'materialized', 'duplicate', 'new_progress'" in ddl  # materialize status


def test_scheduling_timezone_and_dedup_claim_fields(ddl: str) -> None:
    assert "timezone          VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai'" in ddl
    assert "schedule_cron_expr VARCHAR(64)" in ddl
    assert "last_window_key   VARCHAR(64)" in ddl  # dedup scheduling claim
    assert "lease_until       TIMESTAMPTZ" in ddl
    assert "dedup_key         VARCHAR(64)" in ddl  # result dedup
    assert "claimed_at        TIMESTAMPTZ" in ddl


def test_task_and_run_are_separate_records(ddl: str) -> None:
    # A run references its task; it is not inlined into the task row.
    assert "task_id            UUID NOT NULL REFERENCES collection_tasks" in ddl
    assert "CREATE UNIQUE INDEX uq_collection_runs_task_window" in ddl


def test_deletion_preserves_traceability(ddl: str) -> None:
    # Soft deletes / FK rules keep existing runs and results resolvable.
    assert "deleted_at      TIMESTAMPTZ" in ddl  # source soft delete
    assert "status            VARCHAR(16) NOT NULL DEFAULT 'active'" in ddl  # task archive
    assert "run_id            UUID NOT NULL REFERENCES collection_runs(id) ON DELETE RESTRICT" in ddl
    assert "source_id         UUID REFERENCES collection_sources(id) ON DELETE SET NULL" in ddl


def test_paused_task_scheduling_blocked_by_trigger(ddl: str) -> None:
    assert "CREATE FUNCTION assert_collection_task_schedulable()" in ddl
    assert "t.status <> 'active'" in ddl
    assert "CREATE TRIGGER trg_collection_runs_schedulable" in ddl


def test_downgrade_drops_trigger_function_and_tables() -> None:
    mod = _load_migration()
    recorder = _RecordingOp()
    mod.op = recorder
    mod.downgrade()
    down = "\n".join(recorder.statements)
    assert "DROP TRIGGER IF EXISTS trg_collection_runs_schedulable" in down
    assert "DROP FUNCTION IF EXISTS assert_collection_task_schedulable()" in down
    for table in (
        "collection_results", "collection_runs", "collection_task_sources",
        "collection_tasks", "collection_sources",
    ):
        assert f"DROP TABLE IF EXISTS {table}" in down


# --- Constraint behaviour (needs a real test database) ---

@pytest.fixture
def schema_engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from conftest import reset_schema

    reset_schema()
    engine = create_engine(TEST_URL)
    yield engine
    engine.dispose()


def _seed(engine) -> tuple[str, str]:
    """Return (source_id, task_id) for a minimal active source + task."""
    with engine.begin() as conn:
        source_id = conn.execute(
            text(
                "INSERT INTO collection_sources (name, source_type, base_url) "
                "VALUES ('s', 'rss', 'https://example.com/feed') RETURNING id"
            )
        ).scalar_one()
        task_id = conn.execute(
            text("INSERT INTO collection_tasks (name) VALUES ('t') RETURNING id")
        ).scalar_one()
        conn.execute(
            text("INSERT INTO collection_task_sources (task_id, source_id) VALUES (:t, :s)"),
            {"t": task_id, "s": source_id},
        )
    return str(source_id), str(task_id)


def test_invalid_status_rejected(schema_engine) -> None:
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(text("INSERT INTO collection_tasks (name, status) VALUES ('t', 'bogus')"))


def test_paused_task_cannot_be_scheduled_but_can_run_manually(schema_engine) -> None:
    _, task_id = _seed(schema_engine)
    with schema_engine.begin() as conn:
        conn.execute(
            text("UPDATE collection_tasks SET status = 'paused' WHERE id = :t"), {"t": task_id}
        )
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO collection_runs (task_id, trigger) "
                    "VALUES (:t, 'scheduled')"
                ),
                {"t": task_id},
            )
    with schema_engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO collection_runs (task_id, trigger) VALUES (:t, 'manual') RETURNING id"),
            {"t": task_id},
        ).scalar_one()
    assert run_id is not None


def test_duplicate_scheduling_window_rejected(schema_engine) -> None:
    _, task_id = _seed(schema_engine)
    with schema_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO collection_runs (task_id, trigger, window_key) "
                "VALUES (:t, 'scheduled', '2026-11-18T09:00Z')"
            ),
            {"t": task_id},
        )
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO collection_runs (task_id, trigger, window_key) "
                    "VALUES (:t, 'scheduled', '2026-11-18T09:00Z')"
                ),
                {"t": task_id},
            )


def test_run_and_result_survive_task_archive_and_source_soft_delete(schema_engine) -> None:
    source_id, task_id = _seed(schema_engine)
    with schema_engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO collection_runs (task_id, trigger) VALUES (:t, 'manual') RETURNING id"),
            {"t": task_id},
        ).scalar_one()
        result_id = conn.execute(
            text(
                "INSERT INTO collection_results (run_id, source_id, title, url) "
                "VALUES (:r, :s, 'title', 'https://example.com/1') RETURNING id"
            ),
            {"r": run_id, "s": source_id},
        ).scalar_one()
        # Archive the task (soft) and soft-delete the source; both records stay.
        conn.execute(text("UPDATE collection_tasks SET status = 'archived' WHERE id = :t"), {"t": task_id})
        conn.execute(text("UPDATE collection_sources SET deleted_at = now() WHERE id = :s"), {"s": source_id})
    with schema_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT r.id, res.source_id FROM collection_runs r "
                "JOIN collection_results res ON res.run_id = r.id WHERE r.id = :r"
            ),
            {"r": run_id},
        ).one()
        assert str(row.id) == str(run_id)
        assert str(row.source_id) == source_id
