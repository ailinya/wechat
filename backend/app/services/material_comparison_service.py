"""Bounded history lookup and evidence-backed new-progress comparison."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import text

from app.adapters import model_client
from app.errors import ApiError
from app.repositories.material_repository import find_material_by_content_hash
from app.services.material_analysis_service import analyze_result

PROMPT_VERSION = "material-progress/1"
MAX_HISTORY_CANDIDATES = 5


def _load_current(engine, result_id: str) -> dict:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT r.id, r.title, r.url, r.materialize_status, s.markdown, s.content_hash "
                    "FROM collection_results r JOIN LATERAL ("
                    "SELECT markdown, content_hash FROM collection_snapshots WHERE result_id=r.id "
                    "ORDER BY captured_at DESC, id DESC LIMIT 1) s ON TRUE WHERE r.id=:id"
                ),
                {"id": result_id},
            )
            .mappings()
            .first()
        )
    if not row or not row["markdown"]:
        raise ApiError(409, "snapshot_unavailable", "没有可用于比较的正文快照")
    current = dict(row)
    current["content_hash"] = (
        current["content_hash"]
        or hashlib.sha256(current["markdown"].encode("utf-8")).hexdigest()
    )
    return current


def _history(engine, current: dict, keywords: list[str]) -> list[dict]:
    clauses = [
        "cr.url=:url",
        "m.title=:title",
        "length(:title) >= 4 AND position(lower(:title) in lower(m.title)) > 0",
    ]
    params: dict[str, Any] = {"url": current["url"], "title": current["title"]}
    for index, keyword in enumerate(keywords[:20]):
        if not keyword.strip():
            continue
        key = f"keyword_{index}"
        clauses.append(f"position(lower(:{key}) in lower(rev.content_markdown)) > 0")
        params[key] = keyword.strip()
    params["result_id"] = str(current["id"])
    params["limit"] = MAX_HISTORY_CANDIDATES
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT DISTINCT m.id AS material_id, m.title, rev.id AS revision_id, "
                    "rev.content_markdown, rev.content_hash, rev.created_at "
                    "FROM collection_results cr JOIN materials m ON m.id=cr.material_id "
                    "JOIN material_revisions rev ON rev.id=m.current_revision_id "
                    f"WHERE cr.id<>:result_id AND m.deleted_at IS NULL AND ({' OR '.join(clauses)}) "
                    "ORDER BY rev.created_at DESC, rev.id DESC LIMIT :limit"
                ),
                params,
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def compare_result_history(
    engine,
    result_id: str,
    model_config: dict,
    *,
    topic: str | None = None,
    keywords: list[str] | None = None,
    client: model_client.ModelClient | None = None,
) -> dict:
    """Compare only a small, deterministic set of related historical revisions."""
    current = _load_current(engine, str(result_id))
    with engine.connect() as conn:
        exact = find_material_by_content_hash(conn, current["content_hash"])
    if exact:
        return {
            "status": "duplicate",
            "comparisons": [
                {
                    "verdict": "duplicate",
                    "material_id": str(exact["id"]),
                    "exact_hash": True,
                }
            ],
        }
    keywords = keywords or []
    history = _history(engine, current, keywords)
    if not history:
        return {"status": "no_candidate", "comparisons": []}

    client = client or model_client.ModelClient(max_attempts=1)
    comparisons = []
    for candidate in history[:MAX_HISTORY_CANDIDATES]:
        if candidate.get("content_hash") == current["content_hash"]:
            comparisons.append(
                {
                    "verdict": "duplicate",
                    "material_id": str(candidate["material_id"]),
                    "target_revision_id": str(candidate["revision_id"]),
                    "exact_hash": True,
                }
            )
            return {"status": "duplicate", "comparisons": comparisons}

        outcome = analyze_result(
            engine,
            result_id,
            model_config,
            topic=topic,
            keywords=keywords,
            prompt_version=PROMPT_VERSION,
            client=client,
            target=candidate,
        )
        if outcome["status"] != "succeeded" or outcome.get("stale"):
            comparisons.append(
                {
                    "verdict": "uncertain",
                    "target_revision_id": str(candidate["revision_id"]),
                    "error": outcome.get("error") or "comparison_unavailable",
                }
            )
            return {"status": "review_required", "comparisons": comparisons}

        suggestions = outcome["suggestions"]
        verdict = suggestions["compare_verdict"]

        comparisons.append(
            {
                "verdict": verdict,
                "target_material_id": str(candidate["material_id"]),
                "target_revision_id": str(candidate["revision_id"]),
                "suggestions": suggestions,
                "logical_key": outcome["logical_key"],
                "analysis_id": str(outcome["id"]),
            }
        )
        if verdict in ("duplicate", "uncertain"):
            return {"status": "review_required", "comparisons": comparisons}
    status = (
        "new_progress"
        if any(row["verdict"] == "new_progress" for row in comparisons)
        else "distinct"
    )
    return {"status": status, "comparisons": comparisons}


def comparison_job_handler(engine, job):
    payload = job["payload"]
    return compare_result_history(
        engine,
        payload["result_id"],
        {"id": payload["model_config_id"]},
        topic=payload.get("topic"),
        keywords=payload.get("keywords"),
    )
