"""Bounded Tavily search. Snippets are discovery evidence, never article bodies."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.modules.collection.search_policy import normalize_domain, normalize_url
from app.credentials import resolve_credential

Transport = Callable[[dict], tuple[int, dict]]


class SearchError(Exception):
    def __init__(
        self, code: str, message: str, *, attempts: int = 0, retryable: bool = False
    ):
        self.code, self.message = code, message
        self.attempts, self.retryable = attempts, retryable
        super().__init__(message)


@dataclass
class SearchCandidate:
    url: str
    title: str = ""
    summary: str = ""
    provider_rank: int = 1
    provider_published_at: str | None = None
    score: float | None = None
    normalized_url: str = ""


@dataclass
class SearchOutcome:
    candidates: list[SearchCandidate] = field(default_factory=list)
    query: str = ""
    config_version: int = 1
    latency_ms: int = 0
    attempts: int = 0
    empty: bool = False
    filtered: list[dict] = field(default_factory=list)
    request_id: str | None = None
    usage: dict | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(payload: dict) -> tuple[int, dict]:
    body = dict(payload)
    key = body.pop("api_key")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(
            request, timeout=30
        ) as response:
            raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise SearchError("search_response_too_large", "搜索响应超过限制")
            return response.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never read or log provider error bodies: they can echo credentials.
        return exc.code, {}
    except (TimeoutError, urllib.error.URLError, OSError):
        raise SearchError(
            "search_unreachable", "搜索服务连接失败或超时", retryable=True
        ) from None
    except (ValueError, UnicodeError):
        raise SearchError(
            "search_invalid_response", "搜索服务未返回有效 JSON"
        ) from None


def _http_error(status: int) -> SearchError:
    if status in (401, 403):
        return SearchError("search_auth_failed", "搜索凭据无效或无权限")
    if status in (402, 432, 433):
        return SearchError("search_quota_exhausted", "搜索服务额度不足")
    if status == 429:
        return SearchError(
            "search_rate_limited", "搜索服务请求过于频繁", retryable=True
        )
    return SearchError(
        "search_provider_error", f"搜索服务返回 HTTP {status}", retryable=status >= 500
    )


class SearchClient:
    def __init__(self, transport: Transport | None = None, max_attempts: int = 3):
        self._transport = transport or _default_transport
        self._max_attempts = min(3, max(1, max_attempts))

    def search(
        self,
        config: dict,
        query: str,
        *,
        allowed_domains: list[str] | None = None,
        days: int | None = None,
        max_results: int | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        remaining_calls: int = 3,
        before_attempt: Callable[[], None] | None = None,
    ) -> SearchOutcome:
        if not config.get("enabled"):
            raise SearchError("search_disabled", "搜索配置已禁用")
        if config.get("provider") != "tavily":
            raise SearchError("search_unsupported", "不支持的搜索提供方")
        key = resolve_credential(config.get("credential_ref"))
        if not key:
            raise SearchError("search_credential_missing", "搜索凭据未配置")
        if not query.strip() or len(query) > 400:
            raise SearchError("search_invalid_query", "搜索词须为 1–400 字符")
        try:
            domains = [normalize_domain(item) for item in allowed_domains or []]
        except ValueError:
            raise SearchError("search_invalid_domains", "网站范围配置不合法") from None
        limit = min(
            20,
            int(config.get("max_results", 5)),
            max_results if max_results is not None else 20,
        )
        if limit < 1 or remaining_calls < 1:
            raise SearchError("budget_exhausted", "搜索预算已耗尽")
        if bool(window_start) != bool(window_end) or (
            window_start
            and (
                window_start.utcoffset() is None
                or window_end.utcoffset() is None
                or window_start > window_end
            )
        ):
            raise SearchError(
                "search_invalid_window", "搜索时间窗口必须为明确的起止时间"
            )
        payload: dict[str, Any] = {
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "topic": "news",
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": False,
            "auto_parameters": False,
            "include_usage": True,
        }
        if domains and config.get("supports_domain_filter"):
            payload["include_domains"] = domains
        if config.get("supports_date_filter"):
            if window_start:
                payload["start_date"] = (
                    window_start.astimezone(timezone.utc).date().isoformat()
                )
                payload["end_date"] = (
                    window_end.astimezone(timezone.utc).date().isoformat()
                )
                payload["filter_by_published_date"] = True
            elif days:
                payload["days"] = days
        started = time.monotonic()
        attempts = 0
        for _ in range(min(self._max_attempts, remaining_calls)):
            if before_attempt:
                # Caller durably reserves this call before any network activity.
                before_attempt()
            attempts += 1
            try:
                status, body = self._transport(payload)
                if not 200 <= status < 300:
                    raise _http_error(status)
                candidates, filtered = _extract(body, domains, limit)
                usage = body.get("usage")
                safe_usage = None
                if isinstance(usage, dict):
                    safe_usage = {
                        k: v
                        for k, v in usage.items()
                        if k == "credits" and type(v) in (int, float) and v >= 0
                    }
                return SearchOutcome(
                    candidates=candidates,
                    query=query,
                    config_version=int(config.get("config_version", 1)),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    attempts=attempts,
                    empty=not candidates,
                    filtered=filtered,
                    request_id=body.get("request_id")
                    if isinstance(body.get("request_id"), str)
                    else None,
                    usage=safe_usage or None,
                )
            except SearchError as exc:
                exc.attempts = attempts
                if not exc.retryable or attempts == min(
                    self._max_attempts, remaining_calls
                ):
                    raise
            except (TimeoutError, OSError):
                if attempts == min(self._max_attempts, remaining_calls):
                    raise SearchError(
                        "search_unreachable",
                        "搜索服务连接失败或超时",
                        attempts=attempts,
                    ) from None
            time.sleep(0.1 * attempts)
        raise AssertionError("unreachable")


def _extract(
    body: Any, domains: list[str], limit: int
) -> tuple[list[SearchCandidate], list[dict]]:
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise SearchError("search_invalid_response", "搜索响应缺少有效 results")
    candidates, filtered = [], []
    for rank, raw in enumerate(body["results"][:limit], 1):
        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
            raise SearchError("search_invalid_response", "搜索候选缺少有效链接")
        url = raw["url"].strip()
        try:
            normalized = normalize_url(url, domains)
        except ValueError as exc:
            # Retain a reason and rank, never a URL containing user credentials.
            item = {"provider_rank": rank, "reason": str(exc)}
            try:
                parsed_url = urllib.parse.urlsplit(url)
                if parsed_url.username is None and parsed_url.password is None:
                    item["url"] = normalize_url(url)
            except ValueError:
                pass
            filtered.append(item)
            continue

        def text_field(name: str, size: int) -> str:
            value = raw.get(name)
            return value[:size] if isinstance(value, str) else ""

        candidates.append(
            SearchCandidate(
                url=url,
                normalized_url=normalized,
                title=text_field("title", 512),
                summary=text_field("content", 4000) or text_field("snippet", 4000),
                provider_rank=rank,
                provider_published_at=text_field("published_date", 128) or None,
                score=raw.get("score")
                if type(raw.get("score")) in (int, float)
                else None,
            )
        )
    return candidates, filtered
