"""Integration tests for model config endpoints (task 3.16). Skip without DB."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient) -> None:
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"account": "admin", "password": "correct-password"},
        ).status_code
        == 200
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}


def test_create_and_list_never_echo_credential(client: TestClient) -> None:
    _login(client)
    created = client.post(
        "/api/v1/model-configs",
        json={
            "name": "analysis 模型",
            "provider": "openai-compatible",
            "purpose": "analysis",
            "endpoint": "https://example.com/v1",
            "model_name": "gpt-4o-mini",
            "credential_ref": "SECRET_ENV_NAME",
            "enabled": True,
        },
        headers=_csrf(client),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["credential_configured"] is True
    assert "credential_ref" not in body  # secret reference never serialised

    listed = client.get("/api/v1/model-configs")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    updated = client.patch(
        f"/api/v1/model-configs/{body['id']}",
        json={"enabled": False},
        headers=_csrf(client),
    )
    assert updated.status_code == 200, updated.text
    assert (
        updated.json()["config_version"] == 2
        and updated.json()["credential_configured"]
    )
    assert "SECRET_ENV_NAME" not in updated.text
    assert client.get(f"/api/v1/model-configs/{body['id']}").status_code == 200


def test_create_requires_settings_permission(client: TestClient) -> None:
    # editor lacks settings:write
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"account": "editor", "password": "editor-password"},
        ).status_code
        == 200
    )
    resp = client.post(
        "/api/v1/model-configs",
        json={
            "name": "x",
            "provider": "openai-compatible",
            "purpose": "analysis",
            "endpoint": "https://example.com/v1",
            "model_name": "m",
        },
        headers=_csrf(client),
    )
    assert resp.status_code == 403
