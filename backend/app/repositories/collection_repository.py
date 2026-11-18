"""Collection-source persistence (task 3.4)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def list_sources(
    conn: Connection,
    page: int,
    page_size: int,
    keyword: str | None = None,
) -> tuple[list[dict], int]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {}
    if keyword:
        where.append("(name ILIKE :kw OR base_url ILIKE :kw)")
        params["kw"] = f"%{keyword}%"
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT count(*) FROM collection_sources WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT * FROM collection_sources WHERE {clause} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def get_source(conn: Connection, source_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM collection_sources WHERE id = :id AND deleted_at IS NULL"),
        {"id": str(source_id)},
    ).mappings().first()
    return dict(row) if row else None


def source_with_name_exists(
    conn: Connection, name: str, exclude_id: UUID | str | None = None
) -> bool:
    params: dict[str, Any] = {"name": name}
    clause = "name = :name AND deleted_at IS NULL"
    if exclude_id is not None:
        clause += " AND id <> :exclude"
        params["exclude"] = str(exclude_id)
    return (
        conn.execute(
            text(f"SELECT 1 FROM collection_sources WHERE {clause} LIMIT 1"), params
        ).first()
        is not None
    )


def create_source(
    conn: Connection,
    *,
    name: str,
    source_type: str,
    base_url: str,
    description: str,
    enabled: bool,
    created_by: UUID | str | None,
    config: dict | None = None,
    page_kind: str = "article",
    article_link_selector: str | None = None,
    next_page_selector: str | None = None,
) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO collection_sources "
            "(name, source_type, base_url, description, enabled, config, created_by, page_kind, "
            " article_link_selector, next_page_selector) "
            "VALUES (:name, :type, :url, :description, :enabled, CAST(:config AS jsonb), :created_by, "
            " :page_kind, :article_link_selector, :next_page_selector) "
            "RETURNING *"
        ),
        {
            "name": name,
            "type": source_type,
            "url": base_url,
            "description": description,
            "enabled": enabled,
            "config": json.dumps(config or {}, ensure_ascii=False),
            "created_by": str(created_by) if created_by else None,
            "page_kind": page_kind,
            "article_link_selector": article_link_selector,
            "next_page_selector": next_page_selector,
        },
    ).mappings().one()
    return dict(row)


def update_source(
    conn: Connection,
    source_id: UUID | str,
    *,
    name: str,
    source_type: str,
    base_url: str,
    description: str,
    enabled: bool,
    page_kind: str = "article",
    article_link_selector: str | None = None,
    next_page_selector: str | None = None,
) -> dict | None:
    row = conn.execute(
        text(
            "UPDATE collection_sources SET name = :name, source_type = :type, "
            "base_url = :url, description = :description, enabled = :enabled, "
            "page_kind = :page_kind, article_link_selector = :article_link_selector, "
            "next_page_selector = :next_page_selector, updated_at = now() "
            "WHERE id = :id AND deleted_at IS NULL RETURNING *"
        ),
        {
            "id": str(source_id),
            "name": name,
            "type": source_type,
            "url": base_url,
            "description": description,
            "enabled": enabled,
            "page_kind": page_kind,
            "article_link_selector": article_link_selector,
            "next_page_selector": next_page_selector,
        },
    ).mappings().first()
    return dict(row) if row else None


def soft_delete_source(conn: Connection, source_id: UUID | str) -> dict | None:
    row = conn.execute(
        text(
            "UPDATE collection_sources SET deleted_at = now(), enabled = FALSE, "
            "status = 'inactive', updated_at = now() "
            "WHERE id = :id AND deleted_at IS NULL RETURNING *"
        ),
        {"id": str(source_id)},
    ).mappings().first()
    return dict(row) if row else None


def set_check_result(
    conn: Connection,
    source_id: UUID | str,
    *,
    reachable: bool,
) -> None:
    now = "now()"
    if reachable:
        conn.execute(
            text(
                f"UPDATE collection_sources SET last_checked_at = {now}, "
                f"last_success_at = {now}, status = 'active', updated_at = {now} WHERE id = :id"
            ),
            {"id": str(source_id)},
        )
    else:
        conn.execute(
            text(
                f"UPDATE collection_sources SET last_checked_at = {now}, "
                f"status = 'unavailable', updated_at = {now} WHERE id = :id"
            ),
            {"id": str(source_id)},
        )


# --- tasks ---


def list_tasks(
    conn: Connection, page: int, page_size: int, status: str | None = None
) -> tuple[list[dict], int]:
    where, params = ["TRUE"], {}
    if status:
        where.append("status = :status")
        params["status"] = status
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT count(*) FROM collection_tasks WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT * FROM collection_tasks WHERE {clause} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def get_task(conn: Connection, task_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM collection_tasks WHERE id = :id"), {"id": str(task_id)}
    ).mappings().first()
    return dict(row) if row else None


def task_with_name_exists(
    conn: Connection, name: str, exclude_id: UUID | str | None = None
) -> bool:
    params: dict[str, Any] = {"name": name}
    clause = "name = :name"
    if exclude_id is not None:
        clause += " AND id <> :exclude"
        params["exclude"] = str(exclude_id)
    return (
        conn.execute(text(f"SELECT 1 FROM collection_tasks WHERE {clause} LIMIT 1"), params).first()
        is not None
    )


def active_source_ids(conn: Connection, source_ids: list[UUID | str]) -> list[str]:
    if not source_ids:
        return []
    ids = [str(value) for value in source_ids]
    rows = conn.execute(
        text(
            "SELECT id FROM collection_sources "
            "WHERE id = ANY(:ids) AND deleted_at IS NULL AND enabled = TRUE"
        ),
        {"ids": ids},
    ).scalars().all()
    return [str(row) for row in rows]


def _sync_task_sources(conn: Connection, task_id: str, source_ids: list[str]) -> None:
    conn.execute(
        text("DELETE FROM collection_task_sources WHERE task_id = :id"), {"id": task_id}
    )
    for source_id in source_ids:
        conn.execute(
            text(
                "INSERT INTO collection_task_sources (task_id, source_id) "
                "VALUES (:task, :source) ON CONFLICT DO NOTHING"
            ),
            {"task": task_id, "source": source_id},
        )


def create_task(
    conn: Connection,
    *,
    name: str,
    keywords: list[str],
    time_range_days: int,
    schedule_frequency: str,
    schedule_cron_expr: str | None,
    timezone: str,
    auto_materialize: bool,
    auto_create: bool,
    source_ids: list[str],
    created_by: UUID | str | None,
) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO collection_tasks "
            "(name, keywords, time_range_days, schedule_frequency, schedule_cron_expr, "
            " timezone, auto_materialize, auto_create, created_by) "
            "VALUES (:name, CAST(:keywords AS jsonb), :days, :freq, :cron, :tz, "
            " :auto_materialize, :auto_create, :created_by) RETURNING *"
        ),
        {
            "name": name,
            "keywords": json.dumps(keywords, ensure_ascii=False),
            "days": time_range_days,
            "freq": schedule_frequency,
            "cron": schedule_cron_expr,
            "tz": timezone,
            "auto_materialize": auto_materialize,
            "auto_create": auto_create,
            "created_by": str(created_by) if created_by else None,
        },
    ).mappings().one()
    task = dict(row)
    _sync_task_sources(conn, str(task["id"]), source_ids)
    task["source_ids"] = source_ids
    return task


def update_task(
    conn: Connection,
    task_id: UUID | str,
    *,
    name: str,
    keywords: list[str],
    time_range_days: int,
    schedule_frequency: str,
    schedule_cron_expr: str | None,
    timezone: str,
    auto_materialize: bool,
    auto_create: bool,
    source_ids: list[str] | None,
) -> dict | None:
    row = conn.execute(
        text(
            "UPDATE collection_tasks SET name = :name, keywords = CAST(:keywords AS jsonb), "
            "time_range_days = :days, schedule_frequency = :freq, schedule_cron_expr = :cron, "
            "timezone = :tz, auto_materialize = :auto_materialize, auto_create = :auto_create, "
            "updated_at = now() WHERE id = :id RETURNING *"
        ),
        {
            "id": str(task_id),
            "name": name,
            "keywords": json.dumps(keywords, ensure_ascii=False),
            "days": time_range_days,
            "freq": schedule_frequency,
            "cron": schedule_cron_expr,
            "tz": timezone,
            "auto_materialize": auto_materialize,
            "auto_create": auto_create,
        },
    ).mappings().first()
    if not row:
        return None
    if source_ids is not None:
        _sync_task_sources(conn, str(task_id), source_ids)
    task = dict(row)
    task["source_ids"] = source_ids
    return task


def set_task_status(conn: Connection, task_id: UUID | str, status: str) -> dict | None:
    row = conn.execute(
        text(
            "UPDATE collection_tasks SET status = :status, updated_at = now() "
            "WHERE id = :id RETURNING *"
        ),
        {"id": str(task_id), "status": status},
    ).mappings().first()
    return dict(row) if row else None


def task_sources(conn: Connection, task_id: UUID | str) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT s.id, s.name FROM collection_sources s "
            "JOIN collection_task_sources ts ON ts.source_id = s.id "
            "WHERE ts.task_id = :task AND s.deleted_at IS NULL ORDER BY s.name"
        ),
        {"task": str(task_id)},
    ).mappings().all()
    return [dict(row) for row in rows]


def list_scheduled_active_tasks(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT * FROM collection_tasks "
            "WHERE status = 'active' AND schedule_frequency <> 'manual' "
            "ORDER BY created_at"
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def run_in_window_exists(conn: Connection, task_id: UUID | str, window_key: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM collection_runs "
                "WHERE task_id = :task AND window_key = :window LIMIT 1"
            ),
            {"task": str(task_id), "window": window_key},
        ).first()
        is not None
    )


def set_lease(conn: Connection, task_id: UUID | str, window_key: str, seconds: int) -> None:
    conn.execute(
        text(
            "UPDATE collection_tasks SET last_window_key = :window, "
            "lease_until = now() + make_interval(secs => :seconds) WHERE id = :id"
        ),
        {"id": str(task_id), "window": window_key, "seconds": seconds},
    )


# --- runs ---


def create_run(
    conn: Connection,
    *,
    task_id: UUID | str,
    trigger: str,
    window_key: str | None = None,
    async_job_id: UUID | str | None = None,
) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO collection_runs (task_id, trigger, window_key, async_job_id) "
            "VALUES (:task, :trigger, :window, :job) RETURNING *"
        ),
        {
            "task": str(task_id),
            "trigger": trigger,
            "window": window_key,
            "job": str(async_job_id) if async_job_id else None,
        },
    ).mappings().one()
    return dict(row)


def list_runs(
    conn: Connection,
    page: int,
    page_size: int,
    task_id: UUID | str | None = None,
    status: str | None = None,
) -> tuple[list[dict], int]:
    where, params = ["TRUE"], {}
    if task_id:
        where.append("task_id = :task")
        params["task"] = str(task_id)
    if status:
        where.append("status = :status")
        params["status"] = status
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT count(*) FROM collection_runs WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT * FROM collection_runs WHERE {clause} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def get_run(conn: Connection, run_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM collection_runs WHERE id = :id"), {"id": str(run_id)}
    ).mappings().first()
    return dict(row) if row else None


def update_run_counters(
    conn: Connection,
    run_id: UUID | str,
    *,
    status: str,
    fetched_count: int = 0,
    parsed_count: int = 0,
    materialized_count: int = 0,
    failed_count: int = 0,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    assignments = [
        "status = :status",
        "fetched_count = :fetched",
        "parsed_count = :parsed",
        "materialized_count = :materialized",
        "failed_count = :failed",
        "error = :error",
        "updated_at = now()",
    ]
    if started:
        assignments.append("started_at = COALESCE(started_at, now())")
    if finished:
        assignments.append("finished_at = now()")
    params: dict[str, Any] = {
        "id": str(run_id),
        "status": status,
        "fetched": fetched_count,
        "parsed": parsed_count,
        "materialized": materialized_count,
        "failed": failed_count,
        "error": error[:1000] if error else None,
    }
    conn.execute(
        text(f"UPDATE collection_runs SET {', '.join(assignments)} WHERE id = :id"), params
    )


def source_by_id(conn: Connection, source_id: UUID | str) -> dict | None:
    return get_source(conn, source_id)


def insert_result(
    conn: Connection,
    *,
    run_id: UUID | str,
    source_id: UUID | str | None,
    title: str,
    url: str,
    raw_content: str | None,
    dedup_key: str | None,
    parse_status: str = "pending",
    error: str | None = None,
) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO collection_results "
            "(run_id, source_id, title, url, raw_content, dedup_key, parse_status, error) "
            "VALUES (:run, :source, :title, :url, :raw, :dedup, :parse, :error) RETURNING *"
        ),
        {
            "run": str(run_id),
            "source": str(source_id) if source_id else None,
            "title": title[:512],
            "url": url[:2048],
            "raw": raw_content,
            "dedup": dedup_key,
            "parse": parse_status,
            "error": error[:1000] if error else None,
        },
    ).mappings().one()
    return dict(row)


def set_result_parse_status(
    conn: Connection, result_id: UUID | str, *, status: str, error: str | None = None
) -> None:
    conn.execute(
        text(
            "UPDATE collection_results SET parse_status = :status, error = :error, "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": str(result_id), "status": status, "error": error[:1000] if error else None},
    )


def get_result(conn: Connection, result_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM collection_results WHERE id = :id"), {"id": str(result_id)}
    ).mappings().first()
    return dict(row) if row else None


def list_results(
    conn: Connection,
    page: int,
    page_size: int,
    run_id: UUID | str | None = None,
    parse_status: str | None = None,
    materialize_status: str | None = None,
) -> tuple[list[dict], int]:
    where, params = ["TRUE"], {}
    if run_id:
        where.append("run_id = :run")
        params["run"] = str(run_id)
    if parse_status:
        where.append("parse_status = :parse")
        params["parse"] = parse_status
    if materialize_status:
        where.append("materialize_status = :materialize")
        params["materialize"] = materialize_status
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT count(*) FROM collection_results WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT * FROM collection_results WHERE {clause} "
            "ORDER BY collected_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def set_result_materialized(
    conn: Connection, result_id: UUID | str, material_id: UUID | str, status: str
) -> None:
    conn.execute(
        text(
            "UPDATE collection_results SET materialize_status = :status, "
            "material_id = :material, updated_at = now() WHERE id = :id"
        ),
        {"id": str(result_id), "material": str(material_id), "status": status},
    )


def set_result_ignored(conn: Connection, result_id: UUID | str) -> bool:
    row = conn.execute(
        text(
            "UPDATE collection_results SET materialize_status = 'ignored', updated_at = now() "
            "WHERE id = :id RETURNING id"
        ),
        {"id": str(result_id)},
    ).scalar()
    return row is not None
