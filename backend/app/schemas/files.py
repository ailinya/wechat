"""File upload authorization, completion and download contracts (task 2.2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UploadGrantRequest(BaseModel):
    """Request a short-lived upload authorization for one object."""

    filename: str = Field(min_length=1, max_length=255, examples=["cover.png"])
    content_type: str = Field(min_length=3, max_length=128, examples=["image/png"])
    size_bytes: int = Field(gt=0, le=52_428_800, description="文件大小（字节），上限 50 MiB")


class UploadGrantOut(BaseModel):
    """A scoped upload authorization. upload_url is null until the RustFS
    adapter lands in task 2.6; the grant row itself is already persisted."""

    id: UUID
    bucket: str = Field(examples=["attachments"])
    object_key: str = Field(examples=["2026/11/ab/cd-ef.png"])
    content_type: str = Field(examples=["image/png"])
    size_bytes: int
    expires_at: datetime
    upload_url: str | None = None


class UploadCompleteRequest(BaseModel):
    """Declare the direct upload finished; the backend verifies before registering."""

    sha256: str = Field(min_length=64, max_length=64, examples=["a" * 64])


class StoredObjectOut(BaseModel):
    """A registered, backend-verified attachment."""

    id: UUID
    bucket: str
    object_key: str
    size_bytes: int
    content_type: str
    sha256: str
    created_at: datetime


class DownloadGrantOut(BaseModel):
    """Short-term download authorization; no long-term credentials included."""

    object_id: UUID
    url: str = Field(examples=["https://rustfs.local/attachments/2026/11/ab/cd-ef.png?X-Amz-Expires=300"])
    expires_at: datetime
