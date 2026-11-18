"""Analysis inspection, explicit adoption and review retention."""

import json

from sqlalchemy import text

from app.errors import ApiError
from app.repositories import collection_repository, material_repository
from app.services import (
    audit_service,
    async_job_service,
    outbox_service,
    materialization_service,
)


def get_analysis(conn, analysis_id):
    row = (
        conn.execute(
            text(
                "SELECT a.*,COALESCE(a.material_id,r.material_id) AS linked_material_id FROM collection_analyses a LEFT JOIN collection_results r ON r.id=a.result_id WHERE a.id=:id"
            ),
            {"id": str(analysis_id)},
        )
        .mappings()
        .first()
    )
    if not row:
        raise ApiError(404, "not_found", "分析记录不存在")
    row = dict(row)
    row["material_id"] = row.pop("linked_material_id")
    row["input_snapshot_id"] = row["snapshot_id"]
    row["model_config_version"] = (row["config_snapshot"] or {}).get("config_version")
    row["purpose"] = (row["input_context"] or {}).get("purpose", "analysis")
    if row["result_id"] and row["snapshot_id"]:
        current = conn.execute(
            text(
                "SELECT id FROM collection_snapshots WHERE result_id=:id AND markdown IS NOT NULL ORDER BY captured_at DESC,id DESC LIMIT 1"
            ),
            {"id": row["result_id"]},
        ).scalar_one_or_none()
        row["stale"] = row["stale"] or current != row["snapshot_id"]
    if row["material_revision_id"]:
        current = conn.execute(
            text("SELECT current_revision_id FROM materials WHERE id=:id"),
            {"id": row["material_id"]},
        ).scalar_one_or_none()
        row["stale"] = row["stale"] or current != row["material_revision_id"]
    if row["target_revision_id"]:
        active = conn.execute(
            text(
                "SELECT 1 FROM materials WHERE current_revision_id=:revision AND deleted_at IS NULL"
            ),
            {"revision": row["target_revision_id"]},
        ).first()
        row["stale"] = row["stale"] or not active
    return row


