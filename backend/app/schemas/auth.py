"""Authentication and permission contract schemas."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel


class PermissionCode(StrEnum):
    """Stable permission codes used by role assignments and server checks."""

    USER_READ = "user:read"
    USER_WRITE = "user:write"
    ROLE_READ = "role:read"
    ROLE_WRITE = "role:write"
    COLLECTION_READ = "collection:read"
    COLLECTION_WRITE = "collection:write"
    COLLECTION_RUN = "collection:run"
    MATERIAL_READ = "material:read"
    MATERIAL_WRITE = "material:write"
    MATERIAL_SEARCH = "material:search"
    CREATION_READ = "creation:read"
    CREATION_WRITE = "creation:write"
    ARTICLE_READ = "article:read"
    ARTICLE_WRITE = "article:write"
    ARTICLE_REVIEW = "article:review"
    ACCOUNT_READ = "account:read"
    ACCOUNT_WRITE = "account:write"
    PUBLISH_READ = "publish:read"
    PUBLISH_CONFIRM = "publish:confirm"
    PUBLISH_EXECUTE = "publish:execute"
    ANALYTICS_READ = "analytics:read"
    ANALYTICS_EXPORT = "analytics:export"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"
    OPERATION_LOG_READ = "operation_log:read"


# Initial permission configuration for the four required roles. The backend
# task (1.6) seeds/reconciles these; the contract fixes the codes here.
INITIAL_ROLE_PERMISSIONS: dict[str, frozenset[PermissionCode]] = {
    "admin": frozenset(PermissionCode),
    "operations": frozenset(
        {
            PermissionCode.MATERIAL_READ,
            PermissionCode.MATERIAL_SEARCH,
            PermissionCode.COLLECTION_READ,
            PermissionCode.COLLECTION_RUN,
            PermissionCode.CREATION_READ,
            PermissionCode.ARTICLE_READ,
            PermissionCode.ACCOUNT_READ,
            PermissionCode.PUBLISH_READ,
            PermissionCode.PUBLISH_CONFIRM,
            PermissionCode.ANALYTICS_READ,
            PermissionCode.ANALYTICS_EXPORT,
        }
    ),
    "editor": frozenset(
        {
            PermissionCode.MATERIAL_READ,
            PermissionCode.MATERIAL_WRITE,
            PermissionCode.MATERIAL_SEARCH,
            PermissionCode.COLLECTION_READ,
            PermissionCode.CREATION_READ,
            PermissionCode.CREATION_WRITE,
            PermissionCode.ARTICLE_READ,
            PermissionCode.ARTICLE_WRITE,
        }
    ),
    "reviewer": frozenset(
        {
            PermissionCode.MATERIAL_READ,
            PermissionCode.MATERIAL_SEARCH,
            PermissionCode.ARTICLE_READ,
            PermissionCode.ARTICLE_REVIEW,
            PermissionCode.PUBLISH_READ,
        }
    ),
}


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=64, examples=["admin"])
    password: str = Field(min_length=1, max_length=256, examples=["correct-password"])


class PermissionOut(BaseModel):
    id: UUID
    code: PermissionCode
    module: str
    action: str


class RoleSummary(BaseModel):
    id: UUID
    name: str


class CurrentUser(BaseModel):
    """Identity returned by login and /auth/me; never includes credentials."""

    id: UUID
    account: str
    name: str
    status: str = Field(examples=["active"])
    roles: list[str] = Field(default_factory=list, examples=[["admin"]])
    permissions: list[PermissionCode] = Field(default_factory=list)


class LoginResponse(BaseModel):
    user: CurrentUser
    expires_at: str = Field(
        description="会话过期的 UTC ISO 8601 时间",
        examples=["2026-11-18T08:00:00Z"],
    )


class UserOut(TimestampedModel):
    id: UUID
    account: str
    name: str
    contact: str | None = None
    status: str = Field(examples=["active"])
    roles: list[RoleSummary] = Field(default_factory=list)
