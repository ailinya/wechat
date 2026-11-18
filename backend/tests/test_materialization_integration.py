"""Integration tests for materialization (task 3.7).

Require TEST_DATABASE_URL; skip otherwise per conftest convention.
"""

from __future__ import annotations

import pytest
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters import source_fetch
from app.errors import ApiError
from app.repositories import collection_repository as repo
from app.services import materialization_service as service

HTML_A = "<html><body><h1>固件 2.1</h1><p>修复中文输入问题</p></body></html>"
HTML_B = "<html><body><h1>固件 2.2</h1><p>新增夜间模式</p></body></html>"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(source_fetch, "_default_resolver", lambda host, port: ["93.184.216.34"])


def _seed_result(session: Session, body: str, dedup_key: str = "same-source") -> str:
    conn = session.connection()
    source_id = repo.create_source(
        conn, name=f"s-{uuid4()}", source_type="rss", base_url="https://example.com/feed",
        description="", enabled=True, created_by=None,
    )["id"]
    task = repo.create_task(
        conn, name="t", keywords=[], time_range_days=7, schedule_frequency="manual",
        schedule_cron_expr=None, timezone="Asia/Shanghai", auto_materialize=False,
        auto_create=False, source_ids=[str(source_id)], created_by=None,
    )
    run = repo.create_run(conn, task_id=task["id"], trigger="manual")
    result = repo.insert_result(
        conn, run_id=run["id"], source_id=source_id, title="固件更新",
        url=f"https://example.com/{dedup_key}", raw_content=body,
        dedup_key=dedup_key, parse_status="parsed",
    )
    session.flush()
    return str(result["id"])


def test_materialize_creates_material_and_revision(db_engine) -> None:
    with Session(db_engine) as session:
        result_id = _seed_result(session, HTML_A)
        outcome = service.materialize(session.connection(), result_id, None)
        session.commit()
    assert outcome["status"] == "materialized"
    with Session(db_engine) as session:
        conn = session.connection()
        row = conn.execute(
            text("SELECT materialize_status, material_id FROM collection_results WHERE id = :id"),
            {"id": result_id},
        ).mappings().one()
        assert row["materialize_status"] == "materialized"
        revision = conn.execute(
            text("SELECT revision_no, content_markdown FROM material_revisions WHERE material_id = :id"),
            {"id": row["material_id"]},
        ).mappings().one()
        assert revision["revision_no"] == 1
        assert "修复中文输入问题" in revision["content_markdown"]


def test_duplicate_and_changed_content_without_comparison(db_engine) -> None:
    with Session(db_engine) as session:
        first = _seed_result(session, HTML_A, "feed-1")
        second = _seed_result(session, HTML_A, "feed-1")  # same source & content
        third = _seed_result(session, HTML_B, "feed-1")  # same source, new content
        conn = session.connection()
        out1 = service.materialize(session.connection(), first, None)
        session.commit()
        out2 = service.materialize(session.connection(), second, None)
        session.commit()
        out3 = service.materialize(session.connection(), third, None)
        session.commit()
    assert out1["status"] == "materialized"
    assert out2["status"] == "duplicate"
    assert out2["material_id"] == out1["material_id"]
    assert out3["status"] == "materialized"
    assert out3["material_id"] != out1["material_id"]

    with Session(db_engine) as session:
        conn = session.connection()
        relation = conn.execute(
            text("SELECT relation_type FROM material_relations WHERE source_material_id = :id"),
            {"id": out3["material_id"]},
        ).mappings().all()
        assert relation == []
        # The old revision body is untouched.
        old = conn.execute(
            text("SELECT content_markdown FROM material_revisions WHERE material_id = :id"),
            {"id": out1["material_id"]},
        ).scalar_one()
        assert "修复中文输入问题" in old


