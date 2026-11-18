"""Material library contracts (task 3.1).

Usage-status transitions (task 3.8 enforces them server-side):
    pending_review -> ready_to_use | archived
    ready_to_use   -> used | partially_used | archived
    used / partially_used -> ready_to_use (reuse) | archived
    archived -> ready_to_use (unarchive)
`duplicate` is assigned by the dedup flow, not by users.

Deletion semantics: DELETE is a soft delete (archived + deleted flag);
existing article references keep pointing at the revisions they used.
Favorites are isolated per user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import TimestampedModel

UsageStatus = Literal[
    "pending_review",
    "ready_to_use",
    "partially_used",
    "used",
    "archived",
    "duplicate",
]
MaterialOrigin = Literal[
    "collection", "upload", "link", "manual", "article", "enterprise"
]


class TagOut(BaseModel):
    id: UUID
    name: str = Field(examples=["行业动态"])


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class MaterialCategoryOut(TimestampedModel):
    id: UUID
    name: str
    parent_id: UUID | None = None


class MaterialCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: UUID | None = None


class MaterialOut(TimestampedModel):
    id: UUID
    title: str
    origin: MaterialOrigin = Field(examples=["collection"])
    usage_status: UsageStatus = Field(examples=["pending_review"])
    current_revision_id: UUID
    category_id: UUID | None = None
    tags: list[TagOut] = []
    metadata_version: int = 1
    summary: str = ''


class MaterialRevisionOut(BaseModel):
    id: UUID
    material_id: UUID
    revision_no: int = Field(ge=1, examples=[1])
    content_markdown: str = Field(examples=["**固件 2.1** 修复了中文输入问题……"])
    file_ids: list[UUID] = []
    created_by: UUID | None = None
    created_at: datetime


class EmbeddingRebuildIn(BaseModel):
    revision_id: UUID | None = None


class EmbeddingRebuildOut(BaseModel):
    async_job_id: UUID
    resource_id: UUID
    revision_id: UUID
    status: Literal["pending", "running", "succeeded"]
    reused: bool


class MaterialSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    scope: Literal["current", "all"] = "current"
    from_time: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    statuses: list[UsageStatus] | None = None
    top_k: int = Field(default=20, ge=1, le=100)
    min_relevance: float = Field(default=0, ge=0, le=1)
    keyword_mode: Literal["hybrid", "keyword_only"] = "hybrid"

    @field_validator("query")
    @classmethod
    def nonempty_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("查询不能为空")
        return value.strip()

    @model_validator(mode="after")
    def valid_dates(self):
        for value in (self.from_time, self.to):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("时间必须包含时区")
        if self.from_time and self.to and self.from_time > self.to:
            raise ValueError("开始时间不能晚于结束时间")
        return self


class MaterialSearchSource(BaseModel):
    type: str
    title: str | None = None
    url: str | None = None
    attachment_id: UUID | None = None


class MaterialSearchItem(BaseModel):
    material_id: UUID
    title: str
    matched_revision_id: UUID
    snippet: str
    source: MaterialSearchSource
    published_at: datetime | None = None
    keyword_score: float
    semantic_score: float | None = None
    relevance_score: float
    score_explanation: str
    usage_status: UsageStatus


class MaterialSearchOut(BaseModel):
    items: list[MaterialSearchItem]
    mode: Literal["hybrid", "keyword_only"]
    degraded: bool = False
    degradation_reason: str | None = None


class MaterialCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    content_markdown: str = Field(min_length=1, max_length=200_000)
    category_id: UUID | None = None
    tag_ids: list[UUID] = []


class MaterialLinkIn(BaseModel):
    """Create a material from a web link (task 3.8)."""

    url: str = Field(min_length=1, max_length=2048, examples=["https://example.com/article"])
    title: str | None = Field(default=None, max_length=256)


class MaterialUploadIn(BaseModel):
    """Create a material from an already-registered stored object (task 3.8)."""

    object_id: UUID
    title: str = Field(min_length=1, max_length=256)


class MaterialUpdateIn(BaseModel):
    """content_markdown/title change creates a NEW revision (immutable history);
    usage_status/category/tags mutate the material itself."""

    title: str | None = Field(default=None, min_length=1, max_length=256)
    content_markdown: str | None = Field(default=None, min_length=1, max_length=200_000)
    usage_status: UsageStatus | None = None
    category_id: UUID | None = None
    tag_ids: list[UUID] | None = None
    summary: str | None = Field(default=None,max_length=4000)
    base_metadata_version: int | None = Field(default=None,ge=1)


class MaterialDetailOut(MaterialOut):
    current_revision: MaterialRevisionOut
    favorite_count: int = 0
    favorited_by_me: bool = False


class MaterialOriginRef(BaseModel):
    """Collection-result / upload provenance of a material (双向引用追踪)."""

    kind: Literal["collection_result", "upload", "link", "manual", "article"]
    reference_id: UUID
    url: str | None = None
    collected_at: datetime | None = None


class MaterialArticleRef(BaseModel):
    """An article (version) that used this material, with the revision it used."""

    article_id: UUID
    article_title: str
    article_revision_id: UUID
    material_revision_id: UUID
    used_at: datetime


class FavoriteOut(BaseModel):
    material_id: UUID
    user_id: UUID
    created_at: datetime


class BulkActionIn(BaseModel):
    material_ids: list[UUID] = Field(min_length=1, max_length=100)
    action: Literal[
        "archive", "unarchive", "mark_used", "mark_ready", "set_category", "add_tags", "remove_tags"
    ]
    category_id: UUID | None = None
    tag_ids: list[UUID] = []


class BulkActionItem(BaseModel):
    material_id: UUID
    status: Literal["success", "skipped", "failed"]
    error: str | None = None


class BulkActionOut(BaseModel):
    items: list[BulkActionItem]
    counts: dict[str, int] = Field(
        examples=[{"success": 3, "skipped": 1, "failed": 0}]
    )


class MaterialDeleteOut(BaseModel):
    """Soft delete: references (article versions, collection results, origin
    links) stay intact and resolvable."""

    id: UUID
    usage_status: UsageStatus
    deleted_at: datetime
    references_preserved: bool = True
