from datetime import datetime, timezone

import pytest

from app.services.article_extraction_service import extract_article

STARTED = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def _html(*, date_value='2026-11-17T08:00:00Z', title="AI 行业新闻"):
    date_meta = (f'<meta property="article:published_time" content="{date_value}">' if date_value else "")
    return f"""<!doctype html><html><head><title>AI 行业新闻</title>
    <meta name="description" content="站点栏目介绍">{date_meta}</head>
    <body><nav>首页 导航 联系我们</nav><article><h1>{title}</h1>
    <p>这是一篇关于 AI 行业进展的完整新闻正文，包含足够的事实内容供读者阅读。</p>
    <p>正文继续介绍了产品发布、行业变化和相关背景信息。</p></article>
    <footer>版权声明 订阅我们</footer></body></html>"""


def test_extracts_article_without_navigation_and_keeps_title_date_and_version():
    result = extract_article(
        _html(), url="https://example.com/article", run_started_at=STARTED,
        time_range_days=7, keywords=["ＡＩ 行业"],
    )
    assert result.status == "parsed"
    assert result.title == "AI 行业新闻"
    assert "完整新闻正文" in result.markdown
    assert "首页 导航" not in result.markdown
    assert "版权声明" not in result.markdown
    assert result.published_at == datetime(2026, 11, 17, 8, tzinfo=timezone.utc)
    assert len(result.content_hash) == 64
    assert result.extractor_version.startswith("trafilatura/")


def test_old_article_is_filtered_against_frozen_run_window():
    result = extract_article(
        _html(date_value="2026-11-01T08:00:00Z"), url="https://example.com/old",
        run_started_at=STARTED, time_range_days=7,
    )
    assert (result.status, result.reason) == ("filtered", "outside_time_window")


@pytest.mark.parametrize(
    ("html_date", "provider_date", "expected"),
    [(None, None, "date_unknown"), ("2026-11-17T08:00:00Z", "2026-11-16T08:00:00Z", "date_conflict")],
)
def test_unknown_or_conflicting_date_requires_review(html_date, provider_date, expected):
    result = extract_article(
        _html(date_value=html_date), url="https://example.com/uncertain",
        provider_published_at=provider_date, run_started_at=STARTED, time_range_days=7,
    )
    assert (result.status, result.reason) == ("review_required", expected)


def test_nonmatching_keyword_is_filtered():
    result = extract_article(
        _html(), url="https://example.com/article", run_started_at=STARTED,
        time_range_days=7, keywords=["新能源"],
    )
    assert (result.status, result.reason) == ("filtered", "keyword_mismatch")


def test_http_error_and_unreadable_dynamic_page_fail_explicitly():
    http_error = extract_article(
        "<html>blocked</html>", url="https://example.com/a", status_code=403,
        run_started_at=STARTED, time_range_days=7,
    )
    dynamic = extract_article(
        "<html><head><title>JS page</title></head><body><div id='app'></div></body></html>",
        url="https://example.com/js", run_started_at=STARTED, time_range_days=7,
    )
    assert (http_error.status, http_error.error_code) == ("failed", "http_error")
    assert dynamic.status == "failed"


def test_search_summary_is_not_accepted_as_article_body():
    result = extract_article(
        "", url="https://example.com/a", content_type="text/plain",
        run_started_at=STARTED, time_range_days=7,
    )
    assert result.status == "failed"


def test_js_polluted_metadata_title_falls_back_to_clean_html_title():
    html = _html().replace(
        "<title>AI 行业新闻</title>",
        "<title>干净标题</title><meta property='og:title' content=\"var title1 = '污染标题'\">",
    )
    result = extract_article(
        html, url="https://example.com/article", run_started_at=STARTED,
        time_range_days=7,
    )
    assert result.title == "干净标题"


def test_description_only_extraction_is_rejected():
    html = """<html><head><title>栏目</title>
    <meta name="description" content="站点栏目介绍"></head>
    <body><p>站点栏目介绍</p></body></html>"""
    result = extract_article(
        html, url="https://example.com/section", run_started_at=STARTED,
        time_range_days=7,
    )
    assert result.status == "failed"
    assert result.error_code == "low_quality_extraction"

