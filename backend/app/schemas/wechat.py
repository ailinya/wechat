"""Direct-account and explicitly confirmed publication contracts."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class PublishDefaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    need_open_comment: bool = False
    only_fans_can_comment: bool = False


class AccountIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=128)
    app_id: str = Field(pattern=r'^wx[0-9a-fA-F]{16}$')
    app_secret: SecretStr = Field(min_length=16, max_length=256, json_schema_extra={'writeOnly': True})
    account_type: Literal['subscription', 'service'] = 'subscription'
    publish_permission_confirmed: bool = False
    publish_defaults: PublishDefaults = Field(default_factory=PublishDefaults)


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=128)
    publish_permission_confirmed: bool | None = None
    publish_defaults: PublishDefaults | None = None


class CredentialIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    app_secret: SecretStr = Field(min_length=16, max_length=256, json_schema_extra={'writeOnly': True})


class Capability(BaseModel):
    available: bool
    reason: str


class AccountOut(BaseModel):
    id: UUID
    name: str
    app_id: str
    account_type: str
    connection_mode: Literal['direct'] = 'direct'
    status: Literal['active', 'invalid', 'unbound']
    credential_configured: bool = True
    credential_version: int
    is_default: bool
    publish_permission_confirmed: bool
    publish_defaults: PublishDefaults
    capabilities: dict[str, Capability]
    checked_at: datetime | None
    authorized_at: datetime
    last_synced_at: datetime | None
    error_code: str | None
    created_at: datetime


class SyncOut(BaseModel):
    id: UUID
    account_id: UUID
    async_job_id: UUID | None
    status: str
    imported_count: int
    reused_count: int
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class Accepted(BaseModel):
    async_job_id: UUID | None
    resource_id: UUID
    status: str


class PublishOrderIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    article_revision_id: UUID
    account_id: UUID
    mode: Literal['immediate', 'scheduled'] = 'immediate'
    scheduled_at: datetime | None = None
    publish_note: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def validate_time(self):
        if self.mode == 'scheduled':
            if not self.scheduled_at or not self.scheduled_at.tzinfo or self.scheduled_at <= datetime.now(timezone.utc):
                raise ValueError('定时发布须提供未来的带时区时间')
            self.scheduled_at = self.scheduled_at.astimezone(timezone.utc)
        elif self.scheduled_at is not None:
            raise ValueError('立即发布不能指定定时时间')
        return self


class PublishOrderOut(BaseModel):
    id: UUID
    resource_id: UUID
    article_id: UUID
    article_revision_id: UUID
    account_id: UUID
    mode: str
    scheduled_at: datetime | None
    publish_note: str
    publish_defaults: PublishDefaults
    status: str
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    async_job_id: UUID | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class PublishAttemptOut(BaseModel):
    id: UUID
    order_id: UUID
    attempt_no: int
    status: str
    draft_media_id: str | None
    publish_id: str | None
    article_id_external: str | None
    article_url: str | None
    error_code: str | None
    result: dict
    started_at: datetime
    finished_at: datetime | None
    reconciled_by: UUID | None
    reconciliation_note: str | None


class ReconcileIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['query', 'published', 'not_published'] = 'query'
    note: str = Field(default='', max_length=2000)
    external_article_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode='after')
    def validate_evidence(self):
        if self.outcome != 'query' and not self.note.strip():
            raise ValueError('人工核对必须填写依据')
        if self.outcome == 'published' and not self.external_article_id:
            raise ValueError('已发布核对须提供微信文章 ID')
        return self
