"""Search service configuration contracts (task 3.14; implemented in task 3.17).

Independent of collection sources and embedding config. Credentials are kept
as an external reference; queries only return whether they are configured.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import TimestampedModel

SearchProvider = Literal["tavily"]


class SearchConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=128)
    provider: SearchProvider = Field(examples=["tavily"])
    credential_ref: str | None = Field(default=None, max_length=255, pattern=r"^[A-Z][A-Z0-9_]*$", description="环境变量名，非明文密钥")
    enabled: bool = True
    max_results: int = Field(default=5, ge=1, le=20)
    supports_domain_filter: bool = True
    supports_date_filter: bool = True


class SearchConfigUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    credential_ref: str | None = Field(default=None, max_length=255, pattern=r"^[A-Z][A-Z0-9_]*$")
    enabled: bool | None = None
    max_results: int | None = Field(default=None, ge=1, le=20)
    supports_domain_filter: bool | None = None
    supports_date_filter: bool | None = None

    @model_validator(mode="after")
    def reject_null_settings(self):
        if any(getattr(self, key) is None for key in self.model_fields_set - {"credential_ref"}):
            raise ValueError("配置字段不能为 null；不修改的字段请省略")
        return self


class SearchConfigOut(TimestampedModel):
    id: UUID
    name: str
    provider: SearchProvider
    credential_configured: bool = Field(description="仅表示是否已配置凭据，绝不返回明文")
    enabled: bool
    config_version: int = Field(ge=1, examples=[1])
    max_results: int
    supports_domain_filter: bool
    supports_date_filter: bool


class SearchConnectionTestOut(BaseModel):
    reachable: bool
    latency_ms: int | None = None
    error: str | None = Field(default=None, description="脱敏失败原因")
    error_code: str | None = None


class SearchCandidateOut(BaseModel):
    """A discovered web candidate from the search service (task 3.17)."""

    url: str
    title: str = ""
    summary: str = Field(default="", description="搜索摘要，仅作发现依据，不是正文")
    provider_rank: int = Field(ge=1, examples=[1])
    provider_published_at: str | None = None
