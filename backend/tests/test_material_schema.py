"""Schema tests for task 3.3 (material library tables & constraints).

DDL-shape tests run everywhere by capturing the migration's op.execute calls.
Constraint-behaviour tests need a real PostgreSQL (TEST_DATABASE_URL) and skip
otherwise, matching the conftest convention.
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
    / "0004_materials.py"
)
TEST_URL = os.environ.get("TEST_DATABASE_URL")


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0004_materials", MIGRATION)
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

def test_all_material_tables_created(ddl: str) -> None:
    for table in (
        "material_categories", "materials", "material_revisions", "tags",
        "material_tags", "material_files", "material_relations", "material_favorites",
    ):
        assert f"CREATE TABLE {table}" in ddl, table


def test_usage_status_and_origin_checks(ddl: str) -> None:
    assert "'pending_review', 'ready_to_use'" in ddl
    assert "'used', 'archived'," in ddl
    assert "'collection', 'upload', 'link', 'manual'" in ddl
    assert "'update_of', 'related_to'" in ddl  # relation types


def test_revision_no_unique_per_material(ddl: str) -> None:
    assert "UNIQUE (material_id, revision_no)" in ddl


def test_current_revision_belongs_to_same_material(ddl: str) -> None:
    assert "FOREIGN KEY (current_revision_id, id)" in ddl
    assert "REFERENCES material_revisions (id, material_id)" in ddl
    assert "DEFERRABLE INITIALLY DEFERRED" in ddl


def test_link_tables_deduplicated(ddl: str) -> None:
    assert "PRIMARY KEY (material_id, tag_id)" in ddl
    assert "UNIQUE (material_id, stored_object_id, role)" in ddl
    assert "UNIQUE (source_material_id, target_material_id, relation_type)" in ddl
    assert "UNIQUE (material_id, user_id)" in ddl  # favorites per user


def test_retention_safe_deletes(ddl: str) -> None:
    assert "deleted_at         TIMESTAMPTZ" in ddl  # material soft delete
    assert "material_id            UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT" in ddl  # revisions
    assert "FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL" in ddl  # collection_results
    assert "CHECK (parent_id IS NULL OR parent_id <> id)" in ddl  # no self-parent category


def test_downgrade_restores_collection_fk_and_drops_tables() -> None:
    mod = _load_migration()
    recorder = _RecordingOp()
    mod.op = recorder
    mod.downgrade()
    down = "\n".join(recorder.statements)
    assert "DROP CONSTRAINT IF EXISTS fk_collection_results_material" in down
    for table in (
        "material_favorites", "material_relations", "material_files", "material_tags",
        "tags", "material_revisions", "materials", "material_categories",
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


def _new_material(engine, title: str = "m") -> str:
    with engine.begin() as conn:
        return str(
            conn.execute(
                text("INSERT INTO materials (title) VALUES (:t) RETURNING id"), {"t": title}
            ).scalar_one()
        )


def _add_revision(engine, material_id: str, no: int = 1, body: str = "正文") -> str:
    with engine.begin() as conn:
        return str(
            conn.execute(
                text(
                    "INSERT INTO material_revisions (material_id, revision_no, content_markdown) "
                    "VALUES (:m, :n, :b) RETURNING id"
                ),
                {"m": material_id, "n": no, "b": body},
            ).scalar_one()
        )


def test_duplicate_revision_number_rejected(schema_engine) -> None:
    mid = _new_material(schema_engine)
    _add_revision(schema_engine, mid, 1)
    with pytest.raises(Exception):
        _add_revision(schema_engine, mid, 1)


def test_current_revision_must_belong_to_same_material(schema_engine) -> None:
    mid_a = _new_material(schema_engine, "a")
    mid_b = _new_material(schema_engine, "b")
    rev_b = _add_revision(schema_engine, mid_b, 1)
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(
                text("UPDATE materials SET current_revision_id = :r WHERE id = :m"),
                {"r": rev_b, "m": mid_a},
            )


def test_duplicate_tag_and_favorite_rejected(schema_engine) -> None:
    mid = _new_material(schema_engine)
    with schema_engine.begin() as conn:
        tag_id = conn.execute(
            text("INSERT INTO tags (name) VALUES ('t') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(
            text(
                "INSERT INTO users (account, name, password_hash) "
                "VALUES ('u', 'u', 'x') RETURNING id"
            )
        ).scalar_one()
    with schema_engine.begin() as conn:
        conn.execute(text("INSERT INTO material_tags (material_id, tag_id) VALUES (:m, :t)"), {"m": mid, "t": tag_id})
        conn.execute(text("INSERT INTO material_favorites (material_id, user_id) VALUES (:m, :u)"), {"m": mid, "u": user_id})
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(text("INSERT INTO material_tags (material_id, tag_id) VALUES (:m, :t)"), {"m": mid, "t": tag_id})
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(text("INSERT INTO material_favorites (material_id, user_id) VALUES (:m, :u)"), {"m": mid, "u": user_id})


def test_material_with_revisions_cannot_be_hard_deleted(schema_engine) -> None:
    mid = _new_material(schema_engine)
    rev = _add_revision(schema_engine, mid, 1)
    with pytest.raises(Exception):
        with schema_engine.begin() as conn:
            conn.execute(text("DELETE FROM materials WHERE id = :m"), {"m": mid})
    # Soft delete preserves the revision chain.
    with schema_engine.begin() as conn:
        conn.execute(text("UPDATE materials SET deleted_at = now(), usage_status = 'archived' WHERE id = :m"), {"m": mid})
    with schema_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM material_revisions WHERE id = :r AND material_id = :m"),
            {"r": rev, "m": mid},
        ).scalar_one()
        assert count == 1
