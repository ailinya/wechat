"""Input and validated model-output contracts for assisted workflows."""
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field
from app.schemas.materials import MaterialSearchIn


class TopicRequest(BaseModel):
    material_ids: list[UUID] = Field(min_length=1, max_length=20)
    model_config_id: UUID


class TopicEvidence(BaseModel):
    material_id: UUID
    quote: str = Field(min_length=1, max_length=500)


class TopicCandidate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=1000)
    evidence: list[TopicEvidence] = Field(min_length=1, max_length=20)


class TopicOutput(BaseModel):
    candidates: list[TopicCandidate] = Field(max_length=10)


class EnhancedSearchRequest(MaterialSearchIn):
    expand_relations: bool = False


class QualityRequest(BaseModel):
    revision_id: UUID
    model_config_id: UUID


class QualityEvidence(BaseModel):
    article_quote: str = Field(min_length=1, max_length=500)
    material_id: UUID | None = None
    source_quote: str | None = Field(default=None, max_length=500)


class QualityIssue(BaseModel):
    category: Literal['facts', 'sources', 'structure']
    advice: str = Field(min_length=1, max_length=1000)
    limitation: str = Field(min_length=1, max_length=1000)
    evidence: QualityEvidence


class QualityOutput(BaseModel):
    suggestions: list[QualityIssue] = Field(max_length=20)
