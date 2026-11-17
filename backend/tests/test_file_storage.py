"""File storage integration tests against real RustFS (task 2.6).

Skipped unless RUSTFS_ENDPOINT + credentials are available; a repo-root .env
is loaded automatically for local runs so tests use the same values as docker
compose. Tests only talk to the isolated test database and the local RustFS.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.database import get_db
from app.main import create_app
from sqlalchemy.orm import Session

TEST_URL = os.environ.get("TEST_DATABASE_URL")

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_root_env() -> dict:
    env_file = REPO_ROOT / ".env"
    values = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values.setdefault(key.strip(), value.strip())
    return values


_ENV = {**_load_root_env(), **os.environ}
if "RUSTFS_ENDPOINT" not in _ENV and _ENV.get("RUSTFS_API_PORT"):
    _ENV["RUSTFS_ENDPOINT"] = f"http://127.0.0.1:{_ENV['RUSTFS_API_PORT']}"


def _settings(**extra) -> Settings:
    payload = {
        "APP_SECRET_KEY": "t" * 40,
        "DATABASE_URL": TEST_URL,
        "RUSTFS_ENDPOINT": _ENV.get("RUSTFS_ENDPOINT"),
        "RUSTFS_ACCESS_KEY": _ENV.get("RUSTFS_ACCESS_KEY"),
        "RUSTFS_SECRET_KEY": _ENV.get("RUSTFS_SECRET_KEY"),
    }
    payload = {k: v for k, v in payload.items() if v}
    payload.update(extra)
    return Settings.model_validate(payload)


pytestmark = pytest.mark.skipif(
    not (TEST_URL and _ENV.get("RUSTFS_ENDPOINT") and _ENV.get("RUSTFS_ACCESS_KEY")),
    reason="TEST_DATABASE_URL / RustFS settings not available",
)


@pytest.fixture
def storage_settings() -> Settings:
    return _settings()


@pytest.fixture
def client(db_engine, storage_settings) -> TestClient:
    def override_get_db():
        with Session(db_engine) as s:
            yield s

    app = create_app(storage_settings)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, account: str, password: str):
    resp = client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert resp.status_code == 200


def _csrf(client: TestClient) -> str:
    return client.cookies.get("wetchat_csrf")


def _create_grant(client: TestClient, idempotency_key: str | None = None, **payload):
    headers = {"X-CSRF-Token": _csrf(client)}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return client.post("/api/v1/files/upload-grants", json=payload, headers=headers)


def test_grant_upload_complete_download_roundtrip(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    resp = _create_grant(
        client, filename="phase02.txt", content_type="text/plain", size_bytes=len(b"hello rustfs")
    )
    assert resp.status_code == 201, resp.text
    grant = resp.json()
    assert grant["upload_url"] and grant["object_key"].endswith("phase02.txt")

    content = b"hello rustfs"
    put = httpx.put(grant["upload_url"], content=content)
    assert put.status_code in (200, 201), put.text

    done = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": hashlib.sha256(content).hexdigest()},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert done.status_code == 200, done.text
    stored = done.json()
    assert stored["object_key"] == grant["object_key"]
    assert stored["size_bytes"] == len(content)

    # Repeated completion replays the same object (lost-response recovery).
    again = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": hashlib.sha256(content).hexdigest()},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert again.status_code == 200
    assert again.json()["id"] == stored["id"]

    # Uploader can download via a short-term URL.
    dl = client.post(
        f"/api/v1/files/{stored['id']}/download-grant",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert dl.status_code == 200
    fetched = httpx.get(dl.json()["url"])
    assert fetched.status_code == 200
    assert fetched.content == content


def test_idempotency_key_semantics_on_grant_creation(client: TestClient) -> None:
    """Task 2.5 semantics over a real side-effect endpoint."""
    _login(client, "admin", "correct-password")
    payload = {"filename": "idem.png", "content_type": "image/png", "size_bytes": 8}

    first = _create_grant(client, idempotency_key="same-key-1", **payload)
    assert first.status_code == 201
    replay = _create_grant(client, idempotency_key="same-key-1", **payload)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]  # original grant replayed

    conflict = _create_grant(
        client, idempotency_key="same-key-1",
        filename="other.png", content_type="image/png", size_bytes=8,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_forbidden_and_invalid_completions(client: TestClient) -> None:
    _login(client, "admin", "correct-password")
    grant = _create_grant(
        client, filename="guard.txt", content_type="text/plain", size_bytes=4
    ).json()

    # Not uploaded yet -> object_not_uploaded
    missing = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": "0" * 64},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "object_not_uploaded"

    # Editor (different user) cannot complete admin's grant.
    _login(client, "editor", "editor-password")
    forged = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": "0" * 64},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "forbidden"


def test_expired_grant_is_rejected(client: TestClient, db_engine) -> None:
    _login(client, "admin", "correct-password")
    grant = _create_grant(
        client, filename="expired.txt", content_type="text/plain", size_bytes=4
    ).json()

    with Session(db_engine) as session:
        session.execute(
            text("UPDATE upload_grants SET expires_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": grant["id"]},
        )
        session.commit()

    resp = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": "0" * 64},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "grant_expired"


def test_download_requires_access(client: TestClient, db_engine) -> None:
    _login(client, "admin", "correct-password")
    grant = _create_grant(
        client, filename="dl-guard.txt", content_type="text/plain", size_bytes=4
    ).json()
    import httpx as _httpx

    _httpx.put(grant["upload_url"], content=b"abcd")
    done = client.post(
        f"/api/v1/files/upload-grants/{grant['id']}/complete",
        json={"sha256": hashlib.sha256(b"abcd").hexdigest()},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert done.status_code == 200
    object_id = done.json()["id"]

    # Unknown object -> 404 even for a logged-in user.
    unknown = client.post(
        "/api/v1/files/00000000-0000-0000-0000-000000000000/download-grant",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert unknown.status_code == 404

    # Editor has no relation to the object -> 403.
    _login(client, "editor", "editor-password")
    denied = client.post(
        f"/api/v1/files/{object_id}/download-grant",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
