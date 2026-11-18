"""Model configuration contracts (task 3.14; implemented in task 3.16).

Separates analysis / generation / embedding purposes, holds a credential
reference (never the secret itself), a config version and input/output token
budgets. Queries only return whether a credential is configured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.schemas.common import TimestampedModel

ModelPurpose = Literal["analysis", "generation", "embedding"]


class ModelConfigIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64, examples=["openai-compatible"])
    purpose: ModelPurpose = Field(examples=["analysis"])
    endpoint: str = Field(min_length=1, max_length=512)
    model_name: str = Field(min_length=1, max_length=128, examples=["gpt-4o-mini"])
    credential_ref: str | None = Field(
        default=None, max_length=255, description="外部凭据引用标识，非明文"
    )
    enabled: bool = True
    max_input_tokens: int = Field(default=8000, ge=1)
    max_output_tokens: int = Field(default=2000, ge=1)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    params: dict = Field(default_factory=dict)


class ModelConfigOut(TimestampedModel):
    id: UUID
    name: str
    provider: str
    purpose: ModelPurpose
    endpoint: str
    model_name: str
    credential_configured: bool = Field(
        description="仅表示是否已配置凭据，绝不返回明文"
    )
    enabled: bool
    config_version: int = Field(ge=1, examples=[1])
    max_input_tokens: int
    max_output_tokens: int
    timeout_seconds: int
    params: dict


class ModelConnectionTestOut(BaseModel):
    reachable: bool
    latency_ms: int | None = None
    error: str | None = Field(default=None, description="脱敏失败原因")


class ModelConfigUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    credential_ref: str | None = Field(default=None, max_length=255)
    endpoint: str | None = Field(default=None, min_length=1, max_length=512)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)

    @model_validator(mode="after")
    def reject_null_settings(self):
        if any(
            getattr(self, key) is None
            for key in self.model_fields_set - {"credential_ref"}
        ):
            raise ValueError("不修改的配置请省略，配置不能为 null")
        return self
