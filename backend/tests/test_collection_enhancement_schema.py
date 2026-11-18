"""Schema tests for task 3.15 (collection enhancement migration).

DDL-shape tests run everywhere by capturing op.execute calls. Constraint and
backfill behaviour tests require TEST_DATABASE_URL and skip otherwise.
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
    / "0005_collection_enhancement.py"
)
TEST_URL = os.environ.get("TEST_DATABASE_URL")


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0005_enhancement", MIGRATION)
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


def test_new_tables_created(ddl: str) -> None:
    for table in (
        "model_configs", "search_configs", "collection_candidates",
        "collection_stage_attempts", "collection_snapshots",
        "collection_analyses", "material_ready_events",
    ):
        assert f"CREATE TABLE {table}" in ddl, table


def test_backfill_defaults_for_existing_tables(ddl: str) -> None:
    assert "page_kind VARCHAR(16) NOT NULL DEFAULT 'article'" in ddl
    assert "mode VARCHAR(16) NOT NULL DEFAULT 'source'" in ddl
    assert "analysis_enabled BOOLEAN NOT NULL DEFAULT FALSE" in ddl
    assert "analysis_apply_policy VARCHAR(16) NOT NULL DEFAULT 'suggest_only'" in ddl


def test_0003_and_0004_are_untouched(ddl: str) -> None:
    # Only additive ALTER TABLE, no CREATE of the original phase-3 tables.
    assert "CREATE TABLE collection_sources" not in ddl
    assert "CREATE TABLE collection_tasks" not in ddl
    assert "CREATE TABLE materials" not in ddl


def test_mode_and_status_checks(ddl: str) -> None:
    assert "mode IN ('source', 'topic_search')" in ddl
    assert "purpose IN ('analysis', 'generation', 'embedding')" in ddl
    assert "stage IN ('discover', 'fetch', 'parse', 'analyze', 'materialize')" in ddl
    assert "end_reason IN ('completed', 'cancelled', 'budget_exhausted', 'error')" in ddl


def test_ready_event_unique_key_and_candidate_dedup(ddl: str) -> None:
    assert "event_key             VARCHAR(64) NOT NULL UNIQUE" in ddl
    assert "UNIQUE (run_id, normalized_url)" in ddl


def test_material_metadata_version_and_manual_fields(ddl: str) -> None:
    assert "metadata_version INTEGER NOT NULL DEFAULT 1" in ddl
    assert "manual_fields JSONB NOT NULL DEFAULT '[]'::jsonb" in ddl


def test_downgrade_drops_new_objects() -> None:
    mod = _load_migration()
    recorder = _RecordingOp()
    mod.op = recorder
    mod.downgrade()
    down = "\n".join(recorder.statements)
    for table in (
        "material_ready_events", "collection_analyses", "collection_snapshots",
        "collection_stage_attempts", "collection_candidates", "search_configs",
        "model_configs",
    ):
        assert f"DROP TABLE IF EXISTS {table}" in down
    assert "DROP COLUMN IF EXISTS mode" in down
    assert "DROP COLUMN IF EXISTS page_kind" in down
    assert "DROP COLUMN IF EXISTS metadata_version" in down


# --- DB behaviour (needs a real database) ---

@pytest.fixture
def schema_engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from conftest import reset_schema

    reset_schema()
    engine = create_engine(TEST_URL)
    yield engine
    engine.dispose()


def test_existing_rows_backfilled_on_upgrade(db_engine) -> None:
    with db_engine.begin() as conn:
        source_id = conn.execute(
            text("INSERT INTO collection_sources (name, source_type, base_url) VALUES ('s','rss','https://e.com') RETURNING id")
        ).scalar_one()
        task_id = conn.execute(
            text("INSERT INTO collection_tasks (name) VALUES ('t') RETURNING id")
        ).scalar_one()
    with db_engine.connect() as conn:
        source = conn.execute(
            text("SELECT page_kind FROM collection_sources WHERE id = :id"), {"id": source_id}
        ).scalar_one()
        assert source == "article"
        task = conn.execute(
            text("SELECT mode, analysis_enabled, analysis_apply_policy FROM collection_tasks WHERE id = :id"),
            {"id": task_id},
        ).one()
        assert task.mode == "source"
        assert task.analysis_enabled is False
        assert task.analysis_apply_policy == "suggest_only"


def test_mode_check_rejects_invalid(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO collection_tasks(name) VALUES ('constraint-test')"))
    with pytest.raises(Exception):
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE collection_tasks SET mode = 'bogus'"))
