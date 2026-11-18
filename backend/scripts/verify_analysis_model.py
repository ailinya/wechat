"""Verify the explicitly configured DeepSeek analysis model without logging secrets."""

import json
import os
import time
import sys
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
from app.credentials import ENV_FILE, resolve_credential
from app.adapters.model_client import ModelClient, ModelError
from app.adapters.source_fetch import fetch
from app.services.document_parser import parse_article_html


def configured_model():
    values = dotenv_values(ENV_FILE, encoding="utf-8-sig")
    endpoint = os.getenv("DEEPSEEK_BASE_URL") or values.get("DEEPSEEK_BASE_URL")
    model = os.getenv("DEEPSEEK_MODEL") or values.get("DEEPSEEK_MODEL")
    if not endpoint or not model or not resolve_credential("DEEPSEEK_API_KEY"):
        raise RuntimeError(
            "DEEPSEEK_BASE_URL, DEEPSEEK_MODEL and DEEPSEEK_API_KEY must be configured"
        )
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    return {
        "enabled": True,
        "purpose": "analysis",
        "endpoint": endpoint,
        "model_name": model,
        "credential_ref": "DEEPSEEK_API_KEY",
        "max_input_tokens": 8000,
        "max_output_tokens": 2000,
        "timeout_seconds": 60,
    }


def verify():
    config = configured_model()
    public_url = "https://www.cac.gov.cn/2026-10/19/c_1794086281588959.htm"
    response = fetch(public_url)
    if response.status_code != 200:
        raise RuntimeError("Public Chinese source unavailable")
    document = parse_article_html(response.content, response.final_url)
    cases = [
        (
            "fixed-chinese",
            "星河公司于2026年11月17日发布了新型传感器。该传感器的采样率为每秒200次，比上一代提高25%。公司表示将于12月开始交付。",
            "传感器产品发布",
        ),
        (
            "official-chinese",
            document.content_markdown,
            "未成年人网络平台服务提供者认定",
        ),
    ]
    evidence = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": "DeepSeek",
        "model_name": config["model_name"],
        "credential_ref": "DEEPSEEK_API_KEY",
        "source_url": public_url,
        "source_http_status": response.status_code,
        "cases": [],
    }
    client = ModelClient(max_attempts=1)
    for name, body, topic in cases:
        started = time.monotonic()
        try:
            result = client.analysis(config, "collection-analysis/1", body, topic=topic)
            suggestions = result["suggestions"]
            evidence["cases"].append(
                {
                    "case": name,
                    "passed": bool(suggestions.summary.strip())
                    and bool(suggestions.facts),
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "input_characters": len(body),
                    "suggestions": suggestions.model_dump(mode="json"),
                    "usage": result["usage"],
                }
            )
        except ModelError as exc:
            evidence["cases"].append(
                {
                    "case": name,
                    "passed": False,
                    "error_code": exc.code,
                    "error_message": exc.message,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                }
            )
    evidence["passed"] = all(row["passed"] for row in evidence["cases"])
    return evidence


if __name__ == "__main__":
    if "--probe" in sys.argv:
        config = configured_model()
        endpoint = urlsplit(config["endpoint"])
        report = {
            "host": endpoint.hostname,
            "path": endpoint.path,
            "model": config["model_name"],
        }
        try:
            result = ModelClient(max_attempts=1).complete_json(
                config, "Return JSON only", "{}"
            )
            report.update(connected=True, usage=result["usage"])
        except ModelError as exc:
            report.update(
                connected=False, error_code=exc.code, error_message=exc.message
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(0)
    evidence = verify()
    output = (
        Path(__file__).resolve().parents[2]
        / "doc/development/analysis-model-live-evidence.json"
    )
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
