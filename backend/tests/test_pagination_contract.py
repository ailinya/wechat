"""Pagination contract tests: stable ordering, page bounds, filters (task 1.9)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.main import create_app

TEST_URL = os.environ.get("TEST_DATABASE_URL")


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"account": "admin", "password": "correct-password"}
    )
    assert resp.status_code == 200


@pytest.fixture
def many_users(db_engine) -> None:
    """Insert 35 extra users so list pages exceed one default page."""
    with db_engine.connect() as conn:
        for index in range(35):
            conn.execute(
                text(
                    "INSERT INTO users (account, name, status, password_hash, created_at, updated_at) "
                    "VALUES (:account, :name, 'active', :pw, NOW(), NOW())"
                ),
                {
                    "account": f"user{index:03d}",
                    "name": f"用户{index:03d}",
                    "pw": "x" * 64,
                },
            )
        conn.commit()


def test_users_list_requires_permission(client: TestClient) -> None:
    _login(client)
    resp = client.get("/api/v1/users")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "total", "page", "page_size"}


def test_pagination_is_stable_across_pages(client: TestClient, many_users) -> None:
    _login(client)
    page_one = client.get("/api/v1/users", params={"page": 1, "page_size": 10}).json()
    page_two = client.get("/api/v1/users", params={"page": 2, "page_size": 10}).json()

    assert page_one["total"] == 37  # 35 seeded + admin + editor
    assert page_one["page"] == 1 and page_two["page"] == 2
    accounts_one = [item["account"] for item in page_one["items"]]
    accounts_two = [item["account"] for item in page_two["items"]]
    assert len(accounts_one) == len(accounts_two) == 10
    assert not set(accounts_one) & set(accounts_two)

    # Same request twice keeps the same order (stable sort contract).
    repeat = client.get("/api/v1/users", params={"page": 1, "page_size": 10}).json()
    assert [item["account"] for item in repeat["items"]] == accounts_one


def test_page_size_bounds_and_filters(client: TestClient, many_users) -> None:
    _login(client)

    resp = client.get("/api/v1/users", params={"page": 0})
    assert resp.status_code == 422
    resp = client.get("/api/v1/users", params={"page_size": 101})
    assert resp.status_code == 422

    filtered = client.get(
        "/api/v1/users", params={"keyword": "user001", "page_size": 5}
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["account"] == "user001"

    status_filtered = client.get("/api/v1/users", params={"status": "disabled"}).json()
    assert status_filtered["total"] == 0
    assert status_filtered["items"] == []


def test_users_list_forbidden_without_permission(db_engine) -> None:
    """Editor has no user:read -> 403 on the paginated endpoint."""
    def override_get_db():
        with Session(db_engine) as s:
            yield s

    settings = Settings.model_validate(
        {"APP_SECRET_KEY": "t" * 40, "DATABASE_URL": TEST_URL}
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"account": "editor", "password": "editor-password"},
            ).status_code
            == 200
        )
        resp = client.get("/api/v1/users")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "forbidden"
