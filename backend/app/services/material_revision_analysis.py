"""Analyze a material's immutable revision without fetching its original source."""

import hashlib
import json
from sqlalchemy import text
from app.adapters.model_client import ModelClient, ModelError
from app.errors import ApiError
from app.repositories import model_config_repository


def analyze_material(
    engine, material_id, model_config_id, *, topic=None, keywords=None, client=None
):
    with engine.begin() as conn:
        material = (
            conn.execute(
                text(
                    "SELECT m.*,r.content_markdown,r.content_hash FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id WHERE m.id=:id FOR UPDATE OF m"
                ),
                {"id": str(material_id)},
            )
            .mappings()
            .first()
        )
        if (
            not material
            or material["deleted_at"]
            or material["usage_status"] == "archived"
        ):
            raise ApiError(409, "material_unavailable", "素材不可分析")
        config = model_config_repository.get_config(conn, model_config_id)
        if not config or not config["enabled"] or config["purpose"] != "analysis":
            raise ApiError(409, "model_unavailable", "分析模型不可用")
        context = {
            "topic": topic,
            "keywords": keywords or [],
            "metadata_version": material["metadata_version"],
        }
        key = hashlib.sha256(
            json.dumps(
                [
                    str(material["current_revision_id"]),
                    str(model_config_id),
                    config["config_version"],
                    topic,
                    keywords,
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        old = (
            conn.execute(
                text(
                    "SELECT *,lease_until>now() AS leased FROM collection_analyses WHERE logical_key=:key ORDER BY attempt DESC LIMIT 1"
                ),
                {"key": key},
            )
            .mappings()
            .first()
        )
        if old and (
            old["status"] == "succeeded" or old["status"] == "running" and old["leased"]
        ):
            return dict(old)
        attempt = old["attempt"] + 1 if old else 1
        if attempt > 3:
            raise ApiError(409, "analysis_budget_exhausted", "分析尝试预算已耗尽")
        aid = conn.execute(
            text(
                "INSERT INTO collection_analyses(scope,material_id,material_revision_id,model_config_id,prompt_version,status,logical_key,attempt,input_hash,input_context,config_snapshot,lease_until) VALUES ('material_revision',:material,:revision,:model,'material-analysis/1','running',:key,:attempt,:hash,CAST(:context AS jsonb),CAST(:config AS jsonb),now()+make_interval(secs=>:lease)) RETURNING id"
            ),
            {
                "material": str(material_id),
                "revision": material["current_revision_id"],
                "model": str(model_config_id),
                "key": key,
                "attempt": attempt,
                "hash": material["content_hash"],
                "context": json.dumps(context, ensure_ascii=False),
                "config": json.dumps({"config_version": config["config_version"]}),
                "lease": config["timeout_seconds"] + 30,
            },
        ).scalar_one()
    suggestions, usage, error = None, None, None
    try:
        output = (client or ModelClient(max_attempts=1)).analysis(
            config,
            "material-analysis/1",
            material["content_markdown"],
            topic=topic,
            keywords=keywords,
        )
        suggestions = output["suggestions"].model_dump(mode="json")
        usage = output.get("usage") or None
    except ModelError as exc:
        error = exc.code
    with engine.begin() as conn:
        current = (
            conn.execute(
                text(
                    "SELECT current_revision_id,deleted_at,usage_status FROM materials WHERE id=:id"
                ),
                {"id": str(material_id)},
            )
            .mappings()
            .one()
        )
        stale = (
            current["current_revision_id"] != material["current_revision_id"]
            or bool(current["deleted_at"])
            or current["usage_status"] == "archived"
        )
        conn.execute(
            text(
                "UPDATE collection_analyses SET status=:status,stale=:stale,suggestions=CAST(:suggestions AS jsonb),usage=CAST(:usage AS jsonb),error=:error,finished_at=now(),updated_at=now(),lease_until=NULL WHERE id=:id"
            ),
            {
                "id": aid,
                "status": "failed" if error else "succeeded",
                "stale": stale,
                "suggestions": json.dumps(suggestions, ensure_ascii=False)
                if suggestions
                else None,
                "usage": json.dumps(usage) if usage else None,
                "error": error,
            },
        )
    return {
        "id": str(aid),
        "status": "failed" if error else "succeeded",
        "error": error,
        "stale": stale,
    }


def material_analysis_job(engine, job):
    result = analyze_material(engine, **job["payload"])
    if result["status"] == "failed":
        raise ApiError(422, result["error"], "素材分析失败")
    return result
