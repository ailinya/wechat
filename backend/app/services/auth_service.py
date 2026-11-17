"""Authentication business logic."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app import errors
from app.modules.auth.security import (
    hash_password,
    new_csrf_token,
    new_session_token,
    verify_password,
)
from app.repositories import auth_repository as repo
from app.schemas.auth import CurrentUser, PermissionCode, RoleSummary


class AuthService:
    def __init__(self, db: Session, ttl_minutes: int) -> None:
        self.db = db
        self.ttl_minutes = ttl_minutes

    def login(self, account: str, password: str) -> tuple[CurrentUser, str, str, datetime]:
        """Authenticate and create a session.

        Returns (current_user, session_token, csrf_token, expires_at). Raises a
        401 ApiError for unknown accounts, wrong passwords or disabled users,
        with a message that never distinguishes which of the three failed.
        """
        conn = self.db.connection()
        user = repo.find_user_by_account(conn, account)
        if not user or not verify_password(password, user["password_hash"]):
            raise errors.ApiError(401, "unauthorized", "账号或密码错误")
        if user["status"] != "active":
            raise errors.ApiError(401, "unauthorized", "账号或密码错误")

        session_token = new_session_token()
        csrf_token = new_csrf_token()
        expires_at = repo.create_session(conn, user["id"], session_token, self.ttl_minutes)
        self.db.commit()

        current_user = self._current_user(user)
        return current_user, session_token, csrf_token, expires_at

    def _current_user(self, user: dict[str, Any]) -> CurrentUser:
        conn = self.db.connection()
        role_rows = repo.roles_for_user(conn, user["id"])
        roles = [RoleSummary(id=row["id"], name=row["name"]) for row in role_rows]
        codes = repo.permissions_for_user(conn, user["id"])
        return CurrentUser(
            id=user["id"],
            account=user["account"],
            name=user["name"],
            status=user["status"],
            roles=[r.name for r in roles],
            permissions=[PermissionCode(code) for code in codes if code in PermissionCode._value2member_map_],
        )

    def current_user_from_token(self, token: str | None) -> CurrentUser:
        if not token:
            raise errors.ApiError(401, "unauthorized", "请先登录")
        conn = self.db.connection()
        user_id = repo.active_session_user_id(conn, token)
        if user_id is None:
            raise errors.ApiError(401, "unauthorized", "会话无效或已过期")
        user = repo.get_user(conn, user_id)
        if not user or user["status"] != "active":
            raise errors.ApiError(401, "unauthorized", "账号已被禁用")
        return self._current_user(user)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        conn = self.db.connection()
        repo.revoke_session(conn, token)
        self.db.commit()


__all__ = ["AuthService", "hash_password"]
