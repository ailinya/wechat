from __future__ import annotations

import json
import os

import pytest

from app.adapters import embedding_client
from app.services.material_embedding_service import chunk_text


def test_chunking_is_deterministic_and_overlaps_windows():
    content = "甲" * 2500
    first = chunk_text(content)
    second = chunk_text(content)

    assert first == second
    assert [row["chunk_index"] for row in first] == [0, 1, 2]
    assert first[0]["content"][-100:] == first[1]["content"][:100]
    assert first[0]["content_hash"] == first[1]["content_hash"]


def test_chunking_empty_text_returns_no_chunks():
    assert chunk_text(" \r\n\t ") == []


def test_embedding_client_uses_env_contract_and_checks_dimensions(monkeypatch):
    dimension = 1024
    monkeypatch.setattr(embedding_client, "resolve_setting", lambda name: {
        "EMBEDDING_MODEL": "qwen3.7-text-embedding-flash",
        "EMBEDDING_BASE_URL": "https://embedding.example/api/v1/",
        "EMBEDDING_DIMENSION": "1024",
        "EMBEDDING_BATCH_SIZE": "10",
    }.get(name))
    monkeypatch.setattr(embedding_client, "resolve_credential", lambda _name: "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "output": {"embeddings": [{"embedding": [0.25] * dimension}]},
                "usage": {"total_tokens": 4},
            }).encode()

    captured = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(embedding_client.urllib.request, "urlopen", open_request)
    vectors, usage = embedding_client.embed_texts(
        ["中文样例"],
        expected_model="qwen3.7-text-embedding-flash",
        expected_base_url="https://embedding.example/api/v1",
    )

    assert captured["url"] == (
        "https://embedding.example/api/v1/services/embeddings/"
        "text-embedding/text-embedding"
    )
    assert captured["payload"]["input"] == {"texts": ["中文样例"]}
    assert captured["payload"]["parameters"]["dimension"] == dimension
    assert captured["timeout"] == 60
    assert len(vectors[0]) == dimension
    assert usage["total_tokens"] == 4


def test_embedding_client_rejects_changed_env_snapshot(monkeypatch):
    monkeypatch.setattr(embedding_client, "resolve_setting", lambda name: {
        "EMBEDDING_MODEL": "new-model",
        "EMBEDDING_BASE_URL": "https://embedding.example/api/v1",
        "EMBEDDING_DIMENSION": "1024",
        "EMBEDDING_BATCH_SIZE": "10",
    }.get(name))
    monkeypatch.setattr(embedding_client, "resolve_credential", lambda _name: "test-key")

    with pytest.raises(embedding_client.EmbeddingError) as error:
        embedding_client.embed_texts(
            ["中文样例"],
            expected_model="old-model",
            expected_base_url="https://embedding.example/api/v1",
        )

    assert error.value.code == "embedding_configuration_changed"


def test_embedding_build_retry_and_new_revision(monkeypatch):
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from sqlalchemy import create_engine, text
    from conftest import reset_schema
    from app.services import async_job_service, material_embedding_service as service

    reset_schema()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    calls = []

    def send(texts, **_kwargs):
        calls.append(list(texts))
        if len(calls) == 1:
            raise embedding_client.EmbeddingError("embedding_http_503", "unavailable")
        return [[0.1] * 1024 for _ in texts], {}

    monkeypatch.setattr(embedding_client, "embed_texts", send)
    try:
        with engine.begin() as conn:
            material = conn.execute(text("INSERT INTO materials(title) VALUES ('fixture') RETURNING id")).scalar_one()
            first_revision = conn.execute(
                text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'first revision') RETURNING id"),
                {"id": material},
            ).scalar_one()
            conn.execute(text("UPDATE materials SET current_revision_id=:revision WHERE id=:id"), {"revision": first_revision, "id": material})
            accepted = service.enqueue_rebuild(conn, material)
            duplicate = service.enqueue_rebuild(conn, material)
            assert duplicate["async_job_id"] == accepted["async_job_id"]
            assert async_job_service.claim_job(conn, accepted["async_job_id"])
            job = async_job_service.get_job(conn, accepted["async_job_id"])
        with pytest.raises(RuntimeError, match="embedding_http_503"):
            service.material_embedding_job(engine, job)
        with engine.begin() as conn:
            assert conn.execute(text("SELECT error_code FROM material_embedding_runs")).scalar_one() == "embedding_http_503"
            async_job_service.finish_job(conn, accepted["async_job_id"], "failed")
            retry = service.enqueue_rebuild(conn, material)
            assert retry["async_job_id"] != accepted["async_job_id"]
            assert async_job_service.claim_job(conn, retry["async_job_id"])
            retry_job = async_job_service.get_job(conn, retry["async_job_id"])
        service.material_embedding_job(engine, retry_job)
        with engine.begin() as conn:
            async_job_service.finish_job(conn, retry["async_job_id"], "succeeded")
            assert conn.execute(text("SELECT count(*) FROM material_chunks WHERE embedding IS NOT NULL")).scalar_one() == 1
            assert service.enqueue_rebuild(conn, material)["async_job_id"] == retry["async_job_id"]
            second_revision = conn.execute(
                text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,2,'updated revision') RETURNING id"),
                {"id": material},
            ).scalar_one()
            conn.execute(text("UPDATE materials SET current_revision_id=:revision WHERE id=:id"), {"revision": second_revision, "id": material})
            new_build = service.enqueue_rebuild(conn, material)
            assert new_build["revision_id"] == str(second_revision)
            assert conn.execute(text("SELECT count(*) FROM material_chunks c JOIN materials m ON m.current_revision_id=c.material_revision_id WHERE m.id=:id"), {"id": material}).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM material_chunks WHERE material_revision_id=:id AND embedding IS NOT NULL"), {"id": first_revision}).scalar_one() == 1
            assert async_job_service.claim_job(conn, new_build["async_job_id"])
            new_job = async_job_service.get_job(conn, new_build["async_job_id"])
        service.material_embedding_job(engine, new_job)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM material_chunks WHERE material_revision_id=:id AND embedding IS NOT NULL"), {"id": second_revision}).scalar_one() == 1
    finally:
        engine.dispose()
