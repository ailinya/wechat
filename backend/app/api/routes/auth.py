"""Authentication endpoints.

Login establishes an HttpOnly session cookie plus a readable CSRF cookie.
Logout revokes the session. Handlers never return credentials in the body and
all failures use the shared error envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DbSession
from app.api.responses import error_responses
from app.config import Settings
from app.schemas.auth import CurrentUser, LoginRequest, LoginResponse
from app.schemas.common import OkResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_SUCCESS_RESPONSE = {
    "description": "登录成功；会话 Cookie 为 HttpOnly，CSRF Cookie 可读",
    "content": {
        "application/json": {
            "example": {
                "user": {
                    "id": "3f4a1b2c-5d6e-4f70-8a91-0b2c3d4e5f60",
                    "account": "admin",
                    "name": "系统管理员",
                    "status": "active",
                    "roles": ["admin"],
                    "permissions": ["user:read", "user:write"],
                },
                "expires_at": "2026-11-18T08:00:00Z",
            }
        }
    },
}


def _auth_service(request: Request, db) -> AuthService:
    settings: Settings = request.app.state.settings
    return AuthService(db, settings.session_ttl_minutes)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={**error_responses(400, 401, 422), 200: _LOGIN_SUCCESS_RESPONSE},
    summary="登录并建立会话",
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> LoginResponse:
    settings: Settings = request.app.state.settings
    user, session_token, csrf_token, _expires_at = _auth_service(request, db).login(
        payload.account, payload.password
    )
    expires_at = _expires_at.isoformat().replace("+00:00", "Z")

    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    return LoginResponse(user=user, expires_at=expires_at)


@router.post(
    "/logout",
    response_model=OkResponse,
    responses={**error_responses(401)},
    summary="注销当前会话",
)
async def logout(request: Request, response: Response, db: DbSession) -> OkResponse:
    settings: Settings = request.app.state.settings
    _auth_service(request, db).logout(request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return OkResponse()


@router.get(
    "/me",
    response_model=CurrentUser,
    responses={**error_responses(401, 403)},
    summary="获取当前用户与权限",
)
async def me(request: Request, db: DbSession) -> CurrentUser:
    return _auth_service(request, db).current_user_from_token(
        request.cookies.get(request.app.state.settings.session_cookie_name)
    )
