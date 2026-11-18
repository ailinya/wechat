"""Collection management contracts (task 3.1 + enhancement task 3.14).

Status vocabulary:
- sources: active / inactive / unavailable
- tasks:   active / paused / archived (archived = deleted; runs and source
           links are preserved so history and traceability survive)
- runs:    pending / running / succeeded / partial / failed
           (end_reason adds cancelled / budget_exhausted / error)
- result parse status:       pending / parsed / failed
- result materialize status: pending / materialized / duplicate /
                             new_progress / ignored / failed

Enhancement (3.14): two collection modes, optional domain restriction, limits,
analysis config and stage counts. Old requests stay compatible: `mode` defaults
to `source`, `analysis.enabled` defaults to false, source `page_kind` defaults
to `article`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import TimestampedModel

SourceStatus = Literal["active", "inactive", "unavailable"]
SourceKind = Literal["rss", "web_page"]
PageKind = Literal["article", "list"]
TaskStatus = Literal["active", "paused", "archived"]
RunTrigger = Literal["manual", "scheduled"]
RunStatus = Literal["pending", "running", "succeeded", "partial", "failed"]
RunEndReason = Literal["completed", "cancelled", "budget_exhausted", "error"]
ParseStatus = Literal["pending", "parsed", "failed"]
MaterializeStatus = Literal[
    "pending", "materialized", "duplicate", "new_progress", "ignored", "failed"
]
CollectionMode = Literal["source", "topic_search"]
AnalysisApplyPolicy = Literal["suggest_only", "fill_empty"]


class CollectionSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["行业资讯 RSS"])
    source_type: SourceKind = Field(examples=["rss"])
    base_url: str = Field(min_length=1, max_length=512, examples=["https://example.com/feed"])
    description: str = Field(default="", max_length=512)
    enabled: bool = True
    page_kind: PageKind = Field(default="article", examples=["article"])
    article_link_selector: str | None = Field(default=None, max_length=256)
    next_page_selector: str | None = Field(default=None, max_length=256)


class CollectionSourceOut(TimestampedModel):
    id: UUID
    name: str
    source_type: SourceKind
    base_url: str
    description: str
    enabled: bool
    status: SourceStatus = Field(examples=["active"])
    page_kind: PageKind = Field(examples=["article"])
    article_link_selector: str | None = None
    next_page_selector: str | None = None
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


class AnalysisConfigIn(BaseModel):
    """Per-task LLM analysis configuration (default off = old behaviour)."""

    enabled: bool = False
    model_config_id: UUID | None = None
    apply_policy: AnalysisApplyPolicy = "suggest_only"


class AnalysisConfigOut(AnalysisConfigIn):
    pass


class CollectionTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["每日AI资讯采集"])
    mode: CollectionMode = Field(default="source", examples=["source"])
    topic: str | None = Field(default=None, max_length=256)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[UUID] = Field(default_factory=list, max_length=20)
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)
    schedule: ScheduleIn = ScheduleIn()
    time_range_days: int = Field(default=7, ge=1, le=365)
    max_candidates: int = Field(default=100, ge=1, le=100)
    max_fetch: int = Field(default=20, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1, le=20)
    analysis: AnalysisConfigIn = AnalysisConfigIn()
    search_config_id: UUID | None = None
    auto_materialize: bool = False
    auto_create: bool = False

    @model_validator(mode="after")
    def _validate_mode(self) -> "CollectionTaskIn":
        if self.mode == "source":
            if not self.source_ids:
                raise ValueError("source 模式至少需要一个来源")
        else:  # topic_search
            if self.source_ids:
                raise ValueError("topic_search 模式不接受 source_ids，域名限定请用 allowed_domains")
            if not self.topic or not self.topic.strip():
                raise ValueError("topic_search 模式需要非空 topic")
        return self


class CollectionTaskUpdateIn(BaseModel):
    """Partial update: omitted fields keep their stored value (exclude_unset)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    mode: CollectionMode | None = None
    topic: str | None = Field(default=None, max_length=256)
    keywords: list[str] | None = Field(default=None, max_length=20)
    source_ids: list[UUID] | None = Field(default=None, max_length=20)
    allowed_domains: list[str] | None = Field(default=None, max_length=20)
    schedule: ScheduleIn | None = None
    time_range_days: int | None = Field(default=None, ge=1, le=365)
    max_candidates: int | None = Field(default=None, ge=1, le=100)
    max_fetch: int | None = Field(default=None, ge=1, le=100)
    max_pages: int | None = Field(default=None, ge=1, le=20)
    analysis: AnalysisConfigIn | None = None
    search_config_id: UUID | None = None
    auto_materialize: bool | None = None
    auto_create: bool | None = None


class CollectionTaskOut(TimestampedModel):
    id: UUID
    name: str
    status: TaskStatus = Field(examples=["active"])
    mode: CollectionMode = Field(examples=["source"])
    topic: str | None = None
    keywords: list[str]
    sources: list[SourceSummary]
    allowed_domains: list[str] = []
    schedule: ScheduleIn
    time_range_days: int
    max_candidates: int
    max_fetch: int
    max_pages: int
    analysis: AnalysisConfigOut = AnalysisConfigOut()
    search_config_id: UUID | None = None
    auto_materialize: bool
    auto_create: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None


class CollectionRunOut(TimestampedModel):
    id: UUID
    task_id: UUID
    trigger: RunTrigger = Field(examples=["manual"])
    status: RunStatus = Field(examples=["running"])
    end_reason: RunEndReason | None = None
    fetched_count: int = 0
    parsed_count: int = 0
    materialized_count: int = 0
    failed_count: int = 0
    discovered_count: int = 0
    analyzed_count: int = 0
    filtered_count: int = 0
    review_required_count: int = 0
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


class ManualRetentionIn(BaseModel):
    """Keep an uncertain/failed result as a pending-review material (task 3.14)."""

    result_id: UUID
    reason: str = Field(min_length=1, max_length=512)
