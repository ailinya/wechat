"""Shared FastAPI dependencies for authentication, CSRF and permissions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.responses import ERROR_EXAMPLES
from app.config import Settings
from app.database import get_db
from app.errors import ApiError
from app.modules.auth.security import tokens_equal
from app.schemas.auth import CurrentUser, PermissionCode
from app.services.auth_service import AuthService

DbSession = Annotated[object, Depends(get_db)]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_user(request: Request, db: DbSession) -> CurrentUser:
    """Resolve the current user from the HttpOnly session cookie."""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    service = AuthService(db, settings.session_ttl_minutes)
    return service.current_user_from_token(token)


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require_permission(code: PermissionCode) -> Callable[..., CurrentUser]:
    """Build a dependency that checks a server-side permission code."""

    def _check(user: CurrentUserDep) -> CurrentUser:
        if code not in user.permissions:
            raise ApiError(403, "forbidden", ERROR_EXAMPLES[403]["error"]["message"])
        return user

    return _check


def verify_csrf(request: Request, user: CurrentUserDep) -> None:
    """Double-submit CSRF check for state-changing requests.

    The CSRF token is mirrored into a readable cookie and echoed by the client
    in the configured header; a valid session cookie is also required, so an
    attacker cannot forge a write with only a same-site cookie.
    """
    settings: Settings = request.app.state.settings
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(settings.csrf_header_name)
    if not tokens_equal(cookie_token, header_token):
        raise ApiError(403, "csrf_failed", "CSRF 校验失败")
