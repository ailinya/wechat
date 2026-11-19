"""Collection task management and run acceptance (task 3.5).

A run is always created together with an async job and an outbox event in the
caller's transaction: a rollback leaves no orphan run, and the dispatcher
delivers the job only after commit. Scheduled runs carry a window key whose
unique index prevents duplicate scheduling for the same window.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.config import Settings
from app.errors import ApiError
from app.modules.collection import schedule
from app.repositories import collection_repository as repo
from app.schemas.collection import CollectionTaskIn, ScheduleIn
from app.services import async_job_service, audit_service, outbox_service

JOB_TYPE = "collection.run"
TASK_NAME = "app.modules.async_execution.tasks.run_async_job"
LEASE_SECONDS = 120


def _sources(conn: Connection, source_ids: list[UUID]) -> list[str]:
    resolved = repo.active_source_ids(conn, source_ids)
    if len(resolved) != len(set(str(value) for value in source_ids)):
        raise ApiError(422, "invalid_sources", "部分来源不存在、已停用或已删除")
    return resolved


def _task_fields(payload: CollectionTaskIn) -> dict[str, Any]:
    return {
        "name": payload.name,
        "keywords": payload.keywords,
        "time_range_days": payload.time_range_days,
        "schedule_frequency": payload.schedule.frequency,
        "schedule_cron_expr": payload.schedule.cron_expr,
        "timezone": payload.schedule.timezone,
        "auto_materialize": payload.auto_materialize,
        "auto_create": payload.auto_create,
    }


def create_task(
    conn: Connection, payload: CollectionTaskIn, user_id: UUID | str | None
) -> dict:
    if repo.task_with_name_exists(conn, payload.name):
        raise ApiError(409, "conflict", "采集任务名称已存在")
    source_ids = _sources(conn, payload.source_ids)
    task = repo.create_task(
        conn, **_task_fields(payload), source_ids=source_ids, created_by=user_id
    )
    _save_enhancement(conn, task["id"], payload.model_dump(mode="json"))
    task = repo.get_task(conn, task["id"])
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="collection.task.create",
        object_type="collection_task",
        object_id=task["id"],
        detail={"name": task["name"], "sources": len(source_ids)},
    )
    return task


def list_tasks(
    conn: Connection, page: int, page_size: int, status: str | None
) -> tuple[list[dict], int]:
    return repo.list_tasks(conn, page, page_size, status)


def get_task(conn: Connection, task_id: UUID | str) -> dict:
    task = repo.get_task(conn, task_id)
    if not task:
        raise ApiError(404, "not_found", "采集任务不存在")
    return task


def update_task(conn: Connection, task_id: UUID | str, updates: dict[str, Any]) -> dict:
    current = get_task(conn, task_id)
    name = updates.get("name", current["name"])
    if updates.get("name") and repo.task_with_name_exists(
        conn, name, exclude_id=task_id
    ):
        raise ApiError(409, "conflict", "采集任务名称已存在")

    keywords = updates.get("keywords", current.get("keywords") or [])
    time_range_days = updates.get("time_range_days", current["time_range_days"])
    schedule = updates.get("schedule")
    if schedule is not None:
        frequency = schedule.get("frequency", current["schedule_frequency"])
        cron_expr = schedule.get("cron_expr", current.get("schedule_cron_expr"))
        timezone = schedule.get("timezone", current["timezone"])
    else:
        frequency = current["schedule_frequency"]
        cron_expr = current.get("schedule_cron_expr")
        timezone = current["timezone"]
    auto_materialize = updates.get("auto_materialize", current["auto_materialize"])
    auto_create = updates.get("auto_create", current["auto_create"])

    source_ids: list[str] | None = None
    if "source_ids" in updates:
        source_ids = _sources(conn, updates["source_ids"])

    task = repo.update_task(
        conn,
        task_id,
        name=name,
        keywords=keywords,
        time_range_days=time_range_days,
        schedule_frequency=frequency,
        schedule_cron_expr=cron_expr,
        timezone=timezone,
        auto_materialize=auto_materialize,
        auto_create=auto_create,
        source_ids=source_ids,
    )
    assert task is not None
    _save_enhancement(conn, task_id, updates)
    task = repo.get_task(conn, task_id)
    return task


def _save_enhancement(conn, task_id, values):
    columns = {
        "mode",
        "topic",
        "allowed_domains",
        "max_candidates",
        "max_fetch",
        "max_pages",
        "search_config_id",
    }
    params = {"id": str(task_id)}
    assignments = []
    for column in columns & values.keys():
        value = values[column]
        params[column] = json.dumps(value) if column == "allowed_domains" else value
        assignments.append(
            f"{column}=CAST(:{column} AS jsonb)"
            if column == "allowed_domains"
            else f"{column}=:{column}"
        )
    if "analysis" in values and values["analysis"] is not None:
        for key, column in {
            "enabled": "analysis_enabled",
            "model_config_id": "analysis_model_config_id",
            "apply_policy": "analysis_apply_policy",
        }.items():
            if key in values["analysis"]:
                params[column] = values["analysis"][key]
                assignments.append(f"{column}=:{column}")
    if assignments:
        conn.execute(
            text(f"UPDATE collection_tasks SET {', '.join(assignments)} WHERE id=:id"),
            params,
        )
    task = repo.get_task(conn, task_id)
    sources = repo.task_sources(conn, task_id)
    if task["mode"] == "source" and not sources:
        raise ApiError(422, "invalid_sources", "指定来源模式需要至少一个来源")
    if task["mode"] == "topic_search":
        if sources or not (task["topic"] or "").strip():
            raise ApiError(
                422, "invalid_search_input", "主题搜索需要主题且不接受来源 ID"
            )
        config = conn.execute(
            text("SELECT enabled FROM search_configs WHERE id=:id"),
            {"id": task["search_config_id"]},
        ).scalar_one_or_none()
        if not config:
            raise ApiError(422, "search_unavailable", "请选择可用搜索配置")
    if task["analysis_enabled"]:
        config = conn.execute(
            text(
                "SELECT enabled AND purpose='analysis' FROM model_configs WHERE id=:id"
            ),
            {"id": task["analysis_model_config_id"]},
        ).scalar_one_or_none()
        if not config:
            raise ApiError(422, "model_unavailable", "请选择可用的分析模型")


def set_status(conn: Connection, task_id: UUID | str, status: str) -> dict:
    if status not in ("active", "paused", "archived"):
        raise ApiError(400, "bad_request", "非法的任务状态")
    task = repo.set_task_status(conn, task_id, status)
    if not task:
        raise ApiError(404, "not_found", "采集任务不存在")
    if status == "paused":
        # Clearing next_run_at makes it explicit that no scheduling is pending.
        conn.execute(
            text("UPDATE collection_tasks SET next_run_at = NULL WHERE id = :id"),
            {"id": str(task_id)},
        )
    return task


def _create_run_with_job(
    conn: Connection,
    task: dict,
    *,
    trigger: str,
    window_key: str | None,
    created_by: UUID | str | None,
) -> dict:
    run = repo.create_run(
        conn, task_id=task["id"], trigger=trigger, window_key=window_key
    )
    snapshot = dict(task)
    snapshot["source_ids"] = [str(s["id"]) for s in repo.task_sources(conn, task["id"])]
    snapshot["sources"] = [dict(row) for row in conn.execute(text(
        'SELECT s.id,s.name,s.source_type,s.base_url,s.page_kind,s.article_link_selector,s.next_page_selector '
        'FROM collection_sources s JOIN collection_task_sources ts ON ts.source_id=s.id '
        'WHERE ts.task_id=:id AND s.deleted_at IS NULL AND s.enabled ORDER BY s.id'
    ),{'id':task['id']}).mappings()]
    conn.execute(
        text(
            "UPDATE collection_runs SET config_snapshot=CAST(:snapshot AS jsonb) WHERE id=:id"
        ),
        {"id": run["id"], "snapshot": json.dumps(snapshot, default=str)},
    )
    job = async_job_service.create_job(
        conn,
        JOB_TYPE,
        "collection_run",
        run["id"],
        payload={"run_id": str(run["id"]), "task_id": str(task["id"])},
        created_by=created_by,
    )
    conn.execute(
        text("UPDATE collection_runs SET async_job_id=:job WHERE id=:id"),
        {"job": job["id"], "id": run["id"]},
    )
    outbox_service.publish_event(
        conn,
        "collection.run.requested",
        "collection_run",
        run["id"],
        payload={"task": TASK_NAME, "kwargs": {"job_id": job["id"]}},
    )
    return {"run": run, "job": job}


def run_now(conn: Connection, task_id: UUID | str, user_id: UUID | str | None) -> dict:
    task = get_task(conn, task_id)
    if task["status"] != "active":
        raise ApiError(409, "task_not_active", "任务未处于运行状态，无法立即执行")
    result = _create_run_with_job(
        conn, task, trigger="manual", window_key=None, created_by=user_id
    )
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="collection.task.run",
        object_type="collection_task",
        object_id=task_id,
        detail={"run_id": result["run"]["id"]},
    )
    return result


def list_runs(
    conn: Connection,
    page: int,
    page_size: int,
    task_id: UUID | str | None,
    status: str | None,
) -> tuple[list[dict], int]:
    return repo.list_runs(conn, page, page_size, task_id, status)


def get_run(conn: Connection, run_id: UUID | str) -> dict:
    run = repo.get_run(conn, run_id)
    if not run:
        raise ApiError(404, "not_found", "执行记录不存在")
    return run


def schedule_due_runs(
    conn: Connection, now: datetime | None = None, created_by: UUID | str | None = None
) -> dict:
    """Beat tick: create one scheduled run per due active task.

    A partial unique index on (task_id, window_key) plus the SELECT guard
    keeps repeated ticks from creating duplicates; a task paused mid-window
    is skipped by the query and rejected by the DB trigger as a second guard.
    """
    now = now or datetime.now(timezone.utc)
    created: list[str] = []
    for task in repo.list_scheduled_active_tasks(conn):
        window_key = schedule.compute_window_key(
            task["schedule_frequency"],
            task["schedule_cron_expr"],
            task["timezone"],
            now,
        )
        if not window_key:
            continue
        if repo.run_in_window_exists(conn, task["id"], window_key):
            continue
        lease = task.get("lease_until")
        if lease and getattr(lease, "tzinfo", None) is not None and lease > now:
            continue
        result = _create_run_with_job(
            conn,
            task,
            trigger="scheduled",
            window_key=window_key,
            created_by=created_by,
        )
        repo.set_lease(conn, task["id"], window_key, LEASE_SECONDS)
        created.append(str(result["run"]["id"]))
    return {"created": created}
