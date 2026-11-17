"""Authentication integration tests against an isolated test database.

The `client` and `db_engine` fixtures live in conftest.py: they replay
migrations on TEST_DATABASE_URL and skip when it is unset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


def _login(client: TestClient, account: str, password: str):
    return client.post(
        "/api/v1/auth/login", json={"account": account, "password": password}
    )


def test_correct_password_login_and_me(client: TestClient) -> None:
    resp = _login(client, "admin", "correct-password")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["account"] == "admin"
    assert "user:read" in body["user"]["permissions"]
    assert "password" not in body
    assert "password_hash" not in body
    assert client.cookies.get("wetchat_session")
    assert client.cookies.get("wetchat_csrf")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["account"] == "admin"


def test_wrong_password_rejected(client: TestClient) -> None:
    resp = _login(client, "admin", "wrong-password")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert "password" not in resp.text


def test_unknown_account_rejected(client: TestClient) -> None:
    resp = _login(client, "nobody", "whatever-password")
    assert resp.status_code == 401


def test_disabled_user_rejected(client: TestClient, db_engine) -> None:
    with db_engine.connect() as conn:
        conn.execute(text("UPDATE users SET status='disabled' WHERE account='admin'"))
        conn.commit()
    resp = _login(client, "admin", "correct-password")
    assert resp.status_code == 401


def test_logout_revokes_session(client: TestClient) -> None:
    assert _login(client, "admin", "correct-password").status_code == 200
    me_before = client.get("/api/v1/auth/me")
    assert me_before.status_code == 200

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    me_after = client.get("/api/v1/auth/me")
    assert me_after.status_code == 401


def test_expired_session_rejected(client: TestClient, db_engine) -> None:
    assert _login(client, "admin", "correct-password").status_code == 200
    with db_engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET expires_at = :past WHERE token_hash = "
                "(SELECT token_hash FROM sessions ORDER BY created_at DESC LIMIT 1)"
            ),
            {"past": datetime.now(timezone.utc) - timedelta(minutes=1)},
        )
        conn.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_editor_cannot_create_user_returns_403(client: TestClient) -> None:
    assert _login(client, "editor", "editor-password").status_code == 200
    csrf = client.cookies.get("wetchat_csrf")
    resp = client.post(
        "/api/v1/users",
        json={
            "account": "newuser",
            "name": "新用户",
            "password": "a-strong-password",
            "role_ids": [],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_csrf_required_for_write(client: TestClient) -> None:
    assert _login(client, "admin", "correct-password").status_code == 200
    csrf = client.cookies.get("wetchat_csrf")
    client.cookies.set("wetchat_csrf", "")
    resp = client.post(
        "/api/v1/users",
        json={
            "account": "newuser",
            "name": "新用户",
            "password": "a-strong-password",
            "role_ids": [],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


def test_admin_can_create_user_with_valid_csrf(client: TestClient) -> None:
    assert _login(client, "admin", "correct-password").status_code == 200
    csrf = client.cookies.get("wetchat_csrf")
    resp = client.post(
        "/api/v1/users",
        json={
            "account": "newuser",
            "name": "新用户",
            "password": "a-strong-password",
            "role_ids": [],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["account"] == "newuser"
    assert "password" not in resp.json()
