"""LLM analysis contracts (task 3.14).

Covers per-result/per-material analysis results, retry and manual adoption.
The apply payload carries a base metadata version so adoption is guarded by
optimistic concurrency: a stale base version must yield a 409 conflict.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampedModel

AnalysisStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
Relevance = Literal["relevant", "irrelevant", "uncertain", "not_applicable"]
CompareVerdict = Literal["duplicate", "new_progress", "distinct", "uncertain"]


class AnalysisFact(BaseModel):
    """A key fact with its verbatim citation in the source body."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=1, max_length=2000, description="原文引用片段")
    ref_index: int = Field(default=0, ge=0)


class AnalysisCategoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID | None = None
    name: str | None = Field(default=None, max_length=64)
    exists: bool = True


class AnalysisSuggestionOut(BaseModel):
    """Structured, schema-validated suggestions. Never applied automatically."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(default="", max_length=4000)
    category_candidates: list[AnalysisCategoryCandidate] = []
    tag_suggestions: list[str] = Field(default_factory=list, max_length=20)
    relevance: Relevance = "not_applicable"
    relevance_reason: str = Field(default="", max_length=2000)
    facts: list[AnalysisFact] = []
    compare_verdict: CompareVerdict | None = None
    compare_target_revision_id: UUID | None = None


class AnalysisResultOut(TimestampedModel):
    id: UUID
    scope: Literal["collection_result", "material_revision"] = "collection_result"
    result_id: UUID | None = None
    material_id: UUID | None = None
    material_revision_id: UUID | None = None
    status: AnalysisStatus = Field(examples=["succeeded"])
    stale: bool = Field(
        default=False, description="正文版本已变化，结果不能作为当前结果应用"
    )
    model_config_id: UUID | None = None
    prompt_version: str = Field(default="", max_length=64)
    suggestions: AnalysisSuggestionOut | None = None
    attempt: int = 1
    usage: dict | None = None
    error: str | None = None
    finished_at: datetime | None = None
    input_snapshot_id: UUID | None = None
    input_hash: str | None = None
    model_config_version: int | None = None
    target_revision_id: UUID | None = None
    purpose: Literal["analysis", "compare"] = "analysis"


class AnalysisApplyIn(BaseModel):
    """Adopt suggestions into a material; base_metadata_version guards concurrency.

    Mismatched base_metadata_version yields 409 (conflict), never a silent
    overwrite of edits made while analysis was running.
    """

    base_metadata_version: int = Field(ge=1, examples=[3])
    apply: list[Literal["summary", "category", "tags"]] = Field(min_length=1)
    confirmed_categories: list[UUID] = []
    confirmed_tags: list[UUID] = []


class AnalysisRetryOut(BaseModel):
    analysis_id: UUID
    status: Literal["accepted"] = "accepted"
    async_job_id: UUID | None = None


class MaterialAnalysisIn(BaseModel):
    model_config_id: UUID
    topic: str | None = Field(default=None, max_length=256)
    keywords: list[str] = Field(default_factory=list, max_length=20)
