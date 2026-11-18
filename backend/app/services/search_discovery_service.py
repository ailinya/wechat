"""One fixed search per run; short transactions surround external requests.

Worker integration belongs to 3.22. A successful search (including zero hits)
is reusable. Unknown calls after a crash consume budget; no exactly-once
external billing promise is made.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from app.adapters.search_client import SearchClient, SearchError
from app.repositories import search_config_repository
from app.modules.collection.search_policy import build_query, normalize_domain


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def _check_run(conn, run_id):
    run = conn.execute(text("SELECT * FROM collection_runs WHERE id=:id FOR UPDATE"),
                       {"id": str(run_id)}).mappings().first()
    if not run:
        raise SearchError("run_not_found", "采集执行不存在")
    cancelled = conn.execute(text(
        "SELECT 1 FROM async_jobs WHERE resource_id=:id AND resource_type='collection_run' "
        "AND status='cancelled' LIMIT 1"
    ), {"id": str(run_id)}).first()
    if cancelled or run["end_reason"] == "cancelled":
        raise SearchError("cancelled", "采集执行已取消")
    return run


def discover(engine, run_id, task_snapshot: dict, *, client=None, now=None):
    """Discover from a frozen task snapshot; never requires source_ids.

    Returns persisted evidence with candidate IDs; does not materialize snippets
    or advance whole-run status. The pipeline owns subsequent stages.
    """
    now = now or (lambda: datetime.now(timezone.utc))
    token = str(uuid4())
    with engine.begin() as conn:
        run = _check_run(conn, run_id)
        existing = conn.execute(text("SELECT * FROM collection_searches WHERE run_id=:id"),
                                {"id": str(run_id)}).mappings().first()
        if existing and existing["status"] == "succeeded":
            return existing["evidence"]
        if not existing:
            if task_snapshot.get("mode") != "topic_search" or task_snapshot.get("source_ids"):
                raise SearchError("invalid_search_mode", "主题搜索不接受来源 ID")
            config = search_config_repository.get_config(conn, task_snapshot.get("search_config_id"))
            if not config or not config["enabled"]:
                raise SearchError("search_disabled", "搜索配置不存在或已禁用")
            try:
                query = build_query(task_snapshot.get("topic") or "", task_snapshot.get("keywords") or [])
                domains = [normalize_domain(d) for d in task_snapshot.get("allowed_domains", [])]
            except ValueError as exc:
                raise SearchError("invalid_search_input", str(exc)) from None
            end = run["started_at"] or now()
            start = end - timedelta(days=int(task_snapshot.get("time_range_days", 7)))
            limit = min(20, config["max_results"], int(task_snapshot.get("max_candidates", 100)))
            snapshot = {k: config[k] for k in (
                "id", "provider", "credential_ref", "enabled", "config_version", "max_results",
                "supports_domain_filter", "supports_date_filter",
            )}
            existing = conn.execute(text(
                "INSERT INTO collection_searches (run_id, search_config_id, config_snapshot, query, "
                "allowed_domains, window_start, window_end, max_results) VALUES "
                "(:run, :config, CAST(:snapshot AS jsonb), :query, CAST(:domains AS jsonb), :start, :end, :limit) "
                "RETURNING *"
            ), {"run": str(run_id), "config": str(config["id"]), "snapshot": _json(snapshot),
                "query": query, "domains": _json(domains), "start": start, "end": end, "limit": limit}
            ).mappings().one()
        search = dict(existing)
        if search["status"] == "running" and search["lease_until"] and search["lease_until"] > now():
            raise SearchError("search_in_progress", "搜索阶段正在执行")
        if run["status"] not in ("pending", "running"):
            raise SearchError("run_not_active", "执行记录不处于可执行状态")
        conn.execute(text(
            "UPDATE collection_searches SET status='running', lease_token=:token, "
            "lease_until=:lease, updated_at=now() WHERE id=:id"
        ), {"id": search["id"], "token": token, "lease": now() + timedelta(seconds=120)})

    def reserve_call():
        with engine.begin() as conn:
            _check_run(conn, run_id)
            current = conn.execute(text("SELECT * FROM collection_searches WHERE id=:id FOR UPDATE"),
                                   {"id": search["id"]}).mappings().one()
            if str(current["lease_token"]) != token:
                raise SearchError("search_lease_lost", "搜索阶段已由其他执行器接管")
            config = search_config_repository.get_config(conn, search["search_config_id"])
            if not config or not config["enabled"]:
                raise SearchError("search_disabled", "搜索配置已禁用")
            if current["attempts"] >= 3 or now() >= search["window_end"] + timedelta(seconds=600):
                raise SearchError("budget_exhausted", "搜索次数或执行时间预算已耗尽")
            conn.execute(text(
                "UPDATE collection_searches SET attempts=attempts+1, updated_at=now() WHERE id=:id"
            ), {"id": search["id"]})

    try:
        result = (client or SearchClient()).search(
            search["config_snapshot"], search["query"], allowed_domains=search["allowed_domains"],
            window_start=search["window_start"], window_end=search["window_end"],
            max_results=search["max_results"], remaining_calls=3-search["attempts"], before_attempt=reserve_call,
        )
        evidence = asdict(result)
        evidence["reason"] = "no_results" if result.empty else "completed"
        evidence["window_start"], evidence["window_end"] = str(search["window_start"]), str(search["window_end"])
        with engine.begin() as conn:
            _check_run(conn, run_id)
            current = conn.execute(text("SELECT * FROM collection_searches WHERE id=:id FOR UPDATE"),
                                   {"id": search["id"]}).mappings().one()
            if str(current["lease_token"]) != token:
                raise SearchError("search_lease_lost", "搜索阶段已由其他执行器接管")
            evidence["attempts"] = current["attempts"]
            for item in evidence["candidates"]:
                candidate_id = conn.execute(text(
                    "INSERT INTO collection_candidates (run_id, source, url, normalized_url, title, summary, "
                    "provider_rank, dedup_key) VALUES (:run, 'search', :url, :normalized, :title, :summary, "
                    ":rank, :hash) ON CONFLICT (run_id, normalized_url) DO UPDATE "
                    "SET normalized_url=EXCLUDED.normalized_url RETURNING id"
                ), {"run": str(run_id), "url": item["url"], "normalized": item["normalized_url"],
                    "title": item["title"], "summary": item["summary"], "rank": item["provider_rank"],
                    "hash": hashlib.sha256(item["normalized_url"].encode()).hexdigest()}).scalar_one()
                item["candidate_id"] = str(candidate_id)
            conn.execute(text(
                "UPDATE collection_searches SET status='succeeded', evidence=CAST(:evidence AS jsonb), "
                "error_code=NULL, lease_until=NULL, updated_at=now() WHERE id=:id"
            ), {"id": search["id"], "evidence": _json(evidence)})
        return evidence
    except SearchError as exc:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE collection_searches SET status='failed', error_code=:code, lease_until=NULL, "
                "updated_at=now() WHERE id=:id AND lease_token=:token"
            ), {"id": search["id"], "token": token, "code": exc.code})
        raise
