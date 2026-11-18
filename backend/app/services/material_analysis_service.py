"""Fixed, tool-free analysis of immutable collection snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.adapters import model_client
from app.errors import ApiError
from app.repositories import model_config_repository

PROMPT_VERSION = "collection-analysis/1"
MAX_ATTEMPTS = 3
MAX_RUN_CALLS = 40


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _snapshot(conn, result_id):
    row = (
        conn.execute(
            text(
                "SELECT s.*, r.run_id, r.materialize_status FROM collection_snapshots s "
                "JOIN collection_results r ON r.id=s.result_id WHERE r.id=:id "
                "ORDER BY s.captured_at DESC, s.id DESC LIMIT 1"
            ),
            {"id": str(result_id)},
        )
        .mappings()
        .first()
    )
    if not row or not row["markdown"]:
        raise ApiError(409, "snapshot_unavailable", "没有可用于分析的正文快照")
    snapshot = dict(row)
    snapshot["content_hash"] = (
        snapshot["content_hash"]
        or hashlib.sha256(snapshot["markdown"].encode()).hexdigest()
    )
    return snapshot


def analyze_result(
    engine,
    result_id,
    model_config,
    *,
    topic=None,
    keywords=None,
    prompt_version=PROMPT_VERSION,
    client=None,
    target=None,
):
    """Reserve one durable attempt, release the transaction, then call the model."""
    context = {
        "topic": topic or "",
        "keywords": keywords or [],
        "purpose": "compare" if target else "analysis",
    }
    with engine.begin() as conn:
        config = model_config_repository.get_config(conn, model_config["id"])
        if not config or not config["enabled"] or config["purpose"] != "analysis":
            raise ApiError(409, "model_unavailable", "analysis 用途模型不可用或已禁用")
        config = model_client.effective_text_config(config)
        endpoint_hash = hashlib.sha256(config["endpoint"].encode()).hexdigest()
        snapshot = _snapshot(conn, result_id)
        run = (
            conn.execute(
                text("SELECT * FROM collection_runs WHERE id=:id FOR UPDATE"),
                {"id": snapshot["run_id"]},
            )
            .mappings()
            .one()
        )
        if (
            snapshot["materialize_status"] == "ignored"
            or run["end_reason"] == "cancelled"
        ):
            raise ApiError(409, "analysis_cancelled", "结果已忽略或执行已取消")
        if target:
            context["target_revision_id"] = str(target["revision_id"])
            context["target_hash"] = target["content_hash"]
        key_data = {
            "result_id": str(result_id),
            "hash": snapshot["content_hash"],
            "config_id": str(config["id"]),
            "config_version": config["config_version"],
            "model_name": config["model_name"],
            "endpoint_hash": endpoint_hash,
            "prompt": prompt_version,
            "context": context,
        }
        key = hashlib.sha256(_json(key_data).encode()).hexdigest()
        existing = (
            conn.execute(
                text(
                    "SELECT *, lease_until > now() AS leased FROM collection_analyses "
                    "WHERE logical_key=:key ORDER BY attempt DESC LIMIT 1"
                ),
                {"key": key},
            )
            .mappings()
            .first()
        )
        if existing and (
            existing["status"] == "succeeded"
            or (existing["status"] == "running" and existing["leased"])
        ):
            return {**dict(existing), "reused": True}
        attempt = (existing["attempt"] if existing else 0) + 1
        calls = conn.execute(
            text(
                "SELECT count(*) FROM collection_analyses a JOIN collection_results r ON r.id=a.result_id "
                "WHERE r.run_id=:run AND a.snapshot_id IS NOT NULL"
            ),
            {"run": snapshot["run_id"]},
        ).scalar_one()
        started = run["started_at"] or run["created_at"]
        if (
            attempt > MAX_ATTEMPTS
            or calls >= MAX_RUN_CALLS
            or (datetime.now(timezone.utc) - started).total_seconds() >= 600
        ):
            raise ApiError(
                409, "analysis_budget_exhausted", "分析调用或执行时间预算已耗尽"
            )
        if existing and existing["status"] == "running":
            conn.execute(
                text(
                    "UPDATE collection_analyses SET status='failed', error='analysis_lease_expired', "
                    "finished_at=now(), updated_at=now() WHERE id=:id"
                ),
                {"id": existing["id"]},
            )
        safe_config = {
            k: config[k]
            for k in (
                "id",
                "config_version",
                "model_name",
                "purpose",
                "max_input_tokens",
                "max_output_tokens",
                "timeout_seconds",
            )
        }
        safe_config["endpoint_hash"] = endpoint_hash
        analysis_id = conn.execute(
            text(
                "INSERT INTO collection_analyses (scope,result_id,status,model_config_id,prompt_version,"
                "attempt,logical_key,snapshot_id,input_hash,input_context,config_snapshot,lease_until,target_revision_id) "
                "VALUES ('collection_result',:result,'running',:model,:prompt,:attempt,:key,:snapshot,:hash,"
                "CAST(:context AS jsonb),CAST(:config AS jsonb),"
                "now()+make_interval(secs => :lease),:target) RETURNING id"
            ),
            {
                "result": str(result_id),
                "model": config["id"],
                "prompt": prompt_version,
                "attempt": attempt,
                "key": key,
                "snapshot": snapshot["id"],
                "hash": snapshot["content_hash"],
                "context": _json(context),
                "config": _json(safe_config),
                "lease": config["timeout_seconds"] + 30,
                "target": str(target["revision_id"]) if target else None,
            },
        ).scalar_one()

    client = client or model_client.ModelClient(max_attempts=1)
    suggestions, usage, error = None, None, None
    try:
        if target:
            outcome = client.compare_progress(
                config,
                prompt_version,
                target["content_markdown"],
                snapshot["markdown"],
                str(target["revision_id"]),
            )
        else:
            outcome = client.analysis(
                config,
                prompt_version,
                snapshot["markdown"],
                topic=topic,
                keywords=keywords or [],
            )
        suggestions = outcome["suggestions"].model_dump(mode="json")
        usage = outcome.get("usage") or None
    except model_client.ModelError as exc:
        error = exc.code
    except Exception:
        error = "analysis_internal_error"

    with engine.begin() as conn:
        current = _snapshot(conn, result_id)
        run_end_reason = conn.execute(
            text("SELECT end_reason FROM collection_runs WHERE id=:id"),
            {"id": snapshot["run_id"]},
        ).scalar_one()
        stale = (
            current["id"] != snapshot["id"]
            or current["materialize_status"] == "ignored"
            or run_end_reason == "cancelled"
        )
        if target:
            active_revision = conn.execute(
                text(
                    "SELECT current_revision_id FROM materials WHERE id=:id AND deleted_at IS NULL"
                ),
                {"id": target["material_id"]},
            ).scalar_one_or_none()
            stale = stale or str(active_revision) != str(target["revision_id"])
        conn.execute(
            text(
                "UPDATE collection_analyses SET status=:status, stale=:stale,suggestions=CAST(:suggestions AS jsonb),"
                "usage=CAST(:usage AS jsonb),error=:error,finished_at=now(),updated_at=now(),lease_until=NULL "
                "WHERE id=:id AND status='running'"
            ),
            {
                "id": analysis_id,
                "status": "failed" if error else "succeeded",
                "stale": stale,
                "suggestions": _json(suggestions) if suggestions else None,
                "usage": _json(usage) if usage else None,
                "error": error,
            },
        )
    return {
        "id": str(analysis_id),
        "status": "failed" if error else "succeeded",
        "stale": stale,
        "attempt": attempt,
        "suggestions": suggestions,
        "usage": usage,
        "error": error,
        "logical_key": key,
        "reused": False,
    }
