"""Async job query and cancellation contracts (task 2.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel

AsyncJobStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class AsyncJobOut(TimestampedModel):
    """Persistent state of an accepted background job."""

    id: UUID
    job_type: str = Field(examples=["collection.fetch"])
    resource_type: str = Field(examples=["collection_task"])
    resource_id: UUID
    status: AsyncJobStatus = Field(examples=["running"])
    stage: str = Field(examples=["fetching"])
    progress: int = Field(ge=0, le=100, examples=[40])
    attempts: int = Field(ge=0, examples=[1])
    last_error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
