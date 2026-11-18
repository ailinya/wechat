"""Bounded resumable collection pipeline with transactions around each stage."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from app.adapters import source_fetch
from app.errors import ApiError
from app.modules.async_execution.registry import JobCancelled
from app.repositories import collection_repository as repo, material_repository
from app.services import (
    article_discovery_service,
    article_extraction_service,
    material_analysis_service,
    material_comparison_service,
    materialization_service,
    outbox_service,
    search_discovery_service,
)


def _check(conn, run_id, token):
    run = (
        conn.execute(
            text("SELECT * FROM collection_runs WHERE id=:id FOR UPDATE"),
            {"id": run_id},
        )
        .mappings()
        .one()
    )
    job_status = conn.execute(
        text("SELECT status FROM async_jobs WHERE id=:id FOR UPDATE"),
        {"id": run["async_job_id"]},
    ).scalar_one_or_none()
    if job_status == "cancelled" or run["end_reason"] == "cancelled":
        raise JobCancelled()
    if str(run["lease_token"]) != token:
        raise ApiError(409, "run_lease_lost", "采集运行已由其他执行器接管")
    if (datetime.now(timezone.utc) - run["started_at"]).total_seconds() >= 600:
        raise ApiError(409, "budget_exhausted", "采集执行时间预算已耗尽")
    return run


def _stage(engine, run_id, token, candidate_id, stage, operation):
    with engine.begin() as conn:
        _check(conn, run_id, token)
        last = (
            conn.execute(
                text(
                    "SELECT * FROM collection_stage_attempts WHERE candidate_id=:id AND stage=:stage ORDER BY attempt DESC LIMIT 1"
                ),
                {"id": candidate_id, "stage": stage},
            )
            .mappings()
            .first()
        )
        if last and last["status"] == "succeeded":
            return
        attempt = last["attempt"] + 1 if last else 1
        if attempt > 3:
            raise ApiError(409, "budget_exhausted", "阶段重试预算已耗尽")
        stage_id = conn.execute(
            text(
                "INSERT INTO collection_stage_attempts(candidate_id,stage,status,attempt,started_at) VALUES (:id,:stage,'running',:attempt,now()) RETURNING id"
            ),
            {"id": candidate_id, "stage": stage, "attempt": attempt},
        ).scalar_one()
    try:
        operation()
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE collection_stage_attempts SET status='failed',error=:error,finished_at=now() WHERE id=:id"
                ),
                {"id": stage_id, "error": getattr(exc, "code", type(exc).__name__)},
            )
            conn.execute(
                text(
                    "UPDATE collection_candidates SET status='failed',error=:error WHERE id=:id"
                ),
                {"id": candidate_id, "error": getattr(exc, "code", type(exc).__name__)},
            )
        raise
    with engine.begin() as conn:
        _check(conn, run_id, token)
        conn.execute(
            text(
                "UPDATE collection_stage_attempts SET status='succeeded',finished_at=now(),error=NULL WHERE id=:id"
            ),
            {"id": stage_id},
        )


def execute_collection(
    engine,
    run_id,
    *,
    fetcher=None,
    resolver=None,
    search_client=None,
    model_client=None,
):
    run_id, token = str(run_id), str(uuid4())
    with engine.begin() as conn:
        run = (
            conn.execute(
                text("SELECT * FROM collection_runs WHERE id=:id FOR UPDATE"),
                {"id": run_id},
            )
            .mappings()
            .one()
        )
        if run["status"] == "succeeded":
            return {"status": "succeeded", "reused": True}
        if run["lease_until"] and run["lease_until"] > datetime.now(timezone.utc):
            return {"status": "running", "reused": True}
        config = run["config_snapshot"] or repo.get_task(conn, run["task_id"])
        if "sources" not in config:
            config["sources"] = repo.task_sources(conn, run["task_id"])
        conn.execute(
            text(
                "UPDATE collection_runs SET status='running',started_at=COALESCE(started_at,now()),lease_token=:token,lease_until=now()+interval '10 minutes',config_snapshot=CAST(:config AS jsonb) WHERE id=:id"
            ),
            {"id": run_id, "token": token, "config": json.dumps(config, default=str)},
        )

    def limited_fetch(url):
        with engine.begin() as conn:
            _check(conn, run_id, token)
        if fetcher:
            return fetcher(url)
        return source_fetch.fetch(
            url,
            resolver=resolver,
            allowed_domains=config.get("allowed_domains") or None,
        )

    end_reason, error = "completed", None
    try:
        with engine.begin() as conn:
            run = _check(conn, run_id, token)
        if not run["discovery_completed"]:
            if config.get("mode") == "topic_search":
                search_discovery_service.discover(
                    engine, run_id, config, client=search_client
                )
            else:
                state = dict(run["discovery_state"])
                for source in config["sources"]:
                    sid = str(source["id"])
                    previous = state.get(sid, {})
                    if previous.get("status") == "succeeded":
                        continue
                    if previous.get("attempt", 0) >= 3:
                        error = "discovery_budget_exhausted"
                        end_reason = "budget_exhausted"
                        continue
                    state[sid] = {
                        "status": "running",
                        "attempt": previous.get("attempt", 0) + 1,
                        "errors": [],
                    }
                    with engine.begin() as conn:
                        _check(conn, run_id, token)
                        conn.execute(
                            text(
                                "UPDATE collection_runs SET discovery_state=CAST(:state AS jsonb) WHERE id=:id"
                            ),
                            {"id": run_id, "state": json.dumps(state)},
                        )
                    discoveries = article_discovery_service.discover_run(
                        engine,
                        run_id,
                        [source],
                        allowed_domains=config.get("allowed_domains"),
                        max_candidates=config.get("max_candidates", 100),
                        max_pages=config.get("max_pages", 5),
                        fetcher=limited_fetch,
                        resolver=resolver,
                    )
                    state[sid] = {
                        "status": "failed"
                        if discoveries.source_failures
                        else "succeeded",
                        "attempt": previous.get("attempt", 0) + 1,
                        "errors": discoveries.source_failures,
                        "stop_reasons": discoveries.stop_reasons,
                    }
                    if discoveries.source_failures:
                        error = "source_discovery_failed"
                    with engine.begin() as conn:
                        _check(conn, run_id, token)
                        conn.execute(
                            text(
                                "UPDATE collection_runs SET discovery_state=CAST(:state AS jsonb) WHERE id=:id"
                            ),
                            {"id": run_id, "state": json.dumps(state)},
                        )
            with engine.begin() as conn:
                _check(conn, run_id, token)
                conn.execute(
                    text(
                        "UPDATE collection_runs SET discovery_completed=:completed,error=:error WHERE id=:id"
                    ),
                    {"id": run_id, "error": error, "completed": error is None},
                )
        with engine.connect() as conn:
            candidates = (
                conn.execute(
                    text(
                        "SELECT * FROM collection_candidates WHERE run_id=:id ORDER BY created_at,id LIMIT :limit"
                    ),
                    {"id": run_id, "limit": config.get("max_fetch", 20)},
                )
                .mappings()
                .all()
            )
        for item in candidates:
            candidate = dict(item)
            cid = candidate["id"]

            def fetch_one():
                response = limited_fetch(
                    candidate["normalized_url"] or candidate["url"]
                )
                source_fetch.validate_url(response.final_url, resolver=resolver)
                from app.modules.collection.search_policy import normalize_url

                normalize_url(response.final_url, config.get("allowed_domains") or None)
                with engine.begin() as conn:
                    _check(conn, run_id, token)
                    existing = conn.execute(
                        text(
                            "SELECT result_id FROM collection_candidates WHERE id=:id"
                        ),
                        {"id": cid},
                    ).scalar_one()
                    if not existing:
                        source = conn.execute(
                            text(
                                "SELECT source_id FROM collection_candidate_discoveries WHERE candidate_id=:id LIMIT 1"
                            ),
                            {"id": cid},
                        ).scalar_one_or_none()
                        result = repo.insert_result(
                            conn,
                            run_id=run_id,
                            source_id=source,
                            title=candidate["title"] or "未命名文章",
                            url=response.final_url,
                            raw_content=response.content,
                            dedup_key=hashlib.sha256(
                                (
                                    candidate["normalized_url"] or candidate["url"]
                                ).encode()
                            ).hexdigest(),
                        )
                        existing = result["id"]
                    conn.execute(
                        text(
                            "INSERT INTO collection_snapshots(candidate_id,result_id,raw_content) VALUES (:candidate,:result,:raw)"
                        ),
                        {"candidate": cid, "result": existing, "raw": response.content},
                    )
                    conn.execute(
                        text(
                            "UPDATE collection_results SET raw_content=:raw,parse_status='pending' WHERE id=:id"
                        ),
                        {"id": existing, "raw": response.content},
                    )
                    conn.execute(
                        text(
                            "UPDATE collection_candidates SET result_id=:result,status='fetched',http_status=:status,content_type=:type,error=NULL WHERE id=:id"
                        ),
                        {
                            "id": cid,
                            "result": existing,
                            "status": response.status_code,
                            "type": response.content_type,
                        },
                    )
                if not 200 <= response.status_code < 300:
                    raise ApiError(422, "http_error", f"HTTP {response.status_code}")

            try:
                _stage(engine, run_id, token, cid, "fetch", fetch_one)
                with engine.connect() as conn:
                    candidate = dict(
                        conn.execute(
                            text("SELECT * FROM collection_candidates WHERE id=:id"),
                            {"id": cid},
                        )
                        .mappings()
                        .one()
                    )
                result_id = candidate["result_id"]

                def parse_one():
                    with engine.begin() as conn:
                        run = _check(conn, run_id, token)
                        raw = repo.get_result(conn, result_id)["raw_content"] or ""
                    outcome = article_extraction_service.extract_article(
                        raw,
                        url=candidate["url"],
                        content_type=candidate["content_type"],
                        status_code=candidate["http_status"],
                        provider_published_at=candidate["provider_published_at"]
                        if candidate["source"] == "rss"
                        else None,
                        run_started_at=run["started_at"],
                        time_range_days=config.get("time_range_days", 7),
                        keywords=config.get("keywords"),
                    )
                    with engine.begin() as conn:
                        _check(conn, run_id, token)
                        article_extraction_service.persist_candidate_extraction(
                            conn, cid, raw, outcome
                        )
                        conn.execute(
                            text(
                                "UPDATE collection_snapshots SET result_id=:result WHERE candidate_id=:id AND result_id IS NULL"
                            ),
                            {"id": cid, "result": result_id},
                        )
                        conn.execute(
                            text(
                                "UPDATE collection_results SET title=COALESCE(:title,title),published_at=:published,parse_status=:parse,error=:error WHERE id=:id"
                            ),
                            {
                                "id": result_id,
                                "title": outcome.title,
                                "published": outcome.published_at,
                                "parse": "failed"
                                if outcome.status == "failed"
                                else "parsed",
                                "error": outcome.reason,
                            },
                        )
                    if outcome.status == "failed":
                        raise ApiError(
                            422,
                            outcome.error_code or "parse_failed",
                            outcome.reason or "解析失败",
                        )

                _stage(engine, run_id, token, cid, "parse", parse_one)
                with engine.connect() as conn:
                    current = (
                        conn.execute(
                            text("SELECT * FROM collection_candidates WHERE id=:id"),
                            {"id": cid},
                        )
                        .mappings()
                        .one()
                    )
                if current["status"] in (
                    "filtered",
                    "review_required",
                    "materialized",
                    "duplicate",
                ):
                    continue
                with engine.connect() as conn:
                    saved = conn.execute(
                        text(
                            "SELECT content_hash FROM collection_snapshots WHERE result_id=:id AND markdown IS NOT NULL ORDER BY captured_at DESC,id DESC LIMIT 1"
                        ),
                        {"id": result_id},
                    ).scalar_one()
                    exact_before_analysis = (
                        material_repository.find_material_by_content_hash(conn, saved)
                    )
                if config.get("analysis_enabled") and not exact_before_analysis:

                    def analyze_one():
                        outcome = material_analysis_service.analyze_result(
                            engine,
                            result_id,
                            {"id": config["analysis_model_config_id"]},
                            topic=config.get("topic"),
                            keywords=config.get("keywords"),
                            client=model_client,
                        )
                        if outcome["status"] != "succeeded" or outcome.get("stale"):
                            raise ApiError(
                                422,
                                outcome.get("error") or "analysis_failed",
                                "素材分析尚未成功",
                            )

                    _stage(engine, run_id, token, cid, "analyze", analyze_one)
                with engine.begin() as conn:
                    _check(conn, run_id, token)
                    conn.execute(
                        text(
                            "UPDATE collection_candidates SET status='parsed',error=NULL WHERE id=:id AND status='failed'"
                        ),
                        {"id": cid},
                    )

                def decide_one():
                    decision = None
                    with engine.connect() as conn:
                        snapshot = (
                            conn.execute(
                                text(
                                    "SELECT * FROM collection_snapshots WHERE result_id=:id AND markdown IS NOT NULL ORDER BY captured_at DESC,id DESC LIMIT 1"
                                ),
                                {"id": result_id},
                            )
                            .mappings()
                            .one()
                        )
                        exact = material_repository.find_material_by_content_hash(
                            conn, snapshot["content_hash"]
                        )
                    if config.get("analysis_enabled") and not exact:
                        analysis = material_analysis_service.analyze_result(
                            engine,
                            result_id,
                            {"id": config["analysis_model_config_id"]},
                            topic=config.get("topic"),
                            keywords=config.get("keywords"),
                            client=model_client,
                        )
                        if analysis["status"] != "succeeded":
                            raise ApiError(
                                422,
                                analysis.get("error") or "analysis_failed",
                                "素材分析尚未成功",
                            )
                        if analysis.get("stale") or analysis["suggestions"][
                            "relevance"
                        ] in ("irrelevant", "uncertain"):
                            with engine.begin() as conn:
                                _check(conn, run_id, token)
                                conn.execute(
                                    text(
                                        "UPDATE collection_candidates SET status='review_required',error='analysis_review_required' WHERE id=:id"
                                    ),
                                    {"id": cid},
                                )
                            return
                        comparison = material_comparison_service.compare_result_history(
                            engine,
                            result_id,
                            {"id": config["analysis_model_config_id"]},
                            topic=config.get("topic"),
                            keywords=config.get("keywords"),
                            client=model_client,
                        )
                        if comparison["status"] == "review_required":
                            with engine.begin() as conn:
                                _check(conn, run_id, token)
                                conn.execute(
                                    text(
                                        "UPDATE collection_candidates SET status='review_required',error='comparison_review_required' WHERE id=:id"
                                    ),
                                    {"id": cid},
                                )
                            return
                        if comparison["status"] == "new_progress":
                            decision = {
                                "analysis_id": next(
                                    row["analysis_id"]
                                    for row in comparison["comparisons"]
                                    if row["verdict"] == "new_progress"
                                )
                            }
                    if config.get("auto_materialize"):
                        with engine.begin() as conn:
                            _check(conn, run_id, token)
                            result = materialization_service.materialize(
                                conn, result_id, None, progress_decision=decision
                            )
                            conn.execute(
                                text(
                                    "UPDATE collection_candidates SET status=:status,error=NULL WHERE id=:id"
                                ),
                                {
                                    "id": cid,
                                    "status": "duplicate"
                                    if result["status"] == "duplicate"
                                    else "materialized",
                                },
                            )
                            revision = material_repository.current_revision(
                                conn, result["material_id"]
                            )
                            material_status = conn.execute(
                                text("SELECT usage_status FROM materials WHERE id=:id"),
                                {"id": result["material_id"]},
                            ).scalar_one()
                            if material_status == "archived":
                                return
                            key = hashlib.sha256(
                                f"material:{result['material_id']}:{revision['id']}".encode()
                            ).hexdigest()
                            conn.execute(
                                text(
                                    "UPDATE materials SET usage_status='ready_to_use' WHERE id=:id AND usage_status='pending_review'"
                                ),
                                {"id": result["material_id"]},
                            )
                            if (
                                config.get("analysis_enabled")
                                and config.get("analysis_apply_policy") == "fill_empty"
                                and not exact
                            ):
                                from app.services.analysis_management_service import (
                                    apply_analysis,
                                )
                                from app.schemas.analysis import AnalysisApplyIn

                                metadata = conn.execute(
                                    text(
                                        "SELECT metadata_version FROM materials WHERE id=:id"
                                    ),
                                    {"id": result["material_id"]},
                                ).scalar_one()
                                apply_analysis(
                                    conn,
                                    analysis["id"],
                                    AnalysisApplyIn(
                                        base_metadata_version=metadata,
                                        apply=["summary", "category", "tags"],
                                    ),
                                    None,
                                    fill_empty=True,
                                )
                            event = conn.execute(
                                text(
                                    "INSERT INTO material_ready_events(material_id,material_revision_id,event_key) VALUES (:material,:revision,:key) ON CONFLICT DO NOTHING RETURNING id"
                                ),
                                {
                                    "material": result["material_id"],
                                    "revision": revision["id"],
                                    "key": key,
                                },
                            ).scalar_one_or_none()
                            if event:
                                outbox_service.publish_event(
                                    conn,
                                    "material.ready",
                                    "material",
                                    result["material_id"],
                                    payload={
                                        "material_id": result["material_id"],
                                        "revision_id": str(revision["id"]),
                                    },
                                )

                _stage(engine, run_id, token, cid, "materialize", decide_one)
            except JobCancelled:
                raise
            except Exception as exc:
                error = getattr(exc, "code", type(exc).__name__)
                if error in ("budget_exhausted", "analysis_budget_exhausted"):
                    end_reason = "budget_exhausted"
                    break
    except JobCancelled:
        end_reason, error = "cancelled", "cancelled"
    except Exception as exc:
        end_reason, error = "error", getattr(exc, "code", type(exc).__name__)
        if error in ("budget_exhausted", "analysis_budget_exhausted"):
            end_reason = "budget_exhausted"
    with engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT status,result_id FROM collection_candidates WHERE run_id=:id"
                ),
                {"id": run_id},
            )
            .mappings()
            .all()
        )
        fetched = sum(bool(row["result_id"]) for row in rows)
        failed = sum(row["status"] == "failed" for row in rows)
        parsed = conn.execute(
            text(
                "SELECT count(*) FROM collection_results WHERE run_id=:id AND parse_status='parsed'"
            ),
            {"id": run_id},
        ).scalar_one()
        analyzed = conn.execute(
            text(
                "SELECT count(DISTINCT a.result_id) FROM collection_analyses a JOIN collection_results r ON r.id=a.result_id WHERE r.run_id=:id AND a.status='succeeded' AND NOT a.stale AND a.input_context->>'purpose'='analysis'"
            ),
            {"id": run_id},
        ).scalar_one()
        if len(rows) > config.get("max_fetch", 20) and end_reason == "completed":
            end_reason, error = "budget_exhausted", "fetch_limit_reached"
        status = "partial" if error and fetched else "failed" if error else "succeeded"
        conn.execute(
            text(
                "UPDATE collection_runs SET status=:status,end_reason=:end,error=:error,discovered_count=:discovered,fetched_count=:fetched,parsed_count=:parsed,analyzed_count=:analyzed,failed_count=:failed,filtered_count=:filtered,review_required_count=:review,materialized_count=:materialized,finished_at=now(),lease_until=NULL WHERE id=:id AND lease_token=:token"
            ),
            {
                "id": run_id,
                "token": token,
                "status": status,
                "end": end_reason,
                "error": error
                or (
                    "no_results"
                    if not rows and config.get("mode") == "topic_search"
                    else None
                ),
                "discovered": len(rows),
                "fetched": fetched,
                "parsed": parsed,
                "analyzed": analyzed,
                "failed": failed,
                "filtered": sum(r["status"] == "filtered" for r in rows),
                "review": sum(r["status"] == "review_required" for r in rows),
                "materialized": sum(
                    r["status"] in ("materialized", "duplicate") for r in rows
                ),
            },
        )
    if end_reason == "cancelled":
        raise JobCancelled()
    return {"status": status, "end_reason": end_reason, "error": error}


def collection_job_handler(engine, job):
    return execute_collection(engine, job["payload"]["run_id"])
