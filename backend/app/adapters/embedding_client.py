"""Qwen MaaS embeddings client configured from the root environment file."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from app.credentials import resolve_credential, resolve_setting


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def embed_texts(
    texts: list[str], *, expected_model: str | None = None,
    expected_base_url: str | None = None, expected_dimension: int = 1024,
) -> tuple[list[list[float]], dict]:
    model = resolve_setting("EMBEDDING_MODEL") or "qwen3.7-text-embedding-flash"
    base_url = (
        resolve_setting("EMBEDDING_BASE_URL")
        or "https://cn-beijing.maas.qianwenaiapi.com/api/v1"
    ).rstrip("/")
    api_key = resolve_credential("OPENAI_API_KEY")
    try:
        dimension = int(resolve_setting("EMBEDDING_DIMENSION") or "1024")
        batch_size = int(resolve_setting("EMBEDDING_BATCH_SIZE") or "10")
    except ValueError:
        raise EmbeddingError("embedding_configuration_error", "向量配置无效") from None
    if dimension != 1024 or batch_size < 1 or batch_size > 100:
        raise EmbeddingError("embedding_configuration_error", "向量维度或批次大小无效")
    if (
        (expected_model is not None and model != expected_model)
        or (expected_base_url is not None and base_url != expected_base_url.rstrip("/"))
        or dimension != expected_dimension
    ):
        raise EmbeddingError(
            "embedding_configuration_changed", "排队后向量配置已变化，请重新发起构建"
        )
    if not api_key:
        raise EmbeddingError("embedding_credentials_missing", "OPENAI_API_KEY 未配置")
    if not texts or len(texts) > batch_size:
        raise EmbeddingError("embedding_batch_invalid", "向量请求批次为空或超过上限")

    endpoint = base_url
    compatible = "/compatible-mode/" in base_url
    suffix = "/embeddings" if compatible else "/services/embeddings/text-embedding/text-embedding"
    if not endpoint.endswith(suffix):
        endpoint += suffix
    request_body = (
        {"model": model, "input": texts, "dimensions": dimension}
        if compatible
        else {
            "model": model,
            "input": {"texts": texts},
            "parameters": {"dimension": dimension, "output_type": "dense"},
        }
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(
            request_body,
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EmbeddingError(
            f"embedding_http_{exc.code}", f"向量服务返回 HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise EmbeddingError("embedding_unreachable", "向量服务不可达") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EmbeddingError("embedding_invalid_response", "向量服务返回无效响应") from None

    if not isinstance(body, dict):
        raise EmbeddingError("embedding_invalid_response", "向量服务返回无效响应")
    rows = (body.get("data") if compatible else (body.get("output") or {}).get("embeddings")) or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EmbeddingError("embedding_invalid_response", "向量服务返回无效响应")
    index_key = "index" if compatible else "text_index"
    if any(index_key in row for row in rows):
        indices = [row.get(index_key) for row in rows]
        if any(type(index) is not int for index in indices) or sorted(indices) != list(range(len(texts))):
            raise EmbeddingError("embedding_invalid_response", "向量服务返回的文本序号无效")
        rows = sorted(rows, key=lambda row: row[index_key])
    vectors = [row.get("embedding") for row in rows]
    if len(vectors) != len(texts) or any(
        not isinstance(vector, list)
        or len(vector) != dimension
        or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector)
        for vector in vectors
    ):
        raise EmbeddingError("embedding_dimension_mismatch", "向量服务返回数量或维度不符")
    return [[float(value) for value in vector] for vector in vectors], body.get("usage") or {}
