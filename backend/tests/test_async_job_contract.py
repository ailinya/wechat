"""Integration tests for async job query/cancel endpoints (task 2.2)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _login(client: TestClient, account: str, password: str):
    resp = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert resp.status_code == 200
    return resp


def _insert_job(engine, owner_id, status="running") -> str:
    job_id = str(uuid.uuid4())
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO async_jobs (id, job_type, resource_type, resource_id, "
                "created_by, status, stage, progress, attempts) "
                "VALUES (:id, 'collection.fetch', 'collection_task', :rid, "
                ":owner, :status, 'fetching', 40, 1)"
            ),
            {"id": job_id, "rid": str(uuid.uuid4()), "owner": str(owner_id), "status": status},
        )
        conn.commit()
    return job_id


@pytest.fixture
def owner_id(db_engine):
    with db_engine.connect() as conn:
        owner = conn.execute(
            text("SELECT id FROM users WHERE account = 'admin'")
        ).scalar_one()
    return owner


def test_owner_can_query_running_job(client: TestClient, db_engine, owner_id) -> None:
    _login(client, "admin", "correct-password")
    job_id = _insert_job(db_engine, owner_id, status="running")
    resp = client.get(f"/api/v1/async-jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["progress"] == 40
    assert "created_by" not in body  # internal column never leaks
    assert "password" not in resp.text


def test_other_user_query_is_forbidden(client: TestClient, db_engine, owner_id) -> None:
    _login(client, "editor", "editor-password")
    job_id = _insert_job(db_engine, owner_id)
    resp = client.get(f"/api/v1/async-jobs/{job_id}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_job_list_only_returns_own_jobs(client: TestClient, db_engine, owner_id) -> None:
    _login(client, "admin", "correct-password")
    _insert_job(db_engine, owner_id)
    resp = client.get("/api/v1/async-jobs", params={"job_type": "collection.fetch"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and len(body["items"]) == 1


def test_cancel_pending_job_then_cancel_again_conflicts(client: TestClient, db_engine, owner_id) -> None:
    _login(client, "admin", "correct-password")
    csrf = client.cookies.get("wetchat_csrf")
    job_id = _insert_job(db_engine, owner_id, status="pending")

    resp = client.post(f"/api/v1/async-jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"

    resp = client.post(f"/api/v1/async-jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "job_not_cancellable"


def test_cancel_terminal_job_returns_409(client: TestClient, db_engine, owner_id) -> None:
    _login(client, "admin", "correct-password")
    csrf = client.cookies.get("wetchat_csrf")
    job_id = _insert_job(db_engine, owner_id, status="succeeded")
    resp = client.post(f"/api/v1/async-jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 409


def test_file_grant_contract_examples(client: TestClient) -> None:
    """Implemented in 2.6: grant creation validates limits and audits denials."""
    _login(client, "admin", "correct-password")
    csrf = client.cookies.get("wetchat_csrf")
    denied = client.post(
        "/api/v1/files/upload-grants",
        json={"filename": "page.html", "content_type": "text/html", "size_bytes": 100},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "unsupported_content_type"

    too_big = client.post(
        "/api/v1/files/upload-grants",
        json={"filename": "big.png", "content_type": "image/png", "size_bytes": 60 * 1024 * 1024},
        headers={"X-CSRF-Token": csrf},
    )
    # The schema bound (le=52_428_800) rejects before the service limit fires.
    assert too_big.status_code == 422
    assert too_big.json()["error"]["code"] == "validation_error"

