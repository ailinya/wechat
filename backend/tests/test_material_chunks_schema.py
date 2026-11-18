"""Schema contract tests for revision-scoped material chunks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0013_material_chunks.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0013_material_chunks", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


@pytest.fixture
def ddl() -> str:
    module = _load_migration()
    recorder = _RecordingOp()
    module.op = recorder
    module.upgrade()
    return "\n".join(recorder.statements)


def test_material_chunks_use_fixed_vector_dimension_and_revision_scope(ddl: str) -> None:
    assert "CREATE EXTENSION IF NOT EXISTS vector" in ddl
    assert "material_revision_id       UUID NOT NULL REFERENCES material_revisions(id)" in ddl
    assert "embedding                  vector(1024)" in ddl
    assert "embedding_dimension        SMALLINT NOT NULL DEFAULT 1024 CHECK (embedding_dimension = 1024)" in ddl


def test_chunks_are_unique_per_revision_index_and_config_version(ddl: str) -> None:
    assert "UNIQUE (material_revision_id, chunk_index, embedding_model_config_id, embedding_config_version)" in ddl
    assert "embedding_config_version   INTEGER NOT NULL CHECK (embedding_config_version >= 1)" in ddl


def test_vector_dimension_mismatch_is_rejected_by_postgres():
    from sqlalchemy.exc import DataError, IntegrityError

    import os

    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("TEST_DATABASE_URL not set")
    from conftest import reset_schema

    from sqlalchemy import create_engine, text

    reset_schema()
    engine = create_engine(test_url)
    try:
        with engine.begin() as conn:
            model_id = conn.execute(
                text("INSERT INTO model_configs (name,provider,purpose,endpoint,model_name,enabled,max_input_tokens,max_output_tokens,timeout_seconds) "
                     "VALUES ('embedding-test','openai-compatible','embedding','https://example.invalid','test-embedding',true,8000,1000,30) RETURNING id")
            ).scalar_one()
            material_id = conn.execute(
                text("INSERT INTO materials (title) VALUES ('chunk-test') RETURNING id")
            ).scalar_one()
            revision_id = conn.execute(
                text("INSERT INTO material_revisions (material_id,revision_no,content_markdown) "
                     "VALUES (:material,1,'fixture') RETURNING id"),
                {"material": material_id},
            ).scalar_one()
            conn.execute(
                text("UPDATE materials SET current_revision_id=:revision WHERE id=:material"),
                {"revision": revision_id, "material": material_id},
            )
            with pytest.raises(DataError):
                with conn.begin_nested():
                    conn.execute(
                        text("INSERT INTO material_chunks (material_revision_id,chunk_index,content,content_hash,embedding,embedding_model_config_id,embedding_config_version,embedding_model_name) "
                             "VALUES (:revision,0,'fixture',:hash,CAST(:vector AS vector),:model,1,'test-embedding')"),
                        {"revision": revision_id, "hash": "a" * 64, "vector": "[0,0,0]", "model": model_id},
                    )
            conn.execute(
                text("INSERT INTO material_chunks (material_revision_id,chunk_index,content,content_hash,embedding_model_config_id,embedding_config_version,embedding_model_name) "
                     "VALUES (:revision,0,'fixture',:hash,:model,1,'test-embedding')"),
                {"revision": revision_id, "hash": "a" * 64, "model": model_id},
            )
            with pytest.raises(IntegrityError):
                with conn.begin_nested():
                    conn.execute(
                        text("INSERT INTO material_chunks (material_revision_id,chunk_index,content,content_hash,embedding_model_config_id,embedding_config_version,embedding_model_name) "
                             "VALUES (:revision,0,'fixture',:hash,:model,1,'test-embedding')"),
                        {"revision": revision_id, "hash": "a" * 64, "model": model_id},
                    )
            next_revision_id = conn.execute(
                text("INSERT INTO material_revisions (material_id,revision_no,content_markdown) "
                     "VALUES (:material,2,'updated fixture') RETURNING id"),
                {"material": material_id},
            ).scalar_one()
            conn.execute(
                text("UPDATE materials SET current_revision_id=:revision WHERE id=:material"),
                {"revision": next_revision_id, "material": material_id},
            )
            assert conn.execute(
                text("SELECT count(*) FROM material_chunks WHERE material_revision_id=:revision"),
                {"revision": revision_id},
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT count(*) FROM material_chunks c JOIN materials m ON m.current_revision_id=c.material_revision_id WHERE m.id=:material"),
                {"material": material_id},
            ).scalar_one() == 0
    finally:
        engine.dispose()
