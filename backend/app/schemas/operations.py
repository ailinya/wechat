from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReportKind = Literal['collection', 'materials', 'creation', 'reviews', 'publishing', 'accounts']
NotificationCategory = Literal['collection', 'creation', 'review', 'publishing', 'exception']


class PlatformIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(max_length=1000)
    brand_mark: str = Field(min_length=1, max_length=4)
    timezone: str = 'Asia/Shanghai'
    version: int = Field(ge=1)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('请选择有效IANA时区') from None
        return value


class PlatformOut(PlatformIn):
    updated_at: datetime


class PlatformPublic(BaseModel):
    name: str
    description: str
    brand_mark: str
    timezone: str


class ReportFilters(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = 'Asia/Shanghai'
    account_id: UUID | None = None
    collection_task_id: UUID | None = None
    creation_task_id: UUID | None = None

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        return PlatformIn.valid_timezone(value)

    @model_validator(mode='after')
    def interval(self):
        if self.start_date and self.end_date and not 0 < (self.end_date-self.start_date).days <= 366:
            raise ValueError('日期区间须大于0且不超过366天，结束日期不包含在内')
        return self


class MetricValue(BaseModel):
    value: int | None = None
    available: bool
    reason: str = ''


class ReportRow(BaseModel):
    id: str
    title: str
    status: str
    occurred_at: datetime
    source: str
    url: str
    account_id: UUID | None = None
    collection_task_id: UUID | None = None
    creation_task_id: UUID | None = None
    attempts: int = 0
    quantity: int = 1
    reference_count: int = 0
    group_name: str = ''
    reason: str = ''
    collected_at: datetime | None = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)


class ReportSummary(BaseModel):
    total: int
    succeeded: int
    failed: int
    denominator: int
    success_rate: float | None
    attempts: int
    quantity: int
    reused_materials: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    by_group: dict[str, int]
    failure_reasons: dict[str, int]
    definition: str


class TrendPoint(BaseModel):
    day: date
    count: int


class ReportOut(BaseModel):
    kind: ReportKind
    filters: ReportFilters
    items: list[ReportRow]
    total: int
    page: int
    page_size: int
    summary: ReportSummary
    trend: list[TrendPoint]


class DashboardLink(BaseModel):
    id: str
    title: str
    status: str
    url: str
    occurred_at: datetime
    reason: str = ''
    account_names: list[str] = Field(default_factory=list)


class DashboardOut(BaseModel):
    timezone: str
    as_of: datetime
    counters: dict[str, int | None]
    recent_articles: list[DashboardLink]
    activity: list[DashboardLink]
    todos: list[DashboardLink]
    alerts: list[DashboardLink]


class NotificationOut(BaseModel):
    id: UUID
    category: NotificationCategory
    title: str
    body: str
    url: str
    occurred_at: datetime
    created_at: datetime
    read_at: datetime | None


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: NotificationCategory
    channel: Literal['in_app'] = 'in_app'
    enabled: bool


class PreferenceOut(PreferenceIn):
    updated_at: datetime | None = None


class NotificationChannels(BaseModel):
    in_app: bool = True
    email: bool = False
    wechat: bool = False
    reason: str = '本期支持站内通知；邮件和微信外发未接入'


class OperationLogOut(BaseModel):
    id: UUID
    user_id: UUID | None
    user_name: str | None
    action: str
    object_type: str
    object_id: UUID | None
    result: str
    detail: dict
    created_at: datetime


class MonitoredJobOut(BaseModel):
    id: UUID
    job_type: str
    resource_type: str
    resource_id: UUID
    status: str
    stage: str | None
    progress: int
    attempts: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class IntegrationOut(BaseModel):
    id: str
    name: str
    configured: bool
    management_url: str
    description: str


class ConnectionOut(BaseModel):
    reachable: bool
    reason: str


class MetricCollectionIn(BaseModel):
    metric_date: date


class RuntimeOut(BaseModel):
    stale_running_jobs:int
    stale_pending_jobs:int
    pending_outbox:int
    failed_outbox:int
    unknown_publications:int
    unknown_drafts:int


class RuntimeRecoveryOut(RuntimeOut):
    reaped:int
    recovered_pending:int


class OutboxOut(BaseModel):
    id:UUID
    event_type:str
    aggregate_type:str
    aggregate_id:UUID
    status:Literal['pending','dispatched','failed']
    attempts:int
    available_at:datetime
    created_at:datetime


class OutboxRetryOut(BaseModel):
    id:UUID
    status:Literal['pending']
    async_job_id:UUID
