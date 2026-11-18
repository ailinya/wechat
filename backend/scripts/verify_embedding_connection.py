"""Verify the configured Qwen embedding model and vector dimension."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.credentials import resolve_credential, resolve_setting


def verify() -> dict:
    model_name = resolve_setting("EMBEDDING_MODEL") or "qwen3.7-text-embedding-flash"
    dimension = int(resolve_setting("EMBEDDING_DIMENSION") or "1024")
    base_url = (
        resolve_setting("EMBEDDING_BASE_URL")
        or "https://cn-beijing.maas.qianwenaiapi.com/api/v1"
    ).rstrip("/")
    api_key = resolve_credential("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    endpoint = base_url
    compatible = "/compatible-mode/" in endpoint
    suffix = "/embeddings" if compatible else "/services/embeddings/text-embedding/text-embedding"
    if not endpoint.endswith(suffix):
        endpoint += suffix
    inputs = ["中文向量维度连通性验证：人工智能与产业应用。"]
    payload = (
        {"model": model_name, "input": inputs, "dimensions": dimension}
        if compatible
        else {"model": model_name, "input": {"texts": inputs},
              "parameters": {"dimension": dimension, "output_type": "dense"}}
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        error_code = None
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
            error_code = error_body.get("code") or (
                error_body.get("error") or {}
            ).get("code")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Qwen MaaS",
            "endpoint_host": urlsplit(endpoint).hostname,
            "model_name": model_name,
            "requested_dimension": dimension,
            "actual_dimension": None,
            "http_status": exc.code,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error_code": error_code or "embedding_request_failed",
            "passed": False,
            "credential_ref": "OPENAI_API_KEY",
        }
    except urllib.error.URLError as exc:
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Qwen MaaS",
            "endpoint_host": urlsplit(endpoint).hostname,
            "model_name": model_name,
            "requested_dimension": dimension,
            "actual_dimension": None,
            "http_status": None,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error_code": "embedding_service_unreachable",
            "passed": False,
            "credential_ref": "OPENAI_API_KEY",
        }

    rows = (body.get("data") if compatible else (body.get("output") or {}).get("embeddings")) or []
    vector = rows[0].get("embedding") if rows else None
    actual_dimension = len(vector) if isinstance(vector, list) else None
    parsed_url = urlsplit(endpoint)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Qwen MaaS",
        "endpoint_host": parsed_url.hostname,
        "model_name": model_name,
        "requested_dimension": dimension,
        "actual_dimension": actual_dimension,
        "returned_model": body.get("model"),
        "total_tokens": (body.get("usage") or {}).get("total_tokens"),
        "request_id": body.get("id"),
        "http_status": status,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "passed": status == 200 and actual_dimension == dimension,
        "credential_ref": "OPENAI_API_KEY",
    }


if __name__ == "__main__":
    try:
        evidence = verify()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None

    output = (
        Path(__file__).resolve().parents[2]
        / "doc/development/embedding-model-live-evidence.json"
    )
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    raise SystemExit(0 if evidence["passed"] else 1)
