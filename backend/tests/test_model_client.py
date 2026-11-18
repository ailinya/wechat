"""Unit tests for the model client adapter (task 3.16).

Uses an injected transport so no network or credentials are needed.
"""

from __future__ import annotations

import pytest
import json
from uuid import uuid4

from app.adapters import model_client


def _config(**overrides) -> dict:
    base = {
        "name": "analysis",
        "provider": "openai-compatible",
        "purpose": "analysis",
        "endpoint": "https://example.com/v1",
        "model_name": "m",
        "credential_ref": None,
        "enabled": True,
        "max_input_tokens": 8000,
        "max_output_tokens": 2000,
        "timeout_seconds": 10,
    }
    base.update(overrides)
    return base


def _ok_transport(content: str = "{}", usage: dict | None = None):
    body = {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"total_tokens": 10},
    }
    return lambda endpoint, key, model, messages, timeout: (200, body)


def test_complete_json_success() -> None:
    client = model_client.ModelClient(transport=_ok_transport('{"summary": "ok"}'))
    result = client.complete_json(_config(), "sys", "user")
    assert result["content"] == '{"summary": "ok"}'
    assert result["usage"]["total_tokens"] == 10


def test_disabled_config_rejected_without_network() -> None:
    called = []
    client = model_client.ModelClient(
        transport=lambda *a: called.append(1) or (200, {})
    )
    with pytest.raises(model_client.ModelError) as exc:
        client.complete_json(_config(enabled=False), "sys", "user")
    assert exc.value.code == "model_disabled"
    assert called == []


def test_wrong_purpose_rejected() -> None:
    client = model_client.ModelClient(transport=_ok_transport())
    with pytest.raises(model_client.ModelError) as exc:
        client.complete_json(_config(purpose="embedding"), "sys", "user")
    assert exc.value.code == "model_wrong_purpose"


def test_input_too_large_rejected() -> None:
    client = model_client.ModelClient(transport=_ok_transport())
    with pytest.raises(model_client.ModelError) as exc:
        client.complete_json(_config(max_input_tokens=10), "sys", "x" * 100)
    assert exc.value.code == "input_too_large"


def test_output_over_budget_rejected() -> None:
    client = model_client.ModelClient(
        transport=_ok_transport("{}", {"completion_tokens": 5000, "total_tokens": 6000})
    )
    with pytest.raises(model_client.ModelError) as exc:
        client.complete_json(_config(max_output_tokens=2000), "sys", "user")
    assert exc.value.code == "output_too_large"


def test_retries_then_succeeds() -> None:
    calls = []

    def flaky(endpoint, key, model, messages, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise model_client.ModelError("model_unreachable", "x")
        return 200, {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"total_tokens": 1},
        }

    client = model_client.ModelClient(transport=flaky, max_attempts=2)
    result = client.complete_json(_config(), "sys", "user")
    assert result["content"] == "{}"
    assert len(calls) == 2


def test_analysis_valid_output() -> None:
    content = '{"summary": "摘要", "relevance": "not_applicable", "facts": []}'
    client = model_client.ModelClient(transport=_ok_transport(content))
    result = client.analysis(_config(), "v1", "正文")
    assert result["suggestions"].summary == "摘要"


def test_analysis_requires_verbatim_fact_citations() -> None:
    content = '{"summary":"摘要","relevance":"relevant","facts":[{"statement":"事实","quote":"不存在的原文","ref_index":0}]}'
    client = model_client.ModelClient(transport=_ok_transport(content))
    with pytest.raises(model_client.ModelError) as exc:
        client.analysis(_config(), "v1", "实际正文", topic="主题")
    assert exc.value.code == "invalid_citation"


def test_analysis_marks_relevance_not_applicable_without_context() -> None:
    content = '{"summary":"摘要","relevance":"relevant","facts":[]}'
    client = model_client.ModelClient(transport=_ok_transport(content))
    with pytest.raises(model_client.ModelError) as exc:
        client.analysis(_config(), "v1", "正文")
    assert exc.value.code == "invalid_relevance"


def test_analysis_prompt_contains_topic_and_treats_body_as_untrusted_data() -> None:
    captured = {}

    def transport(endpoint, key, model, messages, timeout):
        captured["user"] = messages[1]["content"]
        captured["system"] = messages[0]["content"]
        return 200, {
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"ok","relevance":"relevant","facts":[]}'
                    }
                }
            ],
            "usage": {},
        }

    result = model_client.ModelClient(transport=transport).analysis(
        _config(), "v1", "body", topic="topic", keywords=["key"]
    )
    assert result["suggestions"].summary == "ok"
    assert '"topic": "topic"' in captured["user"]
    assert "不可信资料" in captured["system"]


def test_analysis_invalid_json() -> None:
    client = model_client.ModelClient(transport=_ok_transport("not json at all"))
    with pytest.raises(model_client.ModelError) as exc:
        client.analysis(_config(), "v1", "正文")
    assert exc.value.code == "invalid_json"


def test_analysis_schema_mismatch() -> None:
    client = model_client.ModelClient(transport=_ok_transport('{"unexpected": true}'))
    with pytest.raises(model_client.ModelError) as exc:
        client.analysis(_config(), "v1", "正文")
    assert exc.value.code == "invalid_output"


def test_credential_resolved_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MY_MODEL_KEY", "secret-value")
    assert model_client.resolve_credential("MY_MODEL_KEY") == "secret-value"
    assert model_client.resolve_credential("MISSING_KEY") is None


@pytest.mark.parametrize("quote", ["原文不存在", " "])
def test_comparison_rejects_invalid_fact_quotes(quote):
    revision_id = str(uuid4())
    output = {
        "summary": "比较",
        "compare_verdict": "new_progress",
        "compare_target_revision_id": revision_id,
        "facts": [{"statement": "新增事实", "quote": quote}],
    }
    client = model_client.ModelClient(
        _ok_transport(json.dumps(output, ensure_ascii=False))
    )
    with pytest.raises(model_client.ModelError) as exc:
        client.compare_progress(
            _config(), "compare/1", "旧正文", "新的真实正文", revision_id
        )
    assert exc.value.code == "invalid_citation"


def test_large_prompt_usage_does_not_count_as_output_budget():
    client = model_client.ModelClient(
        _ok_transport(
            "{}", {"prompt_tokens": 5000, "completion_tokens": 2, "total_tokens": 5002}
        )
    )
    assert client.complete_json(_config(), "sys", "user")["content"] == "{}"


def test_analysis_missing_facts_field_is_rejected():
    client = model_client.ModelClient(
        _ok_transport('{"summary":"摘要","relevance":"not_applicable"}')
    )
    with pytest.raises(model_client.ModelError) as exc:
        client.analysis(_config(), "v1", "正文")
    assert exc.value.code == "invalid_output"


def test_invalid_credential_is_reported_without_retries():
    calls = []

    def transport(*args):
        calls.append(1)
        return 401, {}

    client = model_client.ModelClient(transport=transport, max_attempts=3)
    with pytest.raises(model_client.ModelError) as exc:
        client.complete_json(_config(), "system", "user")
    assert exc.value.code == "model_auth_failed"
    assert len(calls) == 1
