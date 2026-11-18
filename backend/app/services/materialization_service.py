"""Collection-result materialization with exact deduplication (tasks 3.7/3.21).

Different content is not enough to claim new progress; only a validated
comparison may create an `update_of` relation.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.errors import ApiError
from app.repositories import collection_repository as collection_repo
from app.repositories import material_repository as material_repo
from app.services import (
    async_job_service,
    document_parser,
    material_embedding_service,
    outbox_service,
)

TERMINAL = {"materialized", "duplicate", "new_progress"}
IGNORED = "ignored"
JOB_TASK = "app.modules.async_execution.tasks.run_async_job"


def accept_job(
    conn: Connection,
    job_type: str,
    result_id: UUID | str,
    user_id: UUID | str | None,
) -> dict:
    """Create the async job + outbox event for a materialize/retry request."""
    job = async_job_service.create_job(
        conn,
        job_type,
        "collection_result",
        result_id,
        payload={
            "result_id": str(result_id),
            "user_id": str(user_id) if user_id else None,
        },
        created_by=user_id,
    )
    outbox_service.publish_event(
        conn,
        f"{job_type}.requested",
        "collection_result",
        result_id,
        payload={"task": JOB_TASK, "kwargs": {"job_id": job["id"]}},
    )
    return job


def _content_type(result: dict) -> str:
    raw = (result.get("raw_content") or "").lstrip()
    if raw.startswith("<"):
        return "text/html"
    return "text/plain"


def parsed_markdown(result: dict) -> str:
    """Parse the stored original response; failures carry a readable reason."""
    try:
        return document_parser.parse_bytes(
            (result.get("raw_content") or "").encode("utf-8"), _content_type(result)
        ).content_markdown
    except document_parser.ParseError as exc:
        raise ApiError(422, "parse_failed", exc.message) from None


def _validated_progress_target(conn, result_id, analysis_id):
    row = conn.execute(
        text(
            "SELECT m.id FROM collection_analyses a "
            "JOIN collection_snapshots s ON s.id=a.snapshot_id "
            "JOIN material_revisions rev ON rev.id=a.target_revision_id "
            "JOIN materials m ON m.current_revision_id=rev.id "
            "WHERE a.id=:analysis AND a.result_id=:result AND a.status='succeeded' AND NOT a.stale "
            "AND m.deleted_at IS NULL AND a.input_context->>'purpose'='compare' "
            "AND a.suggestions->>'compare_verdict'='new_progress' "
            "AND jsonb_array_length(a.suggestions->'facts') > 0 "
            "AND a.input_hash=s.content_hash AND s.id=(SELECT id FROM collection_snapshots "
            "WHERE result_id=:result ORDER BY captured_at DESC,id DESC LIMIT 1)"
        ),
        {"analysis": str(analysis_id), "result": str(result_id)},
    ).scalar_one_or_none()
    if not row:
        raise ApiError(409, "invalid_progress_evidence", "新进展比较依据缺失或已过期")
    return row


def materialize(
    conn: Connection,
    result_id: UUID | str,
    user_id: UUID | str | None,
    *,
    progress_decision: dict | None = None,
    allow_review: bool = False,
) -> dict[str, Any]:
    result = collection_repo.get_result(conn, result_id)
    if not result:
        raise ApiError(404, "not_found", "采集结果不存在")
    status = result["materialize_status"]
    if status in TERMINAL and result.get("material_id"):
        # Repeated submission is idempotent: return the existing association.
        return {"status": status, "material_id": str(result["material_id"])}
    if status == IGNORED:
        raise ApiError(409, "result_ignored", "该结果已忽略，不能入库")

    markdown = parsed_markdown(result)
    if conn is not None:
        snapshot = conn.execute(
            text(
                "SELECT markdown FROM collection_snapshots WHERE result_id=:id AND markdown IS NOT NULL "
                "ORDER BY captured_at DESC,id DESC LIMIT 1"
            ),
            {"id": str(result_id)},
        ).scalar_one_or_none()
        if snapshot:
            markdown = snapshot
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if conn is not None:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:hash, 0))"),
            {"hash": content_hash},
        )
    identical = material_repo.find_material_by_content_hash(conn, content_hash)
    if identical:
        collection_repo.set_result_materialized(
            conn, result_id, identical["id"], "duplicate"
        )
        if conn is not None:
            _bind_analyses(conn, result_id, identical["id"], content_hash)
        return {"status": "duplicate", "material_id": str(identical["id"])}

    target_id = None
    if conn is not None and not allow_review:
        candidate = (
            conn.execute(
                text(
                    "SELECT c.status,run.config_snapshot FROM collection_candidates c JOIN collection_runs run ON run.id=c.run_id WHERE c.result_id=:id"
                ),
                {"id": str(result_id)},
            )
            .mappings()
            .first()
        )
        if candidate:
            if candidate["status"] in ("review_required", "filtered", "failed"):
                raise ApiError(409, "review_required", "该结果需要人工保留或筛选")
            if candidate["config_snapshot"].get("analysis_enabled"):
                valid = conn.execute(
                    text(
                        "SELECT 1 FROM collection_analyses WHERE result_id=:id AND status='succeeded' AND NOT stale AND input_context->>'purpose'='analysis' AND suggestions->>'relevance' IN ('relevant','not_applicable') LIMIT 1"
                    ),
                    {"id": str(result_id)},
                ).first()
                if not valid:
                    raise ApiError(409, "analysis_required", "当前正文分析尚未完成")
    if progress_decision:
        if not progress_decision.get("analysis_id"):
            raise ApiError(
                409, "invalid_progress_evidence", "新进展需要已保存的比较分析记录"
            )
        target_id = _validated_progress_target(
            conn, result_id, progress_decision["analysis_id"]
        )
    created = material_repo.create_material_with_revision(
        conn,
        title=result["title"] or "未命名素材",
        markdown=markdown,
        content_hash=content_hash,
        origin="collection",
        created_by=user_id,
        source_result_id=result_id,
    )
    if conn is not None:
        material_embedding_service.enqueue_rebuild(
            conn,
            created["material_id"],
            revision_id=created["revision_id"],
            user_id=user_id,
        )
    materialize_status = "materialized"
    if target_id:
        material_repo.add_relation(conn, created["material_id"], target_id, "update_of")
        materialize_status = "new_progress"
    collection_repo.set_result_materialized(
        conn, result_id, created["material_id"], materialize_status
    )
    if conn is not None:
        _bind_analyses(conn, result_id, created["material_id"], content_hash)
    return {"status": materialize_status, "material_id": created["material_id"]}


def _bind_analyses(conn, result_id, material_id, content_hash):
    conn.execute(
        text(
            "UPDATE collection_analyses SET material_id=:material,material_revision_id=(SELECT current_revision_id FROM materials WHERE id=:material) WHERE result_id=:result AND input_hash=:hash AND material_revision_id IS NULL"
        ),
        {"material": str(material_id), "result": str(result_id), "hash": content_hash},
    )


def bulk_materialize(
    conn: Connection, result_ids: list[UUID | str], user_id: UUID | str | None
) -> dict:
    items: list[dict] = []
    counts = {
        "materialized": 0,
        "duplicate": 0,
        "new_progress": 0,
        "ignored": 0,
        "failed": 0,
    }
    for result_id in result_ids:
        try:
            outcome = materialize(conn, result_id, user_id)
            item = {"result_id": str(result_id), **outcome, "error": None}
            counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
        except ApiError as exc:
            item = {
                "result_id": str(result_id),
                "status": "failed",
                "material_id": None,
                "error": exc.message,
            }
            counts["failed"] += 1
        items.append(item)
    return {"items": items, "counts": counts}


def ignore(conn: Connection, result_id: UUID | str) -> None:
    result = collection_repo.get_result(conn, result_id)
    if not result:
        raise ApiError(404, "not_found", "采集结果不存在")
    if result["materialize_status"] in TERMINAL:
        raise ApiError(409, "result_materialized", "该结果已入库，不能忽略")
    collection_repo.set_result_ignored(conn, result_id)


def retry_parse(conn: Connection, result_id: UUID | str) -> None:
    result = collection_repo.get_result(conn, result_id)
    if not result:
        raise ApiError(404, "not_found", "采集结果不存在")
    if not result.get("raw_content"):
        raise ApiError(422, "no_raw_content", "无原始内容可重试解析")
    try:
        document_parser.parse_bytes(
            result["raw_content"].encode("utf-8"), _content_type(result)
        )
    except document_parser.ParseError as exc:
        collection_repo.set_result_parse_status(
            conn, result_id, status="failed", error=exc.message
        )
        return
    collection_repo.set_result_parse_status(
        conn, result_id, status="parsed", error=None
    )


def auto_materialize_run(
    conn: Connection, run_id: UUID | str, user_id: UUID | str | None
) -> int:
    """Materialize every parsed, pending result of a run; return success count."""
    rows, _ = collection_repo.list_results(
        conn, 1, 100, run_id=run_id, parse_status="parsed", materialize_status="pending"
    )
    count = 0
    for row in rows:
        try:
            materialize(conn, row["id"], user_id)
            count += 1
        except ApiError:
            continue
    return count
