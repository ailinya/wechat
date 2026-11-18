"""Integration tests for collection task CRUD/run/scheduling (task 3.5).

Require TEST_DATABASE_URL; the conftest fixtures skip when it is unset.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters import source_fetch
from app.modules.collection import schedule
from app.repositories import collection_repository as repo
from app.services import collection_service

PUBLIC = "93.184.216.34"
SOURCE = {
    "name": "RSS 来源",
    "source_type": "rss",
    "base_url": "https://example.com/feed",
    "description": "",
    "enabled": True,
}
TASK = {
    "name": "每日采集",
    "keywords": ["AI", "固件"],
    "source_ids": [],  # filled per test
    "schedule": {"frequency": "daily", "cron_expr": None, "timezone": "Asia/Shanghai"},
    "time_range_days": 7,
    "auto_materialize": False,
    "auto_create": False,
}


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(source_fetch, "_default_resolver", lambda host, port: [PUBLIC])


def _login(client: TestClient) -> None:
    assert client.post(
        "/api/v1/auth/login", json={"account": "admin", "password": "correct-password"}
    ).status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}


def _source_id(client: TestClient) -> str:
    resp = client.post("/api/v1/collection/sources", json=SOURCE, headers=_csrf(client))
    if resp.status_code==409:
        return client.get('/api/v1/collection/sources').json()['items'][0]['id']
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _task(client: TestClient, name: str = "每日采集", frequency: str = "daily") -> str:
    payload = {
        **TASK,
        "name": name,
        "source_ids": [_source_id(client)],
        "schedule": {"frequency": frequency, "cron_expr": None, "timezone": "Asia/Shanghai"},
    }
    resp = client.post("/api/v1/collection/tasks", json=payload, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_task_crud_and_archive(client: TestClient) -> None:
    _login(client)
    task_id = _task(client)
    listed = client.get("/api/v1/collection/tasks")
    assert listed.status_code == 200 and listed.json()["total"] >= 1
    detail = client.get(f"/api/v1/collection/tasks/{task_id}").json()
    assert detail["name"] == "每日采集"
    assert detail["schedule"]["frequency"] == "daily"
    assert len(detail["sources"]) == 1

    updated = client.patch(
        f"/api/v1/collection/tasks/{task_id}",
        json={**TASK, "name": "改名", "source_ids": [detail["sources"][0]["id"]]},
        headers=_csrf(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "改名"

    deleted = client.delete(f"/api/v1/collection/tasks/{task_id}", headers=_csrf(client))
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "archived"
    assert client.get(f"/api/v1/collection/tasks/{task_id}").json()["status"] == "archived"


def test_pause_blocks_immediate_run(client: TestClient) -> None:
    _login(client)
    task_id = _task(client)
    paused = client.post(f"/api/v1/collection/tasks/{task_id}/pause", headers=_csrf(client))
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    resp = client.post(f"/api/v1/collection/tasks/{task_id}/run", headers=_csrf(client))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "task_not_active"
    resumed = client.post(f"/api/v1/collection/tasks/{task_id}/resume", headers=_csrf(client))
    assert resumed.json()["status"] == "active"


def test_run_now_creates_run_job_and_outbox(client: TestClient, db_engine) -> None:
    _login(client)
    task_id = _task(client)
    resp = client.post(f"/api/v1/collection/tasks/{task_id}/run", headers=_csrf(client))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["resource_type"] == "collection_run"

    with Session(db_engine) as session:
        conn = session.connection()
        run = conn.execute(
            text("SELECT * FROM collection_runs WHERE id = :id"), {"id": body["resource_id"]}
        ).mappings().one()
        assert str(run["task_id"]) == task_id
        assert run["trigger"] == "manual"
        assert run["window_key"] is None
        job = conn.execute(
            text("SELECT * FROM async_jobs WHERE id = :id"), {"id": body["async_job_id"]}
        ).mappings().one()
        assert job["job_type"] == "collection.run"
        assert str(job["resource_id"]) == body["resource_id"]
        outbox = conn.execute(
            text("SELECT * FROM outbox_events WHERE aggregate_id = :id"),
            {"id": body["resource_id"]},
        ).mappings().all()
        assert len(outbox) == 1


def test_idempotent_run_now_replay_and_conflict(client: TestClient) -> None:
    _login(client)
    task_id = _task(client)
    headers = {**_csrf(client), "Idempotency-Key": "run-once"}
    first = client.post(f"/api/v1/collection/tasks/{task_id}/run", headers=headers)
    assert first.status_code == 202
    replay = client.post(f"/api/v1/collection/tasks/{task_id}/run", headers=headers)
    assert replay.json()["async_job_id"] == first.json()["async_job_id"]

    other_task = _task(client, name="另一个任务")
    conflict = client.post(
        f"/api/v1/collection/tasks/{other_task}/run", headers=headers
    )
    assert conflict.status_code == 409  # same key, different content
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_scheduled_dedup_and_pause_blocks_new_run(db_engine) -> None:
    now = datetime(2026, 11, 18, 1, 30, tzinfo=timezone.utc)
    with Session(db_engine) as session:
        conn = session.connection()
        source_id = repo.create_source(
            conn, name="s", source_type="rss", base_url="https://example.com/feed",
            description="", enabled=True, created_by=None,
        )["id"]
        task = repo.create_task(
            conn, name="daily", keywords=[], time_range_days=7,
            schedule_frequency="daily", schedule_cron_expr=None, timezone="Asia/Shanghai",
            auto_materialize=False, auto_create=False, source_ids=[str(source_id)], created_by=None,
        )
        session.commit()

        first = collection_service.schedule_due_runs(session.connection(), now=now)
        session.commit()
        assert len(first["created"]) == 1
        second = collection_service.schedule_due_runs(session.connection(), now=now)
        session.commit()
        assert second["created"] == []  # same window not duplicated

        collection_service.set_status(session.connection(), task["id"], "paused")
        session.commit()
        later = collection_service.schedule_due_runs(
            session.connection(), now=datetime(2026, 11, 19, 1, 30, tzinfo=timezone.utc)
        )
        session.commit()
        assert later["created"] == []  # paused task produces no new run
