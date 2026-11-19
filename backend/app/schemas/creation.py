"""Creation rules, requests, decisions, jobs and immutable outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, model_validator

TriggerType = Literal["collection_completed", "schedule", "new_material_count", "manual"]
MaterialStrategy = Literal["new_only", "new_and_unused", "all"]
CreationMode = Literal["automatic", "material", "topic"]
CreationStatus = Literal["pending", "running", "insufficient", "succeeded", "failed", "cancelled"]
DecisionReason = Literal["new_materials_insufficient", "material_count_insufficient", "relevance_insufficient", "body_unavailable", "duplicate_topic", "active_task"]


class GenerationModelOut(BaseModel):
    id: UUID
    name: str
    model_name: str


class TriggerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    new_material_threshold: int = Field(default=1, ge=1, le=10000)


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    topic: str = Field(default="", max_length=500)
    collection_task_ids: list[UUID] = Field(default_factory=list, max_length=100)
    trigger_type: TriggerType
    trigger_config: TriggerConfig = Field(default_factory=TriggerConfig)
    material_strategy: MaterialStrategy = "new_and_unused"
    filters: dict = Field(default_factory=dict)
    min_new_material_count: int = Field(default=1, ge=0, le=100)
    min_material_count: int = Field(default=1, ge=1, le=100)
    min_relevance: float = Field(default=0, ge=0, le=1)
    reference_count: int = Field(default=3, ge=1, le=100)
    batch_count: int = Field(default=1, ge=1, le=20)
    article_type: str = Field(default="news", min_length=1, max_length=64)
    writing_style: str = Field(default="客观", min_length=1, max_length=128)
    min_words: int = Field(default=300, ge=1, le=20000)
    max_words: int = Field(default=1200, ge=1, le=20000)
    model_config_id: UUID
    prompt: str = Field(default="", max_length=10000)
    require_analysis: bool = False
    target_account_id: UUID | None = Field(default=None, description="建议目标公众号；仍须人工审核和逐单确认发布")
    enabled: bool = True

    @model_validator(mode="after")
    def validate_rule(self):
        if self.min_words > self.max_words:
            raise ValueError("最小字数不能大于最大字数")
        if self.trigger_type == "schedule" and not self.trigger_config.cron:
            raise ValueError("定时触发需要 cron")
        if self.trigger_config.cron and not croniter.is_valid(self.trigger_config.cron):
            raise ValueError("cron 表达式无效")
        try:
            ZoneInfo(self.trigger_config.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("时区无效") from None
        if self.reference_count < self.min_material_count:
            raise ValueError("每篇引用数不能小于最低素材数")
        if set(self.filters) - {"category_id", "origins"}:
            raise ValueError("不支持的素材筛选条件")
        if "origins" in self.filters and (not isinstance(self.filters["origins"], list) or any(not isinstance(x, str) for x in self.filters["origins"])):
            raise ValueError("来源筛选必须为字符串数组")
        if "category_id" in self.filters:
            try:
                UUID(str(self.filters["category_id"]))
            except ValueError:
                raise ValueError("分类标识无效") from None
        if len(set(self.collection_task_ids)) != len(self.collection_task_ids):
            raise ValueError("采集任务不能重复")
        return self


class RuleOut(RuleIn):
    id: UUID
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class SelectedMaterial(BaseModel):
    material_id: UUID
    revision_id: UUID


class CreationTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["material", "topic"]
    topic: str = Field(default="", max_length=500)
    materials: list[SelectedMaterial] = Field(min_length=1, max_length=100)
    model_config_id: UUID
    article_type: str = Field(default="news", min_length=1, max_length=64)
    writing_style: str = Field(default="客观", min_length=1, max_length=128)
    min_words: int = Field(default=300, ge=1, le=20000)
    max_words: int = Field(default=1200, ge=1, le=20000)
    batch_count: int = Field(default=1, ge=1, le=20)
    prompt: str = Field(default="", max_length=10000)
    min_material_count: int = Field(default=1, ge=1, le=100)
    min_relevance: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_request(self):
        if self.mode == "topic" and not self.topic.strip():
            raise ValueError("主题创作必须提供主题")
        if self.min_words > self.max_words:
            raise ValueError("最小字数不能大于最大字数")
        if len({m.material_id for m in self.materials}) != len(self.materials):
            raise ValueError("素材不能重复")
        return self


class CreationDecision(BaseModel):
    status: Literal["satisfied", "insufficient"]
    reasons: list[DecisionReason] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class CandidateMaterial(SelectedMaterial):
    selected: bool
    relevance_score: float | None = None
    selection_reason: str | None = None


class CreationTaskOut(BaseModel):
    id: UUID
    rule_id: UUID | None = None
    source_task_id: UUID | None = None
    mode: CreationMode
    topic: str
    status: CreationStatus
    trigger_type: TriggerType
    trigger_source: str | None = None
    trigger_window: str
    decision: CreationDecision | None = None
    async_job_id: UUID | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    materials: list[SelectedMaterial] = Field(default_factory=list)
    candidates: list[CandidateMaterial] = Field(default_factory=list)


class CreationAccepted(BaseModel):
    async_job_id: UUID | None = None
    resource_id: UUID
    status: CreationStatus
    reused: bool = False
    decision: CreationDecision | None = None


class CreationOutputOut(BaseModel):
    id: UUID
    creation_task_id: UUID
    slot: int = Field(ge=1)
    article_id: UUID
    article_revision_id: UUID
    title: str
    candidate_titles: list[str]
    summary: str
    outline: list[str]
    body_markdown: str
    keywords: list[str]
    cover_suggestion: str
    citations: list[SelectedMaterial]
    generated_at: datetime


class GeneratedDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=512)
    candidate_titles: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=4000)
    outline: list[str] = Field(min_length=1, max_length=100)
    body_markdown: str = Field(min_length=1, max_length=100000)
    keywords: list[str] = Field(min_length=1, max_length=50)
    cover_suggestion: str = Field(min_length=1, max_length=4000)
    citations: list[SelectedMaterial] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def nonblank_content(self):
        if any(not value.strip() for value in [self.title, self.summary, self.body_markdown, self.cover_suggestion, *self.candidate_titles, *self.outline, *self.keywords]):
            raise ValueError("生成内容不能为空")
        if len({item.material_id for item in self.citations}) != len(self.citations):
            raise ValueError("素材引用不能重复")
        return self


class CreationBatchItem(BaseModel):
    resource_id: UUID
    status: Literal["accepted", "reused", "failed"]
    error_code: str | None = None


class CreationBatchOut(BaseModel):
    items: list[CreationBatchItem]
