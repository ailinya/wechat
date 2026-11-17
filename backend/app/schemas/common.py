"""Shared API contract schemas.

All field names are snake_case, resource identifiers are UUIDs and timestamps
are timezone-aware UTC ISO 8601 values. These models are the single source of
truth for both OpenAPI documentation and request/response validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Common query parameters for list endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数，1-100")


class PaginatedResponse(BaseModel, Generic[T]):
    """Envelope returned by every list endpoint."""

    items: list[T]
    total: int = Field(ge=0, description="符合筛选条件的总条数")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class FieldError(BaseModel):
    field: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] | None = None


class ErrorEnvelope(BaseModel):
    """Uniform error shape; never contains stack traces or credentials."""

    error: ErrorDetail


class OkResponse(BaseModel):
    status: str = "ok"


class AsyncJobAccepted(BaseModel):
    """Body of an HTTP 202 async acceptance (contract defined in phase 2)."""

    async_job_id: UUID
    resource_type: str
    resource_id: UUID
    status: str = "accepted"


def utc_example(value: str = "2026-11-17T08:00:00Z") -> dict[str, Any]:
    """Attach a UTC ISO 8601 example to a datetime field in JSON schema."""
    return {"json_schema_extra": {"example": value}}


class TimestampedModel(BaseModel):
    """Base for responses carrying UTC created/updated timestamps."""

    created_at: datetime = Field(
        json_schema_extra={"example": "2026-11-17T08:00:00Z"}
    )
    updated_at: datetime = Field(
        json_schema_extra={"example": "2026-11-17T08:00:00Z"}
    )
