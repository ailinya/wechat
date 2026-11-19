"""Indexed lexical candidates and bounded ANN candidates, reranked by exact scores."""

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


def _partial_lexical_candidates(conn,params,where,source_join):
    sql = ("WITH candidates AS (SELECT id FROM materials WHERE deleted_at IS NULL AND search_terms && CAST(:terms AS text[]) "
        "UNION SELECT m.id FROM material_revisions r JOIN materials m ON m.current_revision_id=r.id WHERE r.search_terms && CAST(:terms AS text[]) AND m.deleted_at IS NULL) "
        "SELECT m.id FROM candidates candidate JOIN materials m ON m.id=candidate.id JOIN material_revisions r ON r.id=m.current_revision_id "+source_join+
        "WHERE "+where+" ORDER BY (SELECT count(*) FROM unnest(CAST(:terms AS text[])) term WHERE term=ANY(m.search_terms) OR term=ANY(r.search_terms)) DESC,m.id LIMIT :candidate_limit")
    return conn.execute(text(sql),params).scalars()


def search(conn, request, *, embed=embedding_client.embed_texts) -> dict:
    query_terms = terms(request.query)
    mode, reason, vectors, config = request.keyword_mode, None, None, None
    if mode == "hybrid":
        try:
            config, model, endpoint, dimension = _active_config(conn)
            vectors, _ = embed([request.query], expected_model=model, expected_base_url=endpoint, expected_dimension=dimension)
        except embedding_client.EmbeddingError as exc:
            mode, reason = "keyword_only", exc.code

    # Candidate selection happens in PostgreSQL; never load the full corpus in Python.
    params = {"terms": sorted(query_terms), "candidate_limit": max(100,request.top_k*10)}
    filters = ["m.deleted_at IS NULL", "m.usage_status<>'archived'"]
    if request.scope == 'current':
        filters.append("m.usage_status NOT IN ('used','partially_used')")
    if request.statuses is not None:
        filters.append("m.usage_status=ANY(CAST(:statuses AS text[]))")
        params['statuses']=request.statuses
    source_join = (" LEFT JOIN LATERAL (SELECT cr.title,cr.url,cr.published_at FROM collection_results cr "
                   "WHERE cr.id=r.created_from_result_id OR cr.material_id=m.id "
                   "ORDER BY (cr.id=r.created_from_result_id) DESC NULLS LAST,cr.collected_at,cr.id LIMIT 1) src ON true ")
    if request.from_time:
        filters.append('src.published_at>=:from_time');params['from_time']=request.from_time
    if request.to:
        filters.append('src.published_at<=:to_time');params['to_time']=request.to
    where=' AND '.join(filters)
    candidate_ids=set()
    if query_terms:
        # Full lexical matches have the maximal keyword score. Find a bounded
        # batch first, so common Chinese phrases do not sort the entire corpus.
        lexical_source = source_join if request.from_time or request.to else ''
        for column in ['m.search_terms','r.search_terms']:
            full = conn.execute(text(
                'SELECT m.id FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id '+lexical_source+
                'WHERE '+where+' AND '+column+' @> CAST(:terms AS text[]) ORDER BY m.id LIMIT :candidate_limit'
            ),params).scalars()
            candidate_ids.update(full)
        if len(candidate_ids) < params['candidate_limit']:
            lexical_candidates = _partial_lexical_candidates(conn,params,where,source_join)
            candidate_ids.update(lexical_candidates)
    semantic={}
    if vectors is not None:
        encoded='['+','.join(format(value,'.9g') for value in vectors[0])+']'
        params.update(vector=encoded,config=config['id'],version=config['config_version'])
        conn.execute(text("SET LOCAL hnsw.ef_search=200"))
        conn.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
        revision_source = (' JOIN material_revisions r ON r.id=m.current_revision_id '+source_join) if request.from_time or request.to else ''
        nearest=conn.execute(text(
            "WITH candidates AS MATERIALIZED (SELECT v.id,1-(v.embedding <=> CAST(:vector AS vector)) AS cosine "
            "FROM material_search_vectors v WHERE v.embedding_model_config_id=:config AND v.embedding_config_version=:version "
            "AND EXISTS (SELECT 1 FROM material_chunk_search_vectors link JOIN material_chunks c ON c.id=link.chunk_id "
            "JOIN materials m ON m.current_revision_id=c.material_revision_id "+revision_source+
            "JOIN material_embedding_runs run ON run.material_revision_id=c.material_revision_id AND run.embedding_model_config_id=c.embedding_model_config_id "
            "AND run.embedding_config_version=c.embedding_config_version AND run.status='succeeded' "
            "WHERE link.vector_id=v.id AND "+where+
            " AND c.embedding IS NOT NULL AND c.embedding_model_config_id=:config AND c.embedding_config_version=:version) "
            "ORDER BY binary_quantize(v.embedding)::bit(1024) <~> binary_quantize(CAST(:vector AS vector))::bit(1024) LIMIT :candidate_limit) "
            "SELECT matched.*,nearest.cosine FROM (SELECT * FROM candidates ORDER BY cosine DESC) nearest "
            "CROSS JOIN LATERAL (SELECT DISTINCT ON(c.material_revision_id) m.id,c.material_revision_id,c.content "
            "FROM material_chunk_search_vectors link JOIN material_chunks c ON c.id=link.chunk_id "
            "JOIN materials m ON m.current_revision_id=c.material_revision_id "+revision_source+
            "JOIN material_embedding_runs run ON run.material_revision_id=c.material_revision_id AND run.embedding_model_config_id=c.embedding_model_config_id "
            "AND run.embedding_config_version=c.embedding_config_version AND run.status='succeeded' "
            "WHERE link.vector_id=nearest.id AND "+where+
            " AND c.embedding IS NOT NULL AND c.embedding_model_config_id=:config AND c.embedding_config_version=:version "
            "ORDER BY c.material_revision_id,c.chunk_index LIMIT :candidate_limit) matched "
            "ORDER BY nearest.cosine DESC,matched.material_revision_id LIMIT :candidate_limit"
        ),params).mappings().all()
        for row in nearest:
            if row['cosine'] is None:
                continue
            candidate_ids.add(row['id'])
            prior=semantic.get(row['material_revision_id'])
            if prior is None or row['cosine']>prior['cosine']:
                semantic[row['material_revision_id']]=row
    if not candidate_ids:
        return {'items':[],'mode':mode,'degraded':reason is not None,'degradation_reason':reason}
    params['ids']=list(candidate_ids)
    rows=conn.execute(text(
        "SELECT m.id,m.title,m.origin,m.usage_status,m.summary,r.id AS revision_id,r.content_markdown,r.file_ids,src.title AS source_title,src.url AS source_url,src.published_at "
        "FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id "+source_join+
        "WHERE m.id=ANY(CAST(:ids AS uuid[])) AND "+where
    ),params).mappings().all()

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
            "relevance_score": relevance, "score_explanation": "关键词分数" if mode == "keyword_only" else "关键词与语义各占50%；近似语义候选经原向量余弦重排",
            "usage_status": status,
        })
    results.sort(key=lambda item: (-item["relevance_score"], str(item["material_id"])))
    return {"items": results[:request.top_k], "mode": mode, "degraded": reason is not None, "degradation_reason": reason}
