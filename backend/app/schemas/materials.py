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

from pydantic import BaseModel, Field

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


class MaterialRevisionOut(BaseModel):
    id: UUID
    material_id: UUID
    revision_no: int = Field(ge=1, examples=[1])
    content_markdown: str = Field(examples=["**固件 2.1** 修复了中文输入问题……"])
    file_ids: list[UUID] = []
    created_by: UUID | None = None
    created_at: datetime


class MaterialCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    content_markdown: str = Field(min_length=1, max_length=200_000)
    category_id: UUID | None = None
    tag_ids: list[UUID] = []


class MaterialUpdateIn(BaseModel):
    """content_markdown/title change creates a NEW revision (immutable history);
    usage_status/category/tags mutate the material itself."""

    title: str | None = Field(default=None, min_length=1, max_length=256)
    content_markdown: str | None = Field(default=None, min_length=1, max_length=200_000)
    usage_status: UsageStatus | None = None
    category_id: UUID | None = None
    tag_ids: list[UUID] | None = None


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
