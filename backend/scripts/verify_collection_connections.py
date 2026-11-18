"""Print sanitized live collection evidence; credentials remain in the environment."""

import json
from datetime import datetime, timezone
from app.adapters.search_client import SearchClient, SearchError
from app.adapters.source_fetch import fetch, FetchError
from app.services.document_parser import parse_article_html, ParseError


def verify():
    evidence = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "search": {},
        "article": {},
        "model": {
            "status": "separate_verification",
            "reason": "Run scripts/verify_analysis_model.py for live analysis model evidence; this script checks search and article extraction only.",
        },
    }
    config = {
        "enabled": True,
        "provider": "tavily",
        "credential_ref": "TAVILY_API_KEY",
        "config_version": 1,
        "max_results": 1,
        "supports_domain_filter": True,
        "supports_date_filter": True,
    }
    try:
        result = SearchClient(max_attempts=1).search(
            config, "人工智能 最新进展", max_results=1
        )
        evidence["search"] = {
            "connected": True,
            "results": len(result.candidates),
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
        if result.candidates:
            url = result.candidates[0].url
            try:
                response = fetch(url)
                if not 200 <= response.status_code < 300:
                    raise FetchError("http_error", f"HTTP {response.status_code}")
                parsed = parse_article_html(response.content, response.final_url)
                evidence["article"] = {
                    "url": response.final_url,
                    "http_status": response.status_code,
                    "title": parsed.title,
                    "published_evidence": parsed.published_at,
                    "markdown_length": len(parsed.content_markdown),
                    "extractor_version": parsed.extractor_version,
                    "latency_ms": response.elapsed_ms,
                }
            except (FetchError, ParseError) as exc:
                evidence["article"] = {
                    "url": url,
                    "error_code": exc.code,
                    "message": exc.message,
                }
    except SearchError as exc:
        evidence["search"] = {
            "connected": False,
            "error_code": exc.code,
            "message": exc.message,
        }
    return evidence


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
