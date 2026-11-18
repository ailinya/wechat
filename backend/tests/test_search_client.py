from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.search_client import SearchClient, SearchError
from app.adapters.source_fetch import FetchError, fetch
from app.schemas.search_config import SearchConfigIn, SearchConfigUpdateIn
from app.modules.collection.search_policy import build_query, normalize_url


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("TEST_SEARCH_KEY", "fixture-only-secret")
    return {"provider": "tavily", "enabled": True, "credential_ref": "TEST_SEARCH_KEY",
            "max_results": 20, "config_version": 3, "supports_domain_filter": True, "supports_date_filter": True}


def test_fixed_query_normalizes_without_expansion():
    assert build_query(" ＡＩ  新闻 ", ["AI 新闻", "政策", "政策"]) == "AI 新闻 政策"
    with pytest.raises(ValueError):
        build_query(" ", [])
    with pytest.raises(ValueError):
        build_query("x" * 401, [])


def test_domains_and_absolute_dates_are_pre_filters(config):
    calls = []
    def transport(payload):
        calls.append(payload)
        return 200, {"results": [
            {"url": "https://News.Example.com:443/a?k=1#part", "content": "摘要", "published_date": "2026-11-17"},
            {"url": "https://example.com.evil.com/a"},
            {"url": "https://notexample.com/a"},
        ]}
    outcome = SearchClient(transport).search(config, "新闻", allowed_domains=["example.com"],
        window_start=datetime(2026, 11, 11, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 18, tzinfo=timezone.utc))
    assert calls[0]["start_date"] == "2026-11-11"
    assert calls[0]["end_date"] == "2026-11-18"
    assert calls[0]["filter_by_published_date"] is True
    assert calls[0]["include_domains"] == ["example.com"]
    assert calls[0]["include_answer"] is False
    assert len(outcome.candidates) == 1 and len(outcome.filtered) == 2
    assert outcome.candidates[0].normalized_url == "https://news.example.com/a?k=1"
    assert outcome.candidates[0].summary == "摘要"
    assert not hasattr(outcome.candidates[0], "markdown")
    assert outcome.config_version == 3


def test_provider_without_filters_still_enforces_domain(config):
    config.update(supports_domain_filter=False, supports_date_filter=False)
    def transport(payload):
        assert "include_domains" not in payload and "days" not in payload
        return 200, {"results": [{"url": "https://outside.com/a"}]}
    result = SearchClient(transport).search(config, "主题", allowed_domains=["example.com"], days=7)
    assert result.empty and not result.candidates
    assert result.filtered[0]["reason"] == "domain_out_of_scope"


@pytest.mark.parametrize("status,code", [(401,"search_auth_failed"), (403,"search_auth_failed"),
    (402,"search_quota_exhausted"), (432,"search_quota_exhausted"), (433,"search_quota_exhausted"),
    (400,"search_provider_error"), (302,"search_provider_error")])
def test_permanent_errors_do_not_retry_or_echo_provider(config, status, code):
    calls = []
    def transport(payload):
        calls.append(1)
        return status, {"error": "fixture-only-secret"}
    with pytest.raises(SearchError) as error:
        SearchClient(transport).search(config, "主题")
    assert error.value.code == code and error.value.attempts == 1
    assert len(calls) == 1 and "secret" not in str(error.value)


def test_retry_budget_counts_failed_calls(config):
    calls, reservations = [], []
    def transport(payload):
        calls.append(payload["query"])
        return 503, {}
    with pytest.raises(SearchError) as error:
        SearchClient(transport).search(config, "固定主题", remaining_calls=2,
                                       before_attempt=lambda: reservations.append(1))
    assert calls == ["固定主题", "固定主题"] and len(reservations) == 2
    assert error.value.attempts == 2


def test_transient_failure_then_success(config):
    responses = iter([(429, {}), (200, {"results": []})])
    result = SearchClient(lambda _: next(responses)).search(config, "主题")
    assert result.empty and result.attempts == 2


@pytest.mark.parametrize("body", [{}, {"results": None}, {"results": ["bad"]}, {"results": [{}]}, []])
def test_malformed_response_is_not_empty_success(config, body):
    with pytest.raises(SearchError, match="搜索") as error:
        SearchClient(lambda _: (200, body)).search(config, "主题")
    assert error.value.code == "search_invalid_response"


def test_no_calls_without_credentials_or_budget(config, monkeypatch):
    calls = []
    client = SearchClient(lambda p: calls.append(p))
    monkeypatch.delenv("TEST_SEARCH_KEY")
    with pytest.raises(SearchError) as error:
        client.search(config, "主题")
    assert error.value.code == "search_credential_missing"
    monkeypatch.setenv("TEST_SEARCH_KEY", "fixture")
    with pytest.raises(SearchError) as error:
        client.search(config, "主题", remaining_calls=0)
    assert error.value.code == "budget_exhausted"
    assert not calls


def test_result_limit_and_usage(config):
    result = SearchClient(lambda _: (200, {"results": [
        {"url": f"https://example.com/{i}"} for i in range(25)],
        "usage": {"credits": 1, "credential": "secret"}})).search(config, "主题", max_results=2)
    assert len(result.candidates) == 2 and result.usage == {"credits": 1}


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/a", "http://[::1]/",
    "https://user:password@example.com/", "https://example.com:bad/", "http://localhost/"])
def test_unsafe_candidate_is_filtered(config, url):
    result = SearchClient(lambda _: (200, {"results": [{"url": url}]})).search(config, "主题")
    assert result.empty and len(result.filtered) == 1
    assert "password" not in str(result.filtered)


def test_redirect_domain_rechecked_before_second_fetch():
    calls = []
    def transport(url, timeout):
        calls.append(url)
        return 302, {"Location": "https://other.example.org/a"}, b""
    with pytest.raises(FetchError):
        fetch("https://news.example.com/a", allowed_domains=["example.com"],
              resolver=lambda *_: ["8.8.8.8"], transport=transport)
    assert calls == ["https://news.example.com/a"]


def test_url_normalization_preserves_meaningful_query():
    assert normalize_url("https://EXAMPLE.com:443/a?id=2#x") == "https://example.com/a?id=2"


def test_config_partial_update_and_secret_reference():
    assert SearchConfigUpdateIn(enabled=False).model_dump(exclude_unset=True) == {"enabled": False}
    assert SearchConfigUpdateIn(credential_ref=None).model_dump(exclude_unset=True) == {"credential_ref": None}
    with pytest.raises(ValidationError):
        SearchConfigUpdateIn(enabled=None)
    with pytest.raises(ValidationError):
        SearchConfigIn(name="x", provider="tavily", credential_ref="tvly-plaintext-secret")
