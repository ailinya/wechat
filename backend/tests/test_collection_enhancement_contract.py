"""Contract tests for the collection enhancement (task 3.14).

Validates the two-mode task contract, backward-compatible defaults, partial
update semantics and the analysis/config contracts — all at the schema level
(no database required).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.analysis import AnalysisApplyIn
from app.schemas.collection import (
    CollectionTaskIn,
    CollectionTaskUpdateIn,
    ManualRetentionIn,
)
from app.schemas.model_config import ModelConfigIn, ModelConfigOut
from app.schemas.search_config import SearchConfigIn

SOURCE = uuid4()


def test_old_request_defaults_to_source_mode() -> None:
    task = CollectionTaskIn(name="旧任务", source_ids=[SOURCE])
    assert task.mode == "source"
    assert task.analysis.enabled is False
    assert task.analysis.apply_policy == "suggest_only"
    assert task.max_candidates == 100
    assert task.allowed_domains == []


def test_source_mode_requires_at_least_one_source() -> None:
    with pytest.raises(ValidationError):
        CollectionTaskIn(name="无来源", source_ids=[])


def test_topic_search_without_source_is_legal() -> None:
    task = CollectionTaskIn(name="主题", mode="topic_search", topic="固件更新")
    assert task.source_ids == []
    assert task.topic == "固件更新"


def test_topic_search_with_source_ids_is_conflict() -> None:
    with pytest.raises(ValidationError):
        CollectionTaskIn(name="冲突", mode="topic_search", topic="x", source_ids=[SOURCE])


def test_topic_search_requires_topic() -> None:
    with pytest.raises(ValidationError):
        CollectionTaskIn(name="无主题", mode="topic_search")


def test_update_omitted_fields_are_excluded() -> None:
    update = CollectionTaskUpdateIn(name="改名")
    data = update.model_dump(exclude_unset=True)
    assert data == {"name": "改名"}
    assert "mode" not in data
    assert "analysis" not in data


def test_update_can_set_new_fields() -> None:
    update = CollectionTaskUpdateIn(allowed_domains=["example.com"], max_fetch=30)
    data = update.model_dump(exclude_unset=True)
    assert data["allowed_domains"] == ["example.com"]
    assert data["max_fetch"] == 30


def test_analysis_apply_requires_base_version() -> None:
    apply = AnalysisApplyIn(base_metadata_version=3, apply=["summary"])
    assert apply.base_metadata_version == 3
    with pytest.raises(ValidationError):
        AnalysisApplyIn(apply=["summary"])


def test_manual_retention_requires_reason() -> None:
    retention = ManualRetentionIn(result_id=uuid4(), reason="不确定但需保留")
    assert retention.reason
    with pytest.raises(ValidationError):
        ManualRetentionIn(result_id=uuid4(), reason="")


def test_model_config_never_exposes_credential() -> None:
    incoming = ModelConfigIn(
        name="analysis 模型", provider="openai-compatible", purpose="analysis",
        endpoint="https://example.com/v1", model_name="gpt-4o-mini",
        credential_ref="ref://secret-store/an",
    )
    outgoing_fields = ModelConfigOut.model_fields
    assert "credential_configured" in outgoing_fields
    assert "credential_ref" not in outgoing_fields  # secret reference never serialised


def test_search_config_defaults() -> None:
    config = SearchConfigIn(name="tavily", provider="tavily")
    assert config.enabled is True
    assert config.supports_domain_filter is True
    assert config.max_results == 5
