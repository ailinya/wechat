"""Persist bounded source discoveries after network reads complete."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import text

from app.errors import ApiError
from app.modules.collection.article_discovery import (
    DiscoveryError,
    SourceDiscovery,
    discover_source,
)


@dataclass
class DiscoveryRun:
    candidates: list[dict] = field(default_factory=list)
    source_failures: list[dict] = field(default_factory=list)
    pages_visited: int = 0
    stop_reasons: dict[str, str] = field(default_factory=dict)


def _merge(results: list[tuple[dict, SourceDiscovery]], limit: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for source, result in results:
        for candidate in result.candidates:
            row = merged.get(candidate.normalized_url)
            if row is None:
                if len(merged) >= limit:
                    continue
                row = {
                    "url": candidate.url,
                    "normalized_url": candidate.normalized_url,
                    "title": candidate.title,
                    "published_at": candidate.published_at,
                    "discoveries": [],
                }
                merged[candidate.normalized_url] = row
            elif not row["title"] and candidate.title:
                row["title"] = candidate.title
            for item in candidate.discoveries:
                record = {**asdict(item), "source_id": str(source["id"])}
                if record not in row["discoveries"]:
                    row["discoveries"].append(record)
    return list(merged.values())


def discover_run(
    engine,
    run_id,
    sources: list[dict],
    *,
    allowed_domains: list[str] | None = None,
    max_candidates: int = 100,
    max_pages: int = 5,
    fetcher=None,
    resolver=None,
) -> DiscoveryRun:
    if not 1 <= max_candidates <= 100 or not 1 <= max_pages <= 20:
        raise ApiError(422, "invalid_discovery_limit", "发现数量或分页上限超出允许范围")
    with engine.begin() as conn:
        run = (
            conn.execute(
                text("SELECT * FROM collection_runs WHERE id=:id"), {"id": str(run_id)}
            )
            .mappings()
            .first()
        )
        if not run or run["status"] not in ("pending", "running"):
            raise ApiError(409, "run_not_active", "执行记录不存在或已结束")
        cancelled = conn.execute(
            text(
                "SELECT 1 FROM async_jobs WHERE resource_id=:id AND resource_type='collection_run' "
                "AND status='cancelled' LIMIT 1"
            ),
            {"id": str(run_id)},
        ).first()
        if cancelled or run["end_reason"] == "cancelled":
            raise ApiError(409, "cancelled", "采集执行已取消")

    results, failures, pages, stop_reasons = [], [], 0, {}
    for source in sources:
        try:
            outcome = discover_source(
                source,
                allowed_domains=allowed_domains,
                max_candidates=max_candidates,
                max_pages=max_pages,
                fetcher=fetcher,
                resolver=resolver,
            )
            results.append((source, outcome))
            pages += outcome.pages_visited
            stop_reasons[str(source["id"])] = outcome.stop_reason
        except DiscoveryError as exc:
            failures.append(
                {
                    "source_id": str(source["id"]),
                    "code": exc.code,
                    "message": exc.message,
                }
            )

    candidates = _merge(results, max_candidates)
    persisted = []
    with engine.begin() as conn:
        run = (
            conn.execute(
                text(
                    "SELECT status, end_reason FROM collection_runs WHERE id=:id FOR UPDATE"
                ),
                {"id": str(run_id)},
            )
            .mappings()
            .first()
        )
        if (
            not run
            or run["status"] not in ("pending", "running")
            or run["end_reason"] == "cancelled"
        ):
            raise ApiError(409, "cancelled", "采集执行已结束，发现结果未保存")
        existing_urls = set(
            conn.execute(
                text(
                    "SELECT normalized_url FROM collection_candidates WHERE run_id=:id"
                ),
                {"id": str(run_id)},
            )
            .scalars()
            .all()
        )
        for candidate in candidates:
            if (
                candidate["normalized_url"] not in existing_urls
                and len(existing_urls) >= max_candidates
            ):
                continue
            existing_urls.add(candidate["normalized_url"])
            dedup_key = hashlib.sha256(candidate["normalized_url"].encode()).hexdigest()
            discovery_type = candidate["discoveries"][0]["kind"]
            published_at = None
            if candidate["published_at"]:
                try:
                    published_at = datetime.fromisoformat(candidate["published_at"])
                except ValueError:
                    pass
            candidate_id = conn.execute(
                text(
                    "INSERT INTO collection_candidates (run_id, source, url, normalized_url, title, summary, "
                    "provider_published_at, dedup_key) VALUES (:run, :source, :url, :normalized, :title, '', "
                    ":published, :dedup) ON CONFLICT (run_id, normalized_url) DO UPDATE SET "
                    "title=CASE WHEN collection_candidates.title='' THEN EXCLUDED.title ELSE collection_candidates.title END "
                    "RETURNING id"
                ),
                {
                    "run": str(run_id),
                    "source": discovery_type,
                    "url": candidate["url"],
                    "normalized": candidate["normalized_url"],
                    "title": candidate["title"],
                    "published": published_at,
                    "dedup": dedup_key,
                },
            ).scalar_one()
            for evidence in candidate["discoveries"]:
                conn.execute(
                    text(
                        "INSERT INTO collection_candidate_discoveries (candidate_id, source_id, discovery_type, "
                        "discovery_url, page_number, provenance_key, external_id, title, published_evidence) "
                        "VALUES (:candidate, :source, :kind, :url, :page, :key, :external, :title, :published) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "candidate": candidate_id,
                        "source": evidence["source_id"],
                        "kind": evidence["kind"],
                        "url": evidence["discovery_url"],
                        "page": evidence["page_number"],
                        "key": evidence["provenance_key"],
                        "external": evidence["external_id"],
                        "title": evidence["title"],
                        "published": evidence["published_evidence"],
                    },
                )
            persisted.append({**candidate, "candidate_id": str(candidate_id)})
    return DiscoveryRun(persisted, failures, pages, stop_reasons)
