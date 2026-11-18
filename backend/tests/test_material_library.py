"""Integration tests for the material library endpoints (task 3.8).

Require TEST_DATABASE_URL; skip otherwise.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters import source_fetch


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(source_fetch, "_default_resolver", lambda host, port: ["93.184.216.34"])


def _login(client: TestClient, account: str, password: str) -> None:
    assert client.post(
        "/api/v1/auth/login", json={"account": account, "password": password}
    ).status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}


def _create_material(client: TestClient, title: str = "测试素材") -> str:
    resp = client.post(
        "/api/v1/materials",
        json={"title": title, "content_markdown": "中文正文第一段", "category_id": None, "tag_ids": []},
        headers=_csrf(client),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_create_detail_and_revision(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    material_id = _create_material(client)
    detail = client.get(f"/api/v1/materials/{material_id}").json()
    assert detail["origin"] == "manual"
    assert detail["current_revision"]["revision_no"] == 1
    assert detail["current_revision"]["content_markdown"] == "中文正文第一段"

    updated = client.patch(
        f"/api/v1/materials/{material_id}",
        json={"content_markdown": "中文正文第二段"},
        headers=_csrf(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_revision"]["revision_no"] == 2
    revisions = client.get(f"/api/v1/materials/{material_id}/revisions").json()
    assert [r["revision_no"] for r in revisions] == [1, 2]
    assert revisions[0]["content_markdown"] == "中文正文第一段"


def test_categories_cycle_rejected(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    a = client.post("/api/v1/materials/categories", json={"name": "A", "parent_id": None}, headers=_csrf(client)).json()["id"]
    b = client.post("/api/v1/materials/categories", json={"name": "B", "parent_id": a}, headers=_csrf(client)).json()["id"]
    resp = client.patch(
        f"/api/v1/materials/categories/{a}", json={"name": "A", "parent_id": b}, headers=_csrf(client)
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "category_cycle"


def test_favorites_are_user_isolated(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    material_id = _create_material(client)
    assert client.put(f"/api/v1/materials/{material_id}/favorite", headers=_csrf(client)).status_code == 201
    assert client.get("/api/v1/materials/favorites").json()["total"] == 1

    # Switch to editor: should not see admin's favorite.
    client.cookies.clear()
    _login(client, "editor", "editor-password")
    assert client.get("/api/v1/materials/favorites").json()["total"] == 0
    assert client.get(f"/api/v1/materials/{material_id}").json()["favorited_by_me"] is False


def test_archive_and_soft_delete(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    material_id = _create_material(client)
    archived = client.post(
        "/api/v1/materials/bulk",
        json={"material_ids": [material_id], "action": "archive", "category_id": None, "tag_ids": []},
        headers=_csrf(client),
    )
    assert archived.status_code == 200
    assert archived.json()["counts"]["success"] == 1
    assert client.get(f"/api/v1/materials/{material_id}").json()["usage_status"] == "archived"

    deleted = client.delete(f"/api/v1/materials/{material_id}", headers=_csrf(client))
    assert deleted.status_code == 200
    assert deleted.json()["references_preserved"] is True
    assert client.get(f"/api/v1/materials/{material_id}").status_code == 404
