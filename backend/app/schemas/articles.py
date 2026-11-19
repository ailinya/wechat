"""Phase 6 article editing and human review API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ArticleStatus = Literal['draft', 'pending_review', 'approved', 'returned', 'rejected', 'published']
ArticleOrigin = Literal['manual', 'generated']
ReviewAction = Literal['approve', 'return', 'reject']
CheckResult = Literal['pass', 'fail', 'not_applicable']
AiAction = Literal['polish', 'continue', 'expand', 'shorten', 'rewrite', 'title', 'summary']


class MaterialReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    material_id: UUID
    material_revision_id: UUID = Field(description='必须属于指定素材的不可变修订')


class ArticleReferenceOut(MaterialReference):
    title: str
    content_markdown: str
    source_url: str | None = None


class LayoutConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template: Literal['classic', 'news', 'minimal'] = 'classic'
    font_family: Literal['sans-serif', 'serif'] = 'sans-serif'
    font_size: int = Field(default=16, ge=12, le=24)
    line_height: float = Field(default=1.8, ge=1.2, le=2.5)
    paragraph_spacing: int = Field(default=16, ge=0, le=40)
    image_style: Literal['square', 'rounded'] = 'rounded'


class ArticlePreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body_markdown: str = Field(max_length=200000)
    layout_config: LayoutConfig = Field(default_factory=LayoutConfig)


class ArticlePreviewOut(BaseModel):
    html: str


class ArticleDetailOut(BaseModel):
    """Compatible with the existing generated-article detail endpoint."""
    id: UUID
    status: ArticleStatus
    origin_type: ArticleOrigin
    creation_task_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    revision_id: UUID
    version: int = Field(ge=1)
    title: str
    author: str
    cover_object_id: UUID | None
    layout_config: dict
    summary: str
    body_markdown: str
    keywords: list[str]
    materials: list[ArticleReferenceOut]
    publish_summary: dict[str, int] = Field(default_factory=dict)
    draft_summary: dict[str, int] = Field(default_factory=dict)


class ArticleContent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=512)
    author: str = Field(default='', max_length=255)
    summary: str = Field(default='', max_length=4000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    body_markdown: str = Field(min_length=1, max_length=200000)
    cover_object_id: UUID | None = None
    layout_config: LayoutConfig = Field(default_factory=LayoutConfig)
    materials: list[MaterialReference] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_content(self):
        if not self.title.strip() or not self.body_markdown.strip():
            raise ValueError('标题和正文不能为空')
        if any(not keyword.strip() for keyword in self.keywords):
            raise ValueError('关键词不能为空')
        if len({item.material_id for item in self.materials}) != len(self.materials):
            raise ValueError('同一素材不能重复引用')
        return self


class ArticleCreateIn(ArticleContent):
    """Create a manual draft and its first revision."""


class ArticleRevisionCreateIn(ArticleContent):
    base_revision_id: UUID = Field(description='编辑基准；必须等于保存时的当前修订，否则返回 409 revision_conflict')


class ArticleRevisionOut(ArticleContent):
    id: UUID
    article_id: UUID
    version: int = Field(ge=1)
    created_by: UUID | None = None
    created_at: datetime


class ArticleSummaryOut(BaseModel):
    id: UUID
    status: ArticleStatus
    origin_type: ArticleOrigin
    creation_task_id: UUID | None = None
    current_revision_id: UUID
    version: int = Field(ge=1)
    title: str
    author: str
    created_at: datetime
    updated_at: datetime
    publish_summary: dict[str, int] = Field(default_factory=dict)
    draft_summary: dict[str, int] = Field(default_factory=dict)


class ArticleSaveOut(BaseModel):
    article_id: UUID
    status: Literal['draft'] = Field(description='新修订默认需要重新提审')
    current_revision_id: UUID
    revision: ArticleRevisionOut


class AiEditIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision_id: UUID
    action: AiAction
    model_config_id: UUID
    selected_text: str | None = Field(default=None, max_length=200000)
    instruction: str = Field(default='', max_length=4000)


class AiSuggestionOut(BaseModel):
    article_id: UUID
    base_revision_id: UUID
    action: AiAction
    suggestion: str
    model_config_id: UUID
    model_config_version: int = Field(ge=1)


class SubmitReviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision_id: UUID = Field(description='必须是当前修订；旧修订返回 409 revision_conflict')


class SubmitReviewOut(BaseModel):
    article_id: UUID
    revision_id: UUID
    status: Literal['pending_review']


class ReviewChecklist(BaseModel):
    """Stable review keys; missing items may be saved only with return/reject."""
    model_config = ConfigDict(extra='forbid')
    title: CheckResult | None = None
    content: CheckResult | None = None
    facts: CheckResult | None = None
    citations: CheckResult | None = None
    image_copyright: CheckResult | None = None
    account_compliance: CheckResult | None = None
    layout: CheckResult | None = None


class ReviewCreateIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: ReviewAction
    checklist: ReviewChecklist = Field(default_factory=ReviewChecklist)
    comment: str = Field(default='', max_length=4000)

    @model_validator(mode='after')
    def validate_review(self):
        if self.action in ('return', 'reject') and not self.comment.strip():
            raise ValueError('退回或驳回必须填写意见')
        if self.action == 'approve':
            values = self.checklist.model_dump()
            if any(value != 'pass' for key, value in values.items() if key != 'image_copyright') or values['image_copyright'] not in ('pass', 'not_applicable'):
                raise ValueError('通过前须完成所有检查项；仅图片版权可标记不适用')
        return self


class ReviewOut(BaseModel):
    id: UUID
    article_id: UUID
    article_revision_id: UUID
    action: ReviewAction
    checklist: ReviewChecklist
    comment: str
    reviewer_id: UUID
    created_at: datetime


class ReviewQueueItem(BaseModel):
    article_id: UUID
    article_revision_id: UUID
    version: int = Field(ge=1)
    title: str
    origin_type: ArticleOrigin
    submitted_at: datetime
