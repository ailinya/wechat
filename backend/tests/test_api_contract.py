"""Tests for the fixed OpenAPI contract (task 1.5)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from app.api.responses import ERROR_EXAMPLES
from app.config import Settings
from app.main import create_app
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.schemas.auth import (
    INITIAL_ROLE_PERMISSIONS,
    CurrentUser,
    LoginRequest,
    PermissionCode,
)
from app.schemas.users import UserCreate, UserOut


@pytest.fixture
def client() -> TestClient:
    # A syntactically valid URL lets get_db build an engine (no connection is
    # made until a query runs), so body-validation errors surface as 422.
    settings = Settings.model_validate(
        {
            "APP_SECRET_KEY": "t" * 40,
            "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:1/db",
        }
    )
    return TestClient(create_app(settings))


def test_openapi_is_generatable_with_all_contract_paths(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    expected_paths = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/users",
        "/api/v1/users/{user_id}",
        "/api/v1/roles",
        "/api/v1/roles/{role_id}",
        "/api/v1/roles/{role_id}/permissions",
    }
    assert expected_paths <= set(spec["paths"])


def test_openapi_documents_success_and_error_schemas(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for name in ("ErrorEnvelope", "CurrentUser", "LoginResponse", "PermissionCode"):
        assert name in schemas

    login_ok = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]
    assert "example" in login_ok["content"]["application/json"]
    login_401 = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["401"]
    assert "example" in login_401["content"]["application/json"]


def test_success_and_failure_examples_conform_to_their_schema(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()

    login_ok = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]
    example_user = login_ok["content"]["application/json"]["example"]["user"]
    CurrentUser.model_validate(example_user)

    for status, example in ERROR_EXAMPLES.items():
        assert status in {400, 401, 403, 404, 409, 422}
        ErrorEnvelope.model_validate(example)


def test_login_request_validation_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        LoginRequest(account="", password="x")


def test_paginated_response_contract() -> None:
    page = PaginatedResponse[UserOut](items=[], total=0, page=1, page_size=20)
    assert page.model_dump() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
    }


def test_permission_codes_stable_and_unique() -> None:
    codes = [code.value for code in PermissionCode]
    assert len(codes) == len(set(codes))
    assert "publish:confirm" in codes
    assert "article:review" in codes


def test_initial_roles_cover_four_required_roles() -> None:
    assert set(INITIAL_ROLE_PERMISSIONS) == {
        "admin",
        "operations",
        "editor",
        "reviewer",
    }
    assert frozenset(PermissionCode) == INITIAL_ROLE_PERMISSIONS["admin"]
    assert PermissionCode.PUBLISH_CONFIRM in INITIAL_ROLE_PERMISSIONS["operations"]
    assert PermissionCode.ARTICLE_REVIEW in INITIAL_ROLE_PERMISSIONS["reviewer"]


def test_user_create_never_exposes_password_in_output_schema() -> None:
    assert "password" in UserCreate.model_fields
    assert "password_hash" not in UserOut.model_fields
    assert "password" not in UserOut.model_fields


def test_auth_login_validation_error_uses_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"account": "", "password": ""}
    )
    assert response.status_code == 422
    body = response.json()
    ErrorEnvelope.model_validate(body)
    assert body["error"]["code"] == "validation_error"
