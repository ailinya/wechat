"""Task 3.13 collection tooling evaluation runner (EVALUATION ONLY).

Not part of the application. Runs the fixed annotated sample set in
doc/development/collection-samples.json against the candidate tools and
writes per-sample results to doc/development/collection-tool-eval-results.json.

Dependencies (feedparser, trafilatura, requests) are NOT production
dependencies; install them into an isolated venv:

    uv venv "$TEMP/wetchat-tool-eval"
    uv pip install --python "$TEMP/wetchat-tool-eval" feedparser trafilatura requests

Tavily uses the TAVILY_API_KEY environment variable (never persisted).
The analysis-model check looks for any of the listed provider credential
variables; if absent, the item is recorded as blocked (never simulated).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import trafilatura

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "doc/development/collection-samples.json"
RESULTS = ROOT / "doc/development/collection-tool-eval-results.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FETCH_TIMEOUT = 20

MODEL_CREDENTIAL_VARS = [
    "ZHIPUAI_API_KEY", "GLM_API_KEY", "BIGMODEL_API_KEY", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate_feed(sample: dict) -> dict:
    started = time.monotonic()
    parsed = feedparser.parse(sample["url"], request_headers=HEADERS)
    latency_ms = int((time.monotonic() - started) * 1000)
    if parsed.entries:
        first = parsed.entries[0]
        first_summary = {
            "title": (first.get("title") or "")[:60],
            "link": first.get("link"),
            "published": first.get("published") or first.get("updated"),
        }
    else:
        first_summary = None
    return {
        "id": sample["id"],
        "url": sample["url"],
        "latency_ms": latency_ms,
        "parse_ok": bool(parsed.entries),
        "entry_count": len(parsed.entries),
        "version": parsed.version or None,
        "bozo_reason": str(parsed.get("bozo_exception")) if parsed.bozo and not parsed.entries else None,
        "first_entry": first_summary,
        "expect_pass": sample["expect"]["parse_ok"],
        "matches_expectation": bool(parsed.entries) == sample["expect"]["parse_ok"],
    }


def evaluate_article(sample: dict) -> dict:
    started = time.monotonic()
    downloaded = trafilatura.fetch_url(sample["url"])
    fetch_ms = int((time.monotonic() - started) * 1000)
    if not downloaded:
        return {
            "id": sample["id"], "url": sample["url"], "fetch_ms": fetch_ms,
            "body_ok": False, "error": "fetch_failed_or_timeout",
            "expect_pass": sample["expect"]["body_ok"],
            "matches_expectation": sample["expect"]["body_ok"] is False,
        }
    text = trafilatura.extract(downloaded, with_metadata=True, include_comments=False)
    metadata = trafilatura.extract_metadata(downloaded)
    extract_ms = int((time.monotonic() - started) * 1000)
    title = (metadata.title if metadata else "") or ""
    body_ok = bool(text) and len(text or "") >= 200 and not title.lstrip().startswith("var ")
    date = metadata.date if metadata else None
    result = {
        "id": sample["id"], "url": sample["url"], "fetch_ms": fetch_ms,
        "total_ms": extract_ms, "body_ok": body_ok,
        "body_length": len(text or ""),
        "title": title[:60],
        "title_polluted": title.lstrip().startswith("var "),
        "date": date,
        "date_present": bool(date or re.search(r"20\d\d[-年/]\d{1,2}[-月/]\d{1,2}", text or "")),
        "expect_pass": sample["expect"]["body_ok"],
        "matches_expectation": (body_ok == sample["expect"]["body_ok"])
        and (sample["expect"].get("title_polluted") is None or
             result_title_polluted(sample, title)),
    }
    return result


def result_title_polluted(sample: dict, title: str) -> bool:
    return bool(title.lstrip().startswith("var ")) == bool(sample["expect"].get("title_polluted"))


def evaluate_list_page(sample: dict) -> dict:
    started = time.monotonic()
    try:
        response = requests.get(sample["url"], headers=HEADERS, timeout=FETCH_TIMEOUT)
        latency_ms = int((time.monotonic() - started) * 1000)
        links = re.findall(r'href="([^"]*?(?:20\d\d)[^"]*?\.s?html?)"', response.text)
        unique = list(dict.fromkeys(links))
        fresh = [l for l in unique if re.search(r"202[4-6]", l)]
        return {
            "id": sample["id"], "url": sample["url"], "status": response.status_code,
            "latency_ms": latency_ms, "links_found": len(unique),
            "fresh_links": len(fresh), "sample_links": fresh[:3],
            "links_discoverable": len(fresh) > 0,
            "matches_expectation": (len(fresh) > 0) == sample["expect"]["links_discoverable"],
        }
    except Exception as exc:  # noqa: BLE001 - evaluation records failures as data
        return {"id": sample["id"], "url": sample["url"], "error": f"{type(exc).__name__}: {exc}",
                "links_discoverable": False, "matches_expectation": False}


def evaluate_search(query: dict) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"id": query["id"], "query": query["query"], "blocked": True,
                "blocker": "TAVILY_API_KEY not set"}
    payload = {
        "api_key": api_key,
        "query": query["query"],
        "search_depth": "basic",
        "max_results": 5,
        "topic": "news",
    }
    if query.get("include_domains"):
        payload["include_domains"] = query["include_domains"]
    started = time.monotonic()
    try:
        response = requests.post("https://api.tavily.com/search", json=payload, timeout=30)
        latency_ms = int((time.monotonic() - started) * 1000)
        data = response.json()
        results = [
            {"score": round(r.get("score", 0), 3),
             "url": (r.get("url") or "")[:90],
             "title": (r.get("title") or "")[:50]}
            for r in data.get("results", [])
        ]
        domains_hit = [r["url"] for r in results]
        expectation_ok = all(
            any(domain in url for url in domains_hit)
            for domain in query.get("expect_domains", [])
        )
        return {
            "id": query["id"], "query": query["query"], "blocked": False,
            "status": response.status_code, "latency_ms": latency_ms,
            "results": results,
            "expected_domain_in_results": expectation_ok,
            "matches_expectation": expectation_ok,
        }
    except Exception as exc:  # noqa: BLE001
        return {"id": query["id"], "query": query["query"], "blocked": False,
                "error": f"{type(exc).__name__}: {exc}", "matches_expectation": False}


def evaluate_analysis_model() -> dict:
    present = [name for name in MODEL_CREDENTIAL_VARS if os.environ.get(name)]
    if not present:
        return {
            "tool": "analysis model (LLM structured output + citation)",
            "blocked": True,
            "blocker": "未找到任何模型凭据（" + ", ".join(MODEL_CREDENTIAL_VARS) + " 均未设置）",
            "verification": "中文结构化输出与原文引用能力未验证；不能用 fixture 宣称通过。待凭据可用后在 3.16/3.20 复验。",
        }
    return {
        "tool": "analysis model (LLM structured output + citation)",
        "blocked": False,
        "credential_vars_present": present,
        "note": "发现凭据变量，但本评估脚本未实现模型调用；需在 3.16 adapter 完成后复验结构化输出与引用。",
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = {
        "generated_at": _now_iso(),
        "tool_versions": {
            "feedparser": feedparser.__version__,
            "trafilatura": trafilatura.__version__,
            "requests": requests.__version__,
        },
        "feeds": [evaluate_feed(sample) for sample in manifest["feeds"]],
        "articles": [evaluate_article(sample) for sample in manifest["articles"]],
        "list_pages": [evaluate_list_page(sample) for sample in manifest["list_pages"]],
        "search": [evaluate_search(query) for query in manifest["search_queries"]],
        "analysis_model": evaluate_analysis_model(),
        "known_gaps": manifest["known_gaps"],
    }
    RESULTS.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {RESULTS}")
    feeds_ok = sum(1 for r in output["feeds"] if r["matches_expectation"])
    articles_ok = sum(1 for r in output["articles"] if r["matches_expectation"])
    print(f"feeds: {feeds_ok}/{len(output['feeds'])} match expectation; "
          f"articles: {articles_ok}/{len(output['articles'])} match expectation")


if __name__ == "__main__":
    sys.exit(main())
