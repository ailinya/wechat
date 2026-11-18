"""Bounded RSS, article and configured HTML-list discovery."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

from app.adapters import source_fetch
from app.modules.collection.search_policy import normalize_url


class DiscoveryError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass
class Discovery:
    kind: str
    discovery_url: str
    page_number: int
    provenance_key: str
    external_id: str | None = None
    title: str = ""
    published_evidence: str | None = None


@dataclass
class ArticleCandidate:
    url: str
    normalized_url: str
    title: str = ""
    published_at: str | None = None
    discoveries: list[Discovery] = field(default_factory=list)


@dataclass
class SourceDiscovery:
    candidates: list[ArticleCandidate] = field(default_factory=list)
    pages_visited: int = 0
    stop_reason: str = "completed"
    filtered_count: int = 0


def _published(entry) -> tuple[str | None, str | None]:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            stamp = datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            return stamp, entry.get("published") or entry.get("updated")
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                parsed = parsedate_to_datetime(raw)
                if parsed.tzinfo is not None:
                    return parsed.astimezone(timezone.utc).isoformat(), raw
            except (TypeError, ValueError, OverflowError):
                pass
            return None, raw[:512]
    return None, None


def _safe_link(link: str, page_url: str, domains: list[str], resolver) -> tuple[str, str]:
    target = urljoin(page_url, link.strip())
    try:
        normalized = normalize_url(target, domains or None)
        source_fetch.validate_url(normalized, resolver=resolver)
    except (ValueError, source_fetch.FetchError):
        raise DiscoveryError("unsafe_discovered_url", "发现的文章链接不符合公网或网站范围限制") from None
    return target, normalized


def _append(result: SourceDiscovery, items: dict, *, url: str, title: str,
            published_at: str | None, discovery: Discovery, page_url: str,
            domains: list[str], resolver, max_candidates: int) -> bool:
    target, normalized = _safe_link(url, page_url, domains, resolver)
    candidate = items.get(normalized)
    if candidate is None:
        if len(items) >= max_candidates:
            return False
        candidate = ArticleCandidate(target, normalized, title[:512], published_at)
        items[normalized] = candidate
        result.candidates.append(candidate)
    elif not candidate.title and title:
        candidate.title = title[:512]
    if discovery not in candidate.discoveries:
        candidate.discoveries.append(discovery)
    return True


def discover_source(source: dict, *, allowed_domains: list[str] | None = None,
                    max_candidates: int = 100, max_pages: int = 5,
                    fetcher=None, resolver=None) -> SourceDiscovery:
    """Return unique article links plus each RSS/list/article provenance.

    Fetching is bounded by max_pages; each link is normalized, public-address
    checked, and optionally constrained to allowed_domains. No entry body or
    summary is treated as article text.
    """
    if not 1 <= max_candidates <= 100 or not 1 <= max_pages <= 20:
        raise DiscoveryError("invalid_discovery_limit", "发现数量或分页上限超出允许范围")
    source_id = str(source.get("id") or "")
    kind = source.get("source_type")
    page_kind = source.get("page_kind") or "article"
    base_url = source.get("base_url", "")
    domains = allowed_domains or []
    resolver = resolver or source_fetch._default_resolver
    fetcher = fetcher or (lambda url: source_fetch.fetch(url, resolver=resolver, allowed_domains=domains or None))
    try:
        if kind == "web_page" and page_kind == "article":
            target, normalized = _safe_link(base_url, base_url, domains, resolver)
            item = ArticleCandidate(target, normalized, source.get("name", "")[:512])
            item.discoveries.append(Discovery("article", target, 1,
                hashlib.sha256((source_id + target).encode()).hexdigest(), title=item.title))
            return SourceDiscovery([item], 0, "article_source")
        if kind not in ("rss", "web_page"):
            raise DiscoveryError("unsupported_source_type", "不支持的采集来源类型")
        if kind == "web_page" and not source.get("article_link_selector"):
            raise DiscoveryError("list_selector_required", "栏目页必须配置文章链接 CSS 选择器")
        if kind == "web_page" and page_kind != "list":
            raise DiscoveryError("unsupported_page_kind", "网页来源类型配置无效")

        result, items = SourceDiscovery(), {}
        page_url, visited = base_url, set()
        for page_number in range(1, (1 if kind == "rss" else max_pages) + 1):
            try:
                _, normalized_page = _safe_link(page_url, page_url, domains, resolver)
            except DiscoveryError:
                if page_number == 1:
                    raise
                result.stop_reason = "next_page_out_of_scope"
                break
            if normalized_page in visited:
                result.stop_reason = "pagination_cycle"
                break
            visited.add(normalized_page)
            response = fetcher(page_url)
            result.pages_visited += 1
            if not 200 <= response.status_code < 300:
                raise DiscoveryError("source_http_error", f"来源返回 HTTP {response.status_code}")
            effective_url = response.final_url or page_url
            try:
                normalized_page = normalize_url(effective_url, domains or None)
                source_fetch.validate_url(normalized_page, resolver=resolver)
            except (ValueError, source_fetch.FetchError):
                raise DiscoveryError("unsafe_final_url", "来源重定向目标不符合公网或网站范围限制") from None

            if kind == "rss":
                parsed = feedparser.parse(response.content.encode("utf-8"))
                if not parsed.entries and (getattr(parsed, "bozo", False) or not parsed.version):
                    raise DiscoveryError("invalid_feed", "来源不是可解析的 RSS/Atom feed")
                for index, entry in enumerate(parsed.entries, start=1):
                    link = entry.get("link")
                    if not link:
                        continue
                    published_at, evidence = _published(entry)
                    external_id = entry.get("id") or entry.get("guid")
                    key = str(external_id or f"{index}:{link}")[:2048]
                    try:
                        accepted = _append(result, items, url=link, title=entry.get("title", ""),
                        published_at=published_at, page_url=effective_url, domains=domains,
                                resolver=resolver, max_candidates=max_candidates,
                                discovery=Discovery("rss", normalized_page, 1,
                                    hashlib.sha256(key.encode()).hexdigest(), str(external_id)[:2048] if external_id else None,
                                    str(entry.get("title", ""))[:512], evidence))
                    except DiscoveryError:
                        result.filtered_count += 1
                        continue
                    if not accepted:
                        result.stop_reason = "candidate_limit"
                    elif len(result.candidates) >= max_candidates:
                        result.stop_reason = "candidate_limit"
                if getattr(parsed, "bozo", False) and result.candidates:
                    result.stop_reason = "feed_partial"
                break

            soup = BeautifulSoup(response.content, "html.parser")
            try:
                links = soup.select(source["article_link_selector"])
                next_link = soup.select_one(source["next_page_selector"]) if source.get("next_page_selector") else None
            except SelectorSyntaxError:
                raise DiscoveryError("invalid_css_selector", "栏目页 CSS 选择器语法无效") from None
            if not links:
                result.stop_reason = "no_article_links"
            for index, element in enumerate(links, start=1):
                href = element.get("href")
                if not href:
                    continue
                title = element.get_text(" ", strip=True)
                key = f"{page_number}:{index}:{href}"
                try:
                    accepted = _append(result, items, url=href, title=title, published_at=None,
                            page_url=effective_url, domains=domains, resolver=resolver,
                            max_candidates=max_candidates,
                            discovery=Discovery("list", normalized_page, page_number,
                                hashlib.sha256(key.encode()).hexdigest(), title=title[:512]))
                except DiscoveryError:
                    result.filtered_count += 1
                    continue
                if not accepted:
                    result.stop_reason = "candidate_limit"
                elif len(result.candidates) >= max_candidates:
                    result.stop_reason = "candidate_limit"
            if result.stop_reason == "candidate_limit" or page_number == max_pages:
                if page_number == max_pages and next_link and result.stop_reason != "candidate_limit":
                    result.stop_reason = "page_limit"
                break
            href = next_link.get("href") if next_link else None
            if not href:
                break
            next_url = urljoin(effective_url, href)
            try:
                next_norm = normalize_url(next_url, domains or None)
                source_fetch.validate_url(next_norm, resolver=resolver)
            except (ValueError, source_fetch.FetchError):
                result.stop_reason = "next_page_out_of_scope"
                break
            if next_norm in visited:
                result.stop_reason = "pagination_cycle"
                break
            page_url = next_url
        return result
    except source_fetch.FetchError:
        raise DiscoveryError("source_fetch_failed", "采集来源连接失败") from None
