"""Integration tests for source management endpoints (task 3.4).

Use the isolated TEST_DATABASE_URL via the conftest `client` fixture. DNS is
stubbed so no real network is touched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters import source_fetch

PUBLIC = "93.184.216.34"
SOURCE = {
    "name": "行业资讯 RSS",
    "source_type": "rss",
    "base_url": "https://example.com/feed",
    "description": "测试来源",
    "enabled": True,
}


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(source_fetch, "_default_resolver", lambda host, port: [PUBLIC])


def _login(client: TestClient, account: str = "admin", password: str = "correct-password"):
    resp = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert resp.status_code == 200, resp.text


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}


def _create(client: TestClient, payload: dict | None = None, headers: dict | None = None):
    return client.post(
        "/api/v1/collection/sources",
        json=payload or SOURCE,
        headers=_csrf(client) if headers is None else headers,
    )


def test_create_list_and_get_source(client: TestClient) -> None:
    _login(client)
    created = _create(client)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == SOURCE["name"]
    assert body["status"] == "active"
    assert body["source_type"] == "rss"
    assert body["page_kind"] == "article"
    assert body["article_link_selector"] is None

    listed = client.get("/api/v1/collection/sources")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    detail = client.get(f"/api/v1/collection/sources/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["base_url"] == SOURCE["base_url"]


def test_source_list_selectors_persist_and_update(client: TestClient) -> None:
    _login(client)
    payload = {**SOURCE, "source_type": "web_page", "page_kind": "list",
               "article_link_selector": "main .article a[href]", "next_page_selector": "a.next[href]"}
    created = _create(client, payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["page_kind"] == "list"
    assert body["article_link_selector"] == payload["article_link_selector"]
    changed = client.patch(f"/api/v1/collection/sources/{body['id']}",
        json={**payload, "article_link_selector": ".news a"}, headers=_csrf(client))
    assert changed.status_code == 200
    assert changed.json()["article_link_selector"] == ".news a"


def test_create_rejects_internal_address(client: TestClient, monkeypatch) -> None:
    _login(client)
    monkeypatch.setattr(source_fetch, "_default_resolver", lambda host, port: ["127.0.0.1"])
    resp = _create(client)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "source_url_rejected"


def test_duplicate_name_conflict(client: TestClient) -> None:
    _login(client)
    assert _create(client).status_code == 201
    resp = _create(client)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_create_requires_csrf(client: TestClient) -> None:
    _login(client)
    resp = _create(client, headers={})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


def test_create_requires_write_permission(client: TestClient) -> None:
    _login(client, "editor", "editor-password")  # editor has collection:read but not write
    resp = _create(client)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


def test_idempotent_create_replay_and_conflict(client: TestClient) -> None:
    _login(client)
    headers = {**_csrf(client), "Idempotency-Key": "create-rss-1"}
    first = _create(client, headers=headers)
    assert first.status_code == 201
    replay = _create(client, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    conflict = _create(
        client,
        payload={**SOURCE, "name": "另一个来源"},
        headers={**_csrf(client), "Idempotency-Key": "create-rss-1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_update_and_soft_delete_preserves_404_after_delete(client: TestClient) -> None:
    _login(client)
    source_id = _create(client).json()["id"]

    updated = client.patch(
        f"/api/v1/collection/sources/{source_id}",
        json={**SOURCE, "name": "改名后"},
        headers=_csrf(client),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "改名后"

    deleted = client.delete(f"/api/v1/collection/sources/{source_id}", headers=_csrf(client))
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/collection/sources/{source_id}").status_code == 404


def test_connection_test_records_reachability(client: TestClient, monkeypatch) -> None:
    _login(client)
    source_id = _create(client).json()["id"]

    def ok_fetch(url, **kwargs):
        return source_fetch.FetchResult(
            final_url=url, status_code=200, content="ok",
            content_type="text/plain", elapsed_ms=12,
        )

    monkeypatch.setattr(source_fetch, "fetch", ok_fetch)
    ok = client.post(
        f"/api/v1/collection/sources/{source_id}/test", headers=_csrf(client)
    )
    assert ok.status_code == 200
    assert ok.json()["reachable"] is True
    assert ok.json()["latency_ms"] == 12
    detail = client.get(f"/api/v1/collection/sources/{source_id}").json()
    assert detail["status"] == "active"
    assert detail["last_success_at"] is not None

    def fail_fetch(url, **kwargs):
        raise source_fetch.FetchError("timeout", "连接超时")

    monkeypatch.setattr(source_fetch, "fetch", fail_fetch)
    failed = client.post(
        f"/api/v1/collection/sources/{source_id}/test", headers=_csrf(client)
    )
    assert failed.status_code == 200
    assert failed.json()["reachable"] is False
    assert failed.json()["error"] == "连接超时"
