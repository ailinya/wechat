"""User and role management contract schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import PermissionCode, PermissionOut, RoleSummary, UserOut


class PaginationQuery(BaseModel):
    """Query-string pagination; FastAPI reads these as query params."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class UserListQuery(PaginationQuery):
    status: str | None = Field(default=None, examples=["active"])
    keyword: str | None = Field(default=None, max_length=128)


class UserCreate(BaseModel):
    account: str = Field(min_length=1, max_length=64, examples=["editor01"])
    name: str = Field(min_length=1, max_length=128, examples=["张编辑"])
    contact: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=256, examples=["a-strong-password"])
    role_ids: list[UUID] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    contact: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, examples=["disabled"])
    role_ids: list[UUID] | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in {"active", "disabled"}:
            raise ValueError("status must be 'active' or 'disabled'")
        return value


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["reviewer"])
    description: str = Field(default="", max_length=512)


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str
    permissions: list[PermissionOut] = Field(default_factory=list)


class RolePermissionUpdate(BaseModel):
    permission_codes: list[PermissionCode]

    @field_validator("permission_codes")
    @classmethod
    def unique_codes(cls, value: list[PermissionCode]) -> list[PermissionCode]:
        return list(dict.fromkeys(value))


class RoleWithUsers(RoleOut):
    users: list[RoleSummary] = Field(default_factory=list)


__all__ = [
    "UserOut",
    "RoleSummary",
    "PermissionCode",
    "PermissionOut",
    "UserListQuery",
    "UserCreate",
    "UserUpdate",
    "RoleCreate",
    "RoleOut",
    "RolePermissionUpdate",
    "RoleWithUsers",
]
