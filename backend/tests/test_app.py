from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import SecretStr

from app.config import ConfigurationError, Settings, load_settings


@pytest.fixture
def app_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_SECRET_KEY", "a" * 40)
    from app.main import create_app

    return create_app


def test_missing_required_secret_has_clear_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="APP_SECRET_KEY is required") as error:
        load_settings()

    assert "Traceback" not in str(error.value)


def test_short_secret_is_rejected_without_echoing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "short-secret"
    monkeypatch.setenv("APP_SECRET_KEY", secret)

    with pytest.raises(ConfigurationError, match="at least 32 characters") as error:
        load_settings()

    assert secret not in str(error.value)


def test_health_check_returns_ok(app_factory) -> None:
    settings = Settings.model_validate({"APP_SECRET_KEY": "t" * 40})
    client = TestClient(app_factory(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unexpected_error_response_hides_exception_and_secret(app_factory) -> None:
    secret = "sensitive-value-that-must-not-leak"
    settings = Settings.model_validate({"APP_SECRET_KEY": secret * 2})
    app = app_factory(settings)

    @app.get("/__test__/failure")
    async def fail() -> None:
        raise RuntimeError(f"database failed with {secret}")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test__/failure")
    body = response.text

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "服务器内部错误"}
    }
    assert secret not in body
    assert "Traceback" not in body
    assert "RuntimeError" not in body


def test_http_error_response_uses_safe_error_envelope(app_factory) -> None:
    secret = "credential-value-that-must-not-leak"
    settings = Settings.model_validate({"APP_SECRET_KEY": "s" * 40})
    app = app_factory(settings)

    @app.get("/__test__/http-error")
    async def fail() -> None:
        raise HTTPException(status_code=400, detail=secret)

    response = TestClient(app).get("/__test__/http-error")

    assert response.status_code == 400
    assert response.json() == {
        "error": {"code": "bad_request", "message": "请求无效"}
    }
    assert secret not in response.text


def test_auth_me_has_no_query_parameters(app_factory) -> None:
    """Regression: unannotated request in get_db leaked a required 'request' query param."""
    settings = Settings.model_validate({"APP_SECRET_KEY": "t" * 40})
    client = TestClient(app_factory(settings))
    spec = client.get("/openapi.json").json()
    params = spec["paths"]["/api/v1/auth/me"]["get"].get("parameters", [])
    assert all(p.get("name") != "request" for p in params)


def test_auth_me_without_cookie_returns_401_not_422(app_factory) -> None:
    """Regression: real get_db dependency must not turn 'request' into a query param."""
    settings = Settings.model_validate({"APP_SECRET_KEY": "t" * 40})
    client = TestClient(app_factory(settings))
    response = client.get("/api/v1/auth/me")
    # No DB configured -> 503; the point is it must NOT be 422 (query validation error).
    assert response.status_code in {401, 503}
    assert response.status_code != 422
