from dataclasses import dataclass

import pytest

from app.adapters.source_fetch import FetchError, FetchResult
from app.modules.collection.article_discovery import DiscoveryError, discover_source

PUBLIC = "93.184.216.34"


@dataclass
class Response:
    final_url: str
    status_code: int
    content: str
    content_type: str = "application/rss+xml"


def resolver(*_):
    return [PUBLIC]


def response(url, body, status=200, content_type="text/html"):
    return FetchResult(url, status, body, content_type, 1)


def rss_source(url="https://example.com/feed"):
    return {"id": "source-1", "name": "测试 feed", "source_type": "rss", "base_url": url}


def test_rss_discovers_multiple_articles_and_keeps_duplicate_provenance():
    body = '''<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
      <item><title>第一篇</title><link>/a?id=1#x</link><guid>one</guid><pubDate>Tue, 17 Nov 2026 12:00:00 +0800</pubDate></item>
      <item><title>第一篇转载条目</title><link>https://EXAMPLE.com/a?id=1#y</link><guid>duplicate</guid></item>
      <item><title>第二篇</title><link>/b</link><guid>two</guid></item>
      <item><title>越界</title><link>https://example.com.evil.org/steal</link></item>
    </channel></rss>'''
    result = discover_source(rss_source(), allowed_domains=["example.com"],
        fetcher=lambda url: response(url, body, content_type="application/rss+xml"), resolver=resolver)
    assert len(result.candidates) == 2
    first = result.candidates[0]
    assert first.normalized_url == "https://example.com/a?id=1"
    assert first.title == "第一篇"
    assert first.published_at == "2026-11-17T04:00:00+00:00"
    assert len(first.discoveries) == 2
    assert all(item.kind == "rss" for item in first.discoveries)
    assert result.filtered_count == 1
    assert result.pages_visited == 1


def test_rss_candidate_limit_deduplicates_before_stopping():
    body = '''<rss><channel>
      <item><title>A</title><link>/a#1</link></item>
      <item><title>A</title><link>/a#2</link></item>
      <item><title>B</title><link>/b</link></item>
    </channel></rss>'''
    result = discover_source(rss_source(), max_candidates=1,
        allowed_domains=["example.com"], fetcher=lambda url: response(url, body, content_type="application/rss+xml"), resolver=resolver)
    assert len(result.candidates) == 1
    assert len(result.candidates[0].discoveries) == 2
    assert result.stop_reason == "candidate_limit"


def test_invalid_feed_and_site_challenge_are_not_successful_empty_results():
    with pytest.raises(DiscoveryError) as error:
        discover_source(rss_source(), fetcher=lambda url: response(url, "<html>challenge</html>"), resolver=resolver)
    assert error.value.code == "invalid_feed"


def test_source_http_errors_are_explicit():
    with pytest.raises(DiscoveryError) as error:
        discover_source(rss_source(), fetcher=lambda url: response(url, "", status=403), resolver=resolver)
    assert error.value.code == "source_http_error"


def test_article_source_is_direct_candidate_without_fetch():
    source = {"id": "article", "name": "文章", "source_type": "web_page",
              "page_kind": "article", "base_url": "https://example.com/a"}
    result = discover_source(source, fetcher=lambda _: pytest.fail("article URLs are not discovery pages"), resolver=resolver)
    assert result.candidates[0].url == "https://example.com/a"
    assert result.candidates[0].discoveries[0].kind == "article"
    assert result.pages_visited == 0


def list_source(url="https://example.com/news/page-1"):
    return {"id": "list-1", "name": "新闻栏目", "source_type": "web_page", "page_kind": "list",
            "base_url": url, "article_link_selector": "main .article a[href]",
            "next_page_selector": "a.next[href]"}


def test_list_page_uses_configured_css_and_resolves_links():
    html = '''<main><div class="article"><a href="/a">文章 A</a></div>
      <a href="/ignored">侧栏链接</a><a class="next" href="page-2">下一页</a></main>'''
    result = discover_source(list_source(), fetcher=lambda url: response(url, html), resolver=resolver)
    assert [candidate.normalized_url for candidate in result.candidates] == ["https://example.com/a"]
    assert result.candidates[0].title == "文章 A"
    assert result.candidates[0].discoveries[0].page_number == 1
    assert result.stop_reason == "pagination_cycle"


def test_list_pages_are_bounded_and_cycle_detection_stops():
    first = "<main><div class='article'><a href='/a'>A</a></div><a class='next' href='/page2'>Next</a></main>"
    second = "<main><div class='article'><a href='/b'>B</a></div><a class='next' href='/page1'>Next</a></main>"
    pages = {"https://example.com/news/page-1": first,
             "https://example.com/page2": second,
             "https://example.com/page1": first}
    result = discover_source(list_source(), max_pages=5,
        fetcher=lambda url: response(url, pages[url]), resolver=resolver)
    assert result.pages_visited == 3
    assert result.stop_reason == "pagination_cycle"
    assert [x.normalized_url for x in result.candidates] == ["https://example.com/a", "https://example.com/b"]
    assert [d.page_number for d in result.candidates[0].discoveries] == [1, 3]
    assert [d.page_number for d in result.candidates[1].discoveries] == [2]


def test_list_page_limit_and_invalid_selectors_are_reported():
    html = "<a class='article' href='/a'>A</a><a class='next' href='/page2'>Next</a>"
    result = discover_source(list_source(), max_pages=1,
        fetcher=lambda url: response(url, html), resolver=resolver)
    assert result.pages_visited == 1 and result.stop_reason == "page_limit"
    with pytest.raises(DiscoveryError) as error:
        discover_source({**list_source(), "article_link_selector": "["},
                        fetcher=lambda url: response(url, html), resolver=resolver)
    assert error.value.code == "invalid_css_selector"


def test_list_rejects_out_of_domain_next_page_and_filters_private_articles():
    html = "<main><div class='article'><a href='http://127.0.0.1/private'>内网</a></div><a class='next' href='https://other.org/p'>Next</a></main>"
    result = discover_source(list_source(), allowed_domains=["example.com"], max_pages=5,
        fetcher=lambda url: response(url, html), resolver=resolver)
    assert not result.candidates and result.filtered_count == 1
    assert result.stop_reason == "next_page_out_of_scope"


@pytest.mark.parametrize("limit,pages", [(0, 5), (101, 5), (2, 21)])
def test_discovery_rejects_unbounded_limits(limit, pages):
    with pytest.raises(DiscoveryError) as error:
        discover_source(rss_source(), max_candidates=limit, max_pages=pages)
    assert error.value.code == "invalid_discovery_limit"