def test_exact_cross_source_duplicate_reuses_material(db_engine) -> None:
    with Session(db_engine) as session:
        first = _seed_result(session, HTML_A, "source-a")
        second = _seed_result(session, HTML_A, "source-b")
        conn = session.connection()
        first_out = service.materialize(session.connection(), first, None)
        session.commit()
        second_out = service.materialize(session.connection(), second, None)
        session.commit()
    assert second_out == {"status": "duplicate", "material_id": first_out["material_id"]}
    with Session(db_engine) as session:
        assert session.execute(text("SELECT count(*) FROM materials")).scalar_one() == 1


def test_concurrent_cross_source_import_creates_one_material(db_engine):
    with Session(db_engine) as session:
        ids = [_seed_result(session, HTML_A, f"source-{index}") for index in range(2)]
        session.commit()

    def import_result(result_id):
        with db_engine.begin() as conn:
            return service.materialize(conn, result_id, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(import_result, ids))
    assert sorted(row["status"] for row in outcomes) == ["duplicate", "materialized"]
    assert len({str(row["material_id"]) for row in outcomes}) == 1
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 1
        assert conn.execute(text(
            "SELECT count(DISTINCT source_id) FROM collection_results WHERE material_id IS NOT NULL"
        )).scalar_one() == 2


def test_unpersisted_progress_decision_is_rejected(db_engine) -> None:
    with Session(db_engine) as session:
        old_result = _seed_result(session, HTML_A, "old")
        new_result = _seed_result(session, HTML_B, "new")
        conn = session.connection()
        old = service.materialize(session.connection(), old_result, None)
        session.commit()
        with pytest.raises(ApiError) as exc:
            service.materialize(session.connection(), new_result, None, progress_decision={
                "verdict": "new_progress", "target_material_id": old["material_id"], "evidence": ["新增夜间模式"]
            })
        assert exc.value.code == "invalid_progress_evidence"


def test_repeated_materialize_is_idempotent(db_engine) -> None:
    with Session(db_engine) as session:
        result_id = _seed_result(session, HTML_A)
        conn = session.connection()
        first = service.materialize(session.connection(), result_id, None)
        session.commit()
        again = service.materialize(session.connection(), result_id, None)
        session.commit()
    assert first == again
    with Session(db_engine) as session:
        count = session.execute(
            text("SELECT count(*) FROM materials")
        ).scalar_one()
        assert count == 1


def test_ignore_and_retry_parse(db_engine) -> None:
    with Session(db_engine) as session:
        conn = session.connection()
        result_id = _seed_result(session, HTML_A)
        service.ignore(session.connection(), result_id)
        session.commit()
        status = session.connection().execute(
            text("SELECT materialize_status FROM collection_results WHERE id = :id"),
            {"id": result_id},
        ).scalar_one()
        assert status == "ignored"
        with pytest.raises(ApiError) as exc:
            service.materialize(session.connection(), result_id, None)
        assert exc.value.code == "result_ignored"


def test_materialize_route_returns_202(client: TestClient) -> None:
    assert client.post(
        "/api/v1/auth/login", json={"account": "admin", "password": "correct-password"}
    ).status_code == 200
    csrf = {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}
    created = client.post(
        "/api/v1/collection/sources",
        json={"name": "s", "source_type": "rss", "base_url": "https://example.com/feed",
              "description": "", "enabled": True},
        headers=csrf,
    )
    assert created.status_code == 201
    source_id = created.json()["id"]
    task = client.post(
        "/api/v1/collection/tasks",
        json={"name": "t", "keywords": [], "source_ids": [source_id],
              "schedule": {"frequency": "manual", "cron_expr": None, "timezone": "Asia/Shanghai"},
              "time_range_days": 7, "auto_materialize": False, "auto_create": False},
        headers=csrf,
    )
    assert task.status_code == 201
    resp = client.post(f"/api/v1/collection/tasks/{task.json()['id']}/run", headers=csrf)
    assert resp.status_code == 202
    results = client.get("/api/v1/collection/results").json()
    if results["items"]:
        result_id = results["items"][0]["id"]
        materialize = client.post(f"/api/v1/collection/results/{result_id}/materialize", headers=csrf)
        assert materialize.status_code == 202
        assert materialize.json()["resource_type"] == "collection_result"