def list_analyses(conn, page, page_size, result_id=None, material_id=None, status=None):
    clauses, params = [], {"limit": page_size, "offset": (page - 1) * page_size}
    for name, value in (("result_id", result_id), ("status", status)):
        if value:
            clauses.append(f"a.{name}=:{name}")
            params[name] = str(value)
    if material_id:
        clauses.append("(a.material_id=:material OR r.material_id=:material)")
        params["material"] = str(material_id)
    where = " AND ".join(clauses) or "TRUE"
    query = (
        "FROM collection_analyses a LEFT JOIN collection_results r ON r.id=a.result_id WHERE "
        + where
    )
    total = conn.execute(text("SELECT count(*) " + query), params).scalar_one()
    ids = (
        conn.execute(
            text(
                "SELECT a.id "
                + query
                + " ORDER BY a.created_at DESC,a.id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        .scalars()
        .all()
    )
    return [get_analysis(conn, aid) for aid in ids], total


def retry_analysis(conn, analysis_id, user_id):
    row = get_analysis(conn, analysis_id)
    if row["stale"] or row["status"] != "failed":
        raise ApiError(409, "analysis_not_retryable", "分析已过期或不处于可重试状态")
    result = (
        collection_repository.get_result(conn, row["result_id"])
        if row["result_id"]
        else None
    )
    if result and result["materialize_status"] == "ignored":
        raise ApiError(409, "result_ignored", "已忽略结果不能重试")
    context = row["input_context"] or {}
    if row["scope"] == "material_revision":
        job = async_job_service.create_job(
            conn,
            "material.analysis",
            "material",
            row["material_id"],
            payload={
                "material_id": str(row["material_id"]),
                "model_config_id": str(row["model_config_id"]),
                "topic": context.get("topic"),
                "keywords": context.get("keywords", []),
            },
            created_by=user_id,
        )
        outbox_service.publish_event(
            conn,
            "material.analysis.retry",
            "material",
            row["material_id"],
            payload={
                "task": "app.modules.async_execution.tasks.run_async_job",
                "kwargs": {"job_id": job["id"]},
            },
        )
        audit_service.record_operation(
            conn,
            user_id=user_id,
            action="material.analysis.retry",
            object_type="analysis",
            object_id=analysis_id,
        )
        return job
    job = async_job_service.create_job(
        conn,
        "collection.comparison"
        if context.get("purpose") == "compare"
        else "collection.analysis",
        "collection_result",
        row["result_id"],
        payload={
            "result_id": str(row["result_id"]),
            "model_config_id": str(row["model_config_id"]),
            "topic": context.get("topic"),
            "keywords": context.get("keywords", []),
        },
        created_by=user_id,
    )
    outbox_service.publish_event(
        conn,
        "collection.analysis.requested",
        "collection_result",
        row["result_id"],
        payload={
            "task": "app.modules.async_execution.tasks.run_async_job",
            "kwargs": {"job_id": job["id"]},
        },
    )
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="collection.analysis.retry",
        object_type="analysis",
        object_id=analysis_id,
    )
    return job


def apply_analysis(conn, analysis_id, payload, user_id, *, fill_empty=False):
    row = get_analysis(conn, analysis_id)
    if row["status"] != "succeeded" or row["stale"] or not row["material_id"]:
        raise ApiError(409, "analysis_not_applicable", "分析未完成、已过期或未关联素材")
    material = (
        conn.execute(
            text("SELECT * FROM materials WHERE id=:id FOR UPDATE"),
            {"id": row["material_id"]},
        )
        .mappings()
        .one()
    )
    if (
        material["deleted_at"]
        or material["usage_status"] == "archived"
        or material["metadata_version"] != payload.base_metadata_version
    ):
        raise ApiError(409, "conflict", "素材已归档或元数据版本已变化")
    suggestions = row["suggestions"] or {}
    assignments, params = (
        ["metadata_version=metadata_version+1", "updated_at=now()"],
        {"id": material["id"]},
    )
    manual = set(material["manual_fields"] or [])
    if "summary" in payload.apply and (
        not fill_empty or (not material["summary"] and "summary" not in manual)
    ):
        assignments.append("summary=:summary")
        params["summary"] = suggestions.get("summary", "")
    if "category" in payload.apply and (
        not fill_empty or (not material["category_id"] and "category" not in manual)
    ):
        category = next(
            (
                c.get("category_id")
                for c in suggestions.get("category_candidates", [])
                if c.get("category_id") and c.get("exists")
            ),
            None,
        )
        if payload.confirmed_categories:
            category = str(payload.confirmed_categories[0])
        if not category and suggestions.get("category_candidates") and not fill_empty:
            raise ApiError(422, "category_confirmation_required", "请选择已确认分类")
        if category:
            if not material_repository.category_by_id(conn, category):
                raise ApiError(422, "invalid_category", "建议分类不存在，请人工确认")
            assignments.append("category_id=:category")
            params["category"] = category
    if "tags" in payload.apply and (
        not fill_empty
        or (
            not material_repository.tags_for_material(conn, material["id"])
            and "tags" not in manual
        )
    ):
        tags = payload.confirmed_tags
        if not tags and suggestions.get("tag_suggestions") and not fill_empty:
            raise ApiError(422, "tag_confirmation_required", "请选择已确认标签")
        if tags:
            valid = material_repository.valid_tag_ids(conn, tags)
            if len(valid) != len(set(map(str, tags))):
                raise ApiError(422, "invalid_tags", "标签不存在，请人工确认")
            material_repository.set_material_tags(conn, material["id"], valid)
    if not fill_empty:
        manual.update(payload.apply)
        assignments.append("manual_fields=CAST(:manual AS jsonb)")
        params["manual"] = json.dumps(sorted(manual))
    conn.execute(
        text("UPDATE materials SET " + ",".join(assignments) + " WHERE id=:id"), params
    )
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="material.analysis.apply",
        object_type="material",
        object_id=material["id"],
    )


def retain_result(conn, result_id, reason, user_id):
    if not reason.strip():
        raise ApiError(422, "reason_required", "请填写保留原因")
    current = collection_repository.get_result(conn, result_id)
    if not current:
        raise ApiError(404, "not_found", "采集结果不存在")
    if current["material_id"]:
        return current
    result = materialization_service.materialize(
        conn, result_id, user_id, allow_review=True
    )
    if result["status"] != "duplicate":
        conn.execute(
            text("UPDATE materials SET usage_status='pending_review' WHERE id=:id"),
            {"id": result["material_id"]},
        )
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="collection.result.retain",
        object_type="collection_result",
        object_id=result_id,
        detail={"reason": reason},
    )
    return collection_repository.get_result(conn, result_id)
