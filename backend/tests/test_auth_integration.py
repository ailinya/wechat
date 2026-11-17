"""Authentication integration tests against an isolated test database.

Set TEST_DATABASE_URL to a PostgreSQL URL dedicated to tests. When it is not
set these tests skip, so the default suite never connects to a database.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.main import create_app
from app.modules.auth.security import hash_password
from app.repositories import auth_repository as repo

TEST_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="TEST_DATABASE_URL not set"
)


def _reset_schema() -> None:
    engine = create_engine(TEST_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS sessions, role_permissions, user_roles, "
                "users, permissions, roles, alembic_version CASCADE"
            )
        )
        conn.commit()
    engine.dispose()

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_URL
    try:
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _seed(conn) -> tuple[UUID, UUID]:
    repo.ensure_permissions_seeded(conn)
    now = datetime.now(timezone.utc)
    admin_role = repo.role_id_by_name(conn, "admin")
    editor_role = repo.role_id_by_name(conn, "editor")

    admin_id = conn.execute(
        text(
            "INSERT INTO users (account, name, status, password_hash, created_at, updated_at) "
            "VALUES ('admin', '管理员', 'active', :pw, :now, :now) RETURNING id"
        ),
        {"pw": hash_password("correct-password"), "now": now},
    ).scalar_one()
    editor_id = conn.execute(
        text(
            "INSERT INTO users (account, name, status, password_hash, created_at, updated_at) "
            "VALUES ('editor', '编辑', 'active', :pw, :now, :now) RETURNING id"
        ),
        {"pw": hash_password("editor-password"), "now": now},
    ).scalar_one()
    conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": admin_id, "r": admin_role},
    )
    conn.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
        {"u": editor_id, "r": editor_role},
    )
    return admin_id, editor_id


@pytest.fixture
def client():
    _reset_schema()
    engine = create_engine(TEST_URL)
    with Session(engine) as session:
        with session.begin():
            _seed(session.connection())
    session.close()

    def override_get_db():
        with Session(engine) as s:
            yield s

    settings = Settings.model_validate(
        {"APP_SECRET_KEY": "t" * 40, "DATABASE_URL": TEST_URL}
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    engine.dispose()


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


def test_disabled_user_rejected(client: TestClient) -> None:
    engine = create_engine(TEST_URL)
    with engine.connect() as conn:
        conn.execute(text("UPDATE users SET status='disabled' WHERE account='admin'"))
        conn.commit()
    engine.dispose()
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


def test_expired_session_rejected(client: TestClient) -> None:
    assert _login(client, "admin", "correct-password").status_code == 200
    engine = create_engine(TEST_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE sessions SET expires_at = :past WHERE token_hash = "
                "(SELECT token_hash FROM sessions ORDER BY created_at DESC LIMIT 1)"
            ),
            {"past": datetime.now(timezone.utc) - timedelta(minutes=1)},
        )
        conn.commit()
    engine.dispose()
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
