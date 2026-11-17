"""Collection management contracts (task 3.1).

Status vocabulary:
- sources: active / inactive / unavailable
- tasks:   active / paused / archived (archived = deleted; runs and source
           links are preserved so history and traceability survive)
- runs:    pending / running / succeeded / partial / failed
- result parse status:       pending / parsed / failed
- result materialize status: pending / materialized / duplicate /
                             new_progress / ignored / failed
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedModel

SourceStatus = Literal["active", "inactive", "unavailable"]
SourceKind = Literal["rss", "web_page"]
TaskStatus = Literal["active", "paused", "archived"]
RunTrigger = Literal["manual", "scheduled"]
RunStatus = Literal["pending", "running", "succeeded", "partial", "failed"]
ParseStatus = Literal["pending", "parsed", "failed"]
MaterializeStatus = Literal[
    "pending", "materialized", "duplicate", "new_progress", "ignored", "failed"
]


class CollectionSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["行业资讯 RSS"])
    source_type: SourceKind = Field(examples=["rss"])
    base_url: str = Field(min_length=1, max_length=512, examples=["https://example.com/feed"])
    description: str = Field(default="", max_length=512)
    enabled: bool = True


class CollectionSourceOut(TimestampedModel):
    id: UUID
    name: str
    source_type: SourceKind
    base_url: str
    description: str
    enabled: bool
    status: SourceStatus = Field(examples=["active"])
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None


class SourceTestResult(BaseModel):
    """Connection-test outcome; failures carry a readable reason."""

    reachable: bool
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None


class ScheduleIn(BaseModel):
    frequency: Literal["manual", "hourly", "daily", "weekly", "cron"] = "manual"
    cron_expr: str | None = Field(default=None, max_length=64, examples=["0 9 * * 1-5"])
    timezone: str = Field(default="Asia/Shanghai", max_length=64)


class SourceSummary(BaseModel):
    id: UUID
    name: str


class CollectionTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["每日AI资讯采集"])
    keywords: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[UUID] = Field(min_length=1)
    schedule: ScheduleIn = ScheduleIn()
    time_range_days: int = Field(default=7, ge=1, le=365)
    auto_materialize: bool = False
    auto_create: bool = False


class CollectionTaskOut(TimestampedModel):
    id: UUID
    name: str
    status: TaskStatus = Field(examples=["active"])
    keywords: list[str]
    sources: list[SourceSummary]
    schedule: ScheduleIn
    time_range_days: int
    auto_materialize: bool
    auto_create: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class CollectionRunOut(TimestampedModel):
    id: UUID
    task_id: UUID
    trigger: RunTrigger = Field(examples=["manual"])
    status: RunStatus = Field(examples=["running"])
    fetched_count: int = 0
    parsed_count: int = 0
    materialized_count: int = 0
    failed_count: int = 0
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class CollectionResultOut(TimestampedModel):
    id: UUID
    run_id: UUID
    source_id: UUID | None = None
    title: str = Field(examples=["某产品发布新版固件"])
    url: str = Field(examples=["https://example.com/news/1"])
    published_at: datetime | None = None
    collected_at: datetime
    parse_status: ParseStatus = Field(examples=["parsed"])
    materialize_status: MaterializeStatus = Field(examples=["pending"])
    material_id: UUID | None = None
    error: str | None = None


class BulkMaterializeIn(BaseModel):
    result_ids: list[UUID] = Field(min_length=1, max_length=100)


class BulkResultItem(BaseModel):
    """Per-item outcome; a batch never fails as a whole."""

    result_id: UUID
    status: MaterializeStatus
    material_id: UUID | None = None
    error: str | None = None


class BulkResultOut(BaseModel):
    items: list[BulkResultItem]
    counts: dict[str, int] = Field(
        description="按状态计数：materialized / duplicate / new_progress / ignored / failed",
        examples=[{"materialized": 2, "duplicate": 1, "new_progress": 1, "ignored": 0, "failed": 1}],
    )
