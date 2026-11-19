from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DraftDeliveryIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    article_revision_id: UUID
    account_id: UUID
    confirm_sync: Literal[True]
    note: str = Field(default='', max_length=2000)


class DraftDeliveryOut(BaseModel):
    id: UUID
    resource_id: UUID
    article_id: UUID
    article_revision_id: UUID
    account_id: UUID
    status: str
    note: str
    async_job_id: UUID | None
    remote_media_id: str | None
    error_code: str | None
    confirmed_by: UUID
    confirmed_at: datetime
    publication_source: Literal['operator'] | None
    manual_published_by: UUID | None
    manual_published_at: datetime | None
    manual_article_url: str | None
    manual_note: str | None
    created_at: datetime
    updated_at: datetime


class DraftAttemptOut(BaseModel):
    id: UUID
    delivery_id: UUID
    attempt_no: int
    status: str
    remote_media_id: str | None
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None
    reconciled_by: UUID | None
    reconciliation_note: str | None


class DraftReconcileIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['query', 'not_synced'] = 'query'
    note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def evidence(self):
        if self.outcome == 'not_synced' and not self.note.strip():
            raise ValueError('确认未同步须填写微信后台核对依据')
        return self


class ManualPublicationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content_matches_revision: Literal[True]
    article_url: str = Field(max_length=2000)
    note: str = Field(min_length=1, max_length=2000)

    @field_validator('article_url')
    @classmethod
    def wechat_url(cls, value):
        try:
            url = urlsplit(value)
            if url.scheme == 'https' and url.hostname == 'mp.weixin.qq.com' and url.username is None and url.password is None and url.port in (None, 443) and url.path not in ('', '/') and not any(c.isspace() for c in value):
                return value
        except ValueError:
            pass
        raise ValueError('请填写 https://mp.weixin.qq.com/ 开头的微信文章链接')

    @field_validator('note')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('请填写人工发布说明')
        return value.strip()
