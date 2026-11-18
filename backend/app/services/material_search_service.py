"""Exact current-revision material retrieval with explainable scores."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from sqlalchemy import text

from app.adapters import embedding_client
from app.credentials import resolve_setting

_TOKENS = re.compile(r"[\u3400-\u9fff]+|[a-z0-9]+", re.IGNORECASE)


def terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    result: set[str] = set()
    for word in _TOKENS.findall(normalized):
        if "\u3400" <= word[0] <= "\u9fff":
            result.update(word[i:i + 2] for i in range(len(word) - 1))
            if len(word) == 1:
                result.add(word)
        else:
            result.add(word)
    return result


def _active_config(conn):
    model = resolve_setting("EMBEDDING_MODEL") or "qwen3.7-text-embedding-flash"
    endpoint = (resolve_setting("EMBEDDING_BASE_URL") or "https://cn-beijing.maas.qianwenaiapi.com/api/v1").rstrip("/")
    try:
        dimension = int(resolve_setting("EMBEDDING_DIMENSION") or "1024")
    except ValueError:
        raise embedding_client.EmbeddingError("embedding_configuration_error", "向量配置无效") from None
    fingerprint = hashlib.sha256(json.dumps([model, endpoint, dimension], ensure_ascii=False).encode()).hexdigest()
    config = conn.execute(text(
        "SELECT id, config_version, enabled, model_name, endpoint, params, purpose "
        "FROM model_configs WHERE name=:name"
    ), {"name": "Environment embedding " + fingerprint}).mappings().first()
    if not config or not config["enabled"] or config["purpose"] != "embedding":
        raise embedding_client.EmbeddingError("embedding_model_unavailable", "向量模型配置不可用")
    if config["model_name"] != model or config["endpoint"] != endpoint or config["params"] != {"dimension": dimension}:
        raise embedding_client.EmbeddingError("embedding_configuration_changed", "向量模型配置已变化")
    return config, model, endpoint, dimension


def search(conn, request, *, embed=embedding_client.embed_texts) -> dict:
    query_terms = terms(request.query)
    mode, reason, vectors, config = request.keyword_mode, None, None, None
    if mode == "hybrid":
        try:
            config, model, endpoint, dimension = _active_config(conn)
            vectors, _ = embed([request.query], expected_model=model, expected_base_url=endpoint, expected_dimension=dimension)
        except embedding_client.EmbeddingError as exc:
            mode, reason = "keyword_only", exc.code

    rows = conn.execute(text(
        "SELECT m.id, m.title, m.origin, m.usage_status, m.summary, r.id AS revision_id, "
        "r.content_markdown, r.file_ids, src.title AS source_title, src.url AS source_url, src.published_at "
        "FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id "
        "LEFT JOIN LATERAL (SELECT cr.title, cr.url, cr.published_at FROM collection_results cr "
        "WHERE cr.id=r.created_from_result_id OR cr.material_id=m.id "
        "ORDER BY (cr.id=r.created_from_result_id) DESC NULLS LAST, cr.collected_at, cr.id LIMIT 1) src ON true "
        "WHERE m.deleted_at IS NULL AND m.usage_status <> 'archived'"
    )).mappings().all()

    semantic = {}
    if vectors is not None:
        encoded = "[" + ",".join(format(value, ".9g") for value in vectors[0]) + "]"
        matches = conn.execute(text(
            "SELECT DISTINCT ON (c.material_revision_id) c.material_revision_id, c.content, "
            "1 - (c.embedding <=> CAST(:vector AS vector)) AS cosine "
            "FROM material_chunks c JOIN materials m ON m.current_revision_id=c.material_revision_id "
            "JOIN material_embedding_runs run ON run.material_revision_id=c.material_revision_id "
            "AND run.embedding_model_config_id=c.embedding_model_config_id "
            "AND run.embedding_config_version=c.embedding_config_version AND run.status='succeeded' "
            "WHERE c.embedding IS NOT NULL AND c.embedding_model_config_id=:config "
            "AND c.embedding_config_version=:version "
            "ORDER BY c.material_revision_id, c.embedding <=> CAST(:vector AS vector), c.chunk_index"
        ), {"vector": encoded, "config": config["id"], "version": config["config_version"]}).mappings().all()
        semantic = {row["material_revision_id"]: row for row in matches if row["cosine"] is not None}

    results = []
    for row in rows:
        status = row["usage_status"]
        if request.scope == "current" and status in ("used", "partially_used"):
            continue
        if request.statuses is not None and status not in request.statuses:
            continue
        date = row["published_at"]
        if request.from_time and (not date or date < request.from_time):
            continue
        if request.to and (not date or date > request.to):
            continue
        content = row["content_markdown"]
        matched = query_terms & terms(row["title"] + " " + content)
        lexical = len(matched) / len(query_terms) if query_terms else 0.0
        match = semantic.get(row["revision_id"])
        score = max(0.0, min(1.0, (float(match["cosine"]) + 1) / 2)) if match else None
        relevance = lexical if mode == "keyword_only" else 0.5 * lexical + 0.5 * (score or 0.0)
        if relevance <= 0 or relevance < request.min_relevance:
            continue
        snippet = match["content"] if match and not matched else content
        if matched and content:
            normalized = unicodedata.normalize("NFKC", content).casefold()
            positions = [normalized.find(term) for term in matched if normalized.find(term) >= 0]
            start = max(0, min(positions) - 60) if positions else 0
            snippet = content[start:start + 240]
        files = row["file_ids"] or []
        results.append({
            "material_id": row["id"], "title": row["title"], "matched_revision_id": row["revision_id"],
            "snippet": snippet[:240], "source": {"type": row["origin"], "title": row["source_title"],
                "url": row["source_url"] or (row["summary"] if row["origin"] == "link" else None),
                "attachment_id": files[0] if files else None},
            "published_at": date, "keyword_score": lexical, "semantic_score": score,
            "relevance_score": relevance, "score_explanation": "关键词分数" if mode == "keyword_only" else "关键词与语义分数各占 50%",
            "usage_status": status,
        })
    results.sort(key=lambda item: (-item["relevance_score"], str(item["material_id"])))
    return {"items": results[:request.top_k], "mode": mode, "degraded": reason is not None, "degradation_reason": reason}
