"""Collection management endpoints (task 3.1 contracts).

Handlers are implemented in tasks 3.4-3.7; until then documented endpoints
answer 501 not_implemented. Contracts are complete: permissions, status
vocabularies and the batch per-item results are visible in /openapi.json.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import CurrentUserDep, DbSession, require_permission, verify_csrf
from app.api.responses import error_responses, idempotency_conflict_response
from app.errors import ApiError
from app.schemas.auth import PermissionCode
from app.schemas.common import AsyncJobAccepted as AsyncJobAcceptedOut
from app.schemas.analysis import AnalysisApplyIn, AnalysisResultOut, AnalysisRetryOut
from app.schemas.collection import (
    AnalysisConfigOut,
    BulkMaterializeIn,
    BulkResultOut,
    CollectionResultOut,
    CollectionRunOut,
    CollectionSourceIn,
    CollectionSourceOut,
    CollectionTaskIn,
    CollectionTaskOut,
    CollectionTaskUpdateIn,
    ManualRetentionIn,
    ScheduleIn,
    SourceSummary,
    SourceTestResult,
)
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.repositories import collection_repository as collection_repo
from app.services import (
    audit_service,
    collection_service,
    idempotency_service,
    materialization_service,
    source_service,
    analysis_management_service,
)

router = APIRouter(prefix="/collection", tags=["collection"])

READ = Depends(require_permission(PermissionCode.COLLECTION_READ))
WRITE = Depends(require_permission(PermissionCode.COLLECTION_WRITE))
RUN = Depends(require_permission(PermissionCode.COLLECTION_RUN))


@router.get("/config-options", responses=error_responses(401, 403))
async def configuration_options(db: DbSession, _perm=READ):
    from sqlalchemy import text

    return {
        name: [
            dict(row) for row in db.connection().execute(text(query)).mappings().all()
        ]
        for name, query in {
            "searches": "SELECT id,name FROM search_configs WHERE enabled ORDER BY name",
            "models": "SELECT id,name FROM model_configs WHERE enabled AND purpose='analysis' ORDER BY name",
            "sources": "SELECT id,name FROM collection_sources WHERE enabled AND deleted_at IS NULL ORDER BY name",
        }.items()
    }


CSRF = Depends(verify_csrf)


def _source_out(row: dict) -> CollectionSourceOut:
    return CollectionSourceOut(
        id=row["id"],
        name=row["name"],
        source_type=row["source_type"],
        base_url=row["base_url"],
        description=row["description"],
        enabled=row["enabled"],
        status=row["status"],
        page_kind=row.get("page_kind") or "article",
        article_link_selector=row.get("article_link_selector"),
        next_page_selector=row.get("next_page_selector"),
        last_checked_at=row.get("last_checked_at"),
        last_success_at=row.get("last_success_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _task_out(row: dict, db) -> CollectionTaskOut:
    sources = collection_repo.task_sources(db.connection(), row["id"])
    return CollectionTaskOut(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        mode=row.get("mode") or "source",
        topic=row.get("topic"),
        keywords=row.get("keywords") or [],
        sources=[SourceSummary(id=s["id"], name=s["name"]) for s in sources],
        allowed_domains=row.get("allowed_domains") or [],
        schedule=ScheduleIn(
            frequency=row["schedule_frequency"],
            cron_expr=row.get("schedule_cron_expr"),
            timezone=row["timezone"],
        ),
        time_range_days=row["time_range_days"],
        max_candidates=row.get("max_candidates") or 100,
        max_fetch=row.get("max_fetch") or 20,
        max_pages=row.get("max_pages") or 5,
        analysis=AnalysisConfigOut(
            enabled=bool(row.get("analysis_enabled")),
            model_config_id=row.get("analysis_model_config_id"),
            apply_policy=row.get("analysis_apply_policy") or "suggest_only",
        ),
        search_config_id=row.get("search_config_id"),
        auto_materialize=row["auto_materialize"],
        auto_create=row["auto_create"],
        last_run_at=row.get("last_run_at"),
        next_run_at=row.get("next_run_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_out(row: dict) -> CollectionRunOut:
    return CollectionRunOut(
        id=row["id"],
        task_id=row["task_id"],
        trigger=row["trigger"],
        status=row["status"],
        end_reason=row.get("end_reason"),
        fetched_count=row["fetched_count"],
        parsed_count=row["parsed_count"],
        materialized_count=row["materialized_count"],
        failed_count=row["failed_count"],
        discovered_count=row.get("discovered_count") or 0,
        analyzed_count=row.get("analyzed_count") or 0,
        filtered_count=row.get("filtered_count") or 0,
        review_required_count=row.get("review_required_count") or 0,
        error=row.get("error"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _result_out(row: dict) -> CollectionResultOut:
    return CollectionResultOut(
        id=row["id"],
        run_id=row["run_id"],
        source_id=row.get("source_id"),
        title=row["title"],
        url=row["url"],
        published_at=row.get("published_at"),
        collected_at=row["collected_at"],
        parse_status=row["parse_status"],
        materialize_status=row["materialize_status"],
        material_id=row.get("material_id"),
        error=row.get("error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _not_ready(description: str) -> dict:
    return {
        "model": ErrorEnvelope,
        "description": description,
        "content": {
            "application/json": {
                "example": {
                    "error": {
                        "code": "not_implemented",
                        "message": "该接口的实现将在后续任务完成",
                    }
                }
            }
        },
    }


RUN_ACCEPTED_EXAMPLE = {
    "async_job_id": "0d1c6a3e-6f4a-4a5d-9a44-8d0b6c5f21aa",
    "resource_type": "collection_run",
    "resource_id": "7b2d8c1a-1e2f-4b3c-8d4e-5f6a7b8c9d0e",
    "status": "accepted",
}

# --- sources ---


@router.get(
    "/sources",
    response_model=PaginatedResponse[CollectionSourceOut],
    responses=error_responses(401, 403),
    summary="分页查询采集来源",
)
async def list_sources(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=128),
) -> PaginatedResponse[CollectionSourceOut]:
    rows, total = source_service.list_sources(db.connection(), page, page_size, keyword)
    return PaginatedResponse(
        items=[_source_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/sources",
    response_model=CollectionSourceOut,
    status_code=201,
    responses={
        **error_responses(400, 401, 403, 409, 422),
        409: idempotency_conflict_response(),
    },
    summary="创建采集来源",
)
async def create_source(
    payload: CollectionSourceIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CollectionSourceOut:
    conn = db.connection()
    idem_row = None
    if idempotency_key:
        fingerprint = idempotency_service.request_fingerprint(payload.model_dump())
        try:
            idem_row = idempotency_service.begin_request(
                conn, "collection.create_source", user.id, idempotency_key, fingerprint
            )
        except idempotency_service.IdempotencyReplay as replay:
            return CollectionSourceOut.model_validate(replay.row["response_body"])
        except idempotency_service.IdempotencyConflict:
            raise ApiError(
                409, "idempotency_conflict", "该幂等键已被用于不同的请求内容"
            ) from None
        if idem_row.get("response_status") == 201:
            return CollectionSourceOut.model_validate(idem_row["response_body"])
    try:
        row = source_service.create_source(conn, payload, user.id)
    except ApiError as exc:
        db.rollback()
        audit_service.record_operation(
            db.connection(),
            user_id=user.id,
            action="collection.source.create",
            object_type="collection_source",
            result="denied",
            detail={"name": payload.name, "reason": exc.code},
        )
        db.commit()
        raise
    audit_service.record_operation(
        conn,
        user_id=user.id,
        action="collection.source.create",
        object_type="collection_source",
        object_id=row["id"],
        detail={"name": row["name"], "base_url": row["base_url"]},
    )
    db.commit()
    body = _source_out(row).model_dump(mode="json")
    if idem_row is not None:
        idempotency_service.store_response(db.connection(), idem_row["id"], 201, body)
        db.commit()
    return CollectionSourceOut.model_validate(body)


@router.get(
    "/sources/{source_id}",
    response_model=CollectionSourceOut,
    responses=error_responses(401, 403, 404),
    summary="来源详情",
)
async def get_source(source_id: UUID, db: DbSession, _perm=READ) -> CollectionSourceOut:
    return _source_out(source_service.get_source(db.connection(), source_id))


@router.patch(
    "/sources/{source_id}",
    response_model=CollectionSourceOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新来源（重命名/启停/地址）",
)
async def update_source(
    source_id: UUID,
    payload: CollectionSourceIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionSourceOut:
    conn = db.connection()
    try:
        row = source_service.update_source(conn, source_id, payload)
    except ApiError as exc:
        db.rollback()
        audit_service.record_operation(
            db.connection(),
            user_id=user.id,
            action="collection.source.update",
            object_type="collection_source",
            object_id=source_id,
            result="denied",
            detail={"reason": exc.code},
        )
        db.commit()
        raise
    audit_service.record_operation(
        conn,
        user_id=user.id,
        action="collection.source.update",
        object_type="collection_source",
        object_id=source_id,
        detail={"name": row["name"]},
    )
    db.commit()
    return _source_out(row)


@router.delete(
    "/sources/{source_id}",
    responses={
        **error_responses(401, 403, 404),
        200: {
            "model": CollectionSourceOut,
            "description": "来源已停用/删除，历史运行与结果保留",
        },
    },
    summary="删除来源（保留历史追溯）",
)
async def delete_source(
    source_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionSourceOut:
    row = source_service.delete_source(db.connection(), source_id, user.id)
    db.commit()
    return _source_out(row)


@router.post(
    "/sources/{source_id}/test",
    response_model=SourceTestResult,
    responses={**error_responses(401, 403, 404, 503)},
    summary="来源连接测试（范围/超时/大小受限）",
)
async def test_source(
    source_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> SourceTestResult:
    result = source_service.test_source(db.connection(), source_id)
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="collection.source.test",
        object_type="collection_source",
        object_id=source_id,
        result="success" if result.reachable else "failed",
        detail={"status_code": result.status_code, "error": result.error},
    )
    db.commit()
    return result


# --- tasks ---


@router.get(
    "/tasks",
    response_model=PaginatedResponse[CollectionTaskOut],
    responses=error_responses(401, 403),
    summary="分页查询采集任务",
)
async def list_tasks(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionTaskOut]:
    rows, total = collection_service.list_tasks(
        db.connection(), page, page_size, status
    )
    return PaginatedResponse(
        items=[_task_out(row, db) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/tasks",
    response_model=CollectionTaskOut,
    status_code=201,
    responses={
        **error_responses(400, 401, 403, 409, 422),
        409: idempotency_conflict_response(),
    },
    summary="创建采集任务",
)
async def create_task(
    payload: CollectionTaskIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionTaskOut:
    task = collection_service.create_task(db.connection(), payload, user.id)
    db.commit()
    return _task_out(task, db)


@router.get(
    "/tasks/{task_id}",
    response_model=CollectionTaskOut,
    responses=error_responses(401, 403, 404),
    summary="任务详情",
)
async def get_task(task_id: UUID, db: DbSession, _perm=READ) -> CollectionTaskOut:
    return _task_out(collection_service.get_task(db.connection(), task_id), db)


@router.patch(
    "/tasks/{task_id}",
    response_model=CollectionTaskOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新任务（关键词/来源/调度/开关；省略字段保留原值）",
)
async def update_task(
    task_id: UUID,
    payload: CollectionTaskUpdateIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionTaskOut:
    task = collection_service.update_task(
        db.connection(), task_id, payload.model_dump(exclude_unset=True)
    )
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="collection.task.update",
        object_type="collection_task",
        object_id=task_id,
        detail={"name": task["name"]},
    )
    db.commit()
    return _task_out(task, db)


@router.delete(
    "/tasks/{task_id}",
    response_model=CollectionTaskOut,
    responses={**error_responses(401, 403, 404)},
    summary="删除任务（置 archived；历史运行与来源关联保留）",
)
async def delete_task(
    task_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionTaskOut:
    task = collection_service.set_status(db.connection(), task_id, "archived")
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="collection.task.delete",
        object_type="collection_task",
        object_id=task_id,
    )
    db.commit()
    return _task_out(task, db)


@router.post(
    "/tasks/{task_id}/pause",
    response_model=CollectionTaskOut,
    responses=error_responses(401, 403, 404, 409),
    summary="暂停任务（暂停后不再调度，历史保留）",
)
async def pause_task(
    task_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionTaskOut:
    task = collection_service.set_status(db.connection(), task_id, "paused")
    db.commit()
    return _task_out(task, db)


@router.post(
    "/tasks/{task_id}/resume",
    response_model=CollectionTaskOut,
    responses=error_responses(401, 403, 404, 409),
    summary="恢复任务调度",
)
async def resume_task(
    task_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionTaskOut:
    task = collection_service.set_status(db.connection(), task_id, "active")
    db.commit()
    return _task_out(task, db)


@router.post(
    "/tasks/{task_id}/run",
    response_model=AsyncJobAcceptedOut,
    status_code=202,
    responses={
        **error_responses(401, 403, 404, 409, 422),
        409: idempotency_conflict_response(),
        202: {
            "model": AsyncJobAcceptedOut,
            "description": "立即执行已被可靠受理；用 async_job_id / run 资源查询进度",
            "content": {"application/json": {"example": RUN_ACCEPTED_EXAMPLE}},
        },
    },
    summary="立即执行采集任务（202 受理）",
)
async def run_task_now(
    task_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=RUN,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AsyncJobAcceptedOut:
    conn = db.connection()
    idem_row = None
    if idempotency_key:
        fingerprint = idempotency_service.request_fingerprint({"task_id": str(task_id)})
        try:
            idem_row = idempotency_service.begin_request(
                conn, "collection.run_task", user.id, idempotency_key, fingerprint
            )
        except idempotency_service.IdempotencyReplay as replay:
            return AsyncJobAcceptedOut.model_validate(replay.row["response_body"])
        except idempotency_service.IdempotencyConflict:
            raise ApiError(
                409, "idempotency_conflict", "该幂等键已被用于不同的请求内容"
            ) from None
        if idem_row.get("response_status") == 202:
            return AsyncJobAcceptedOut.model_validate(idem_row["response_body"])
    try:
        result = collection_service.run_now(conn, task_id, user.id)
    except ApiError:
        db.rollback()
        raise
    db.commit()
    accepted = AsyncJobAcceptedOut(
        async_job_id=result["job"]["id"],
        resource_type="collection_run",
        resource_id=result["run"]["id"],
        status="accepted",
    )
    body = accepted.model_dump(mode="json")
    if idem_row is not None:
        idempotency_service.store_response(db.connection(), idem_row["id"], 202, body)
        db.commit()
    return accepted


# --- runs ---


@router.get(
    "/runs",
    response_model=PaginatedResponse[CollectionRunOut],
    responses=error_responses(401, 403),
    summary="分页查询执行记录（按任务/触发方式筛选）",
)
async def list_runs(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    task_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionRunOut]:
    rows, total = collection_service.list_runs(
        db.connection(), page, page_size, task_id, status
    )
    return PaginatedResponse(
        items=[_run_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_model=CollectionRunOut,
    responses=error_responses(401, 403, 404),
    summary="执行详情",
)
async def get_run(run_id: UUID, db: DbSession, _perm=READ) -> CollectionRunOut:
    return _run_out(collection_service.get_run(db.connection(), run_id))


# --- results ---


@router.get(
    "/results",
    response_model=PaginatedResponse[CollectionResultOut],
    responses=error_responses(401, 403),
    summary="分页查询采集结果（按 run/解析/入库状态筛选）",
)
async def list_results(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    run_id: UUID | None = Query(default=None),
    parse_status: str | None = Query(default=None),
    materialize_status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionResultOut]:
    rows, total = collection_repo.list_results(
        db.connection(), page, page_size, run_id, parse_status, materialize_status
    )
    return PaginatedResponse(
        items=[_result_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/results/{result_id}",
    response_model=CollectionResultOut,
    responses=error_responses(401, 403, 404),
    summary="采集结果详情（含原文链接与来源）",
)
async def get_result(result_id: UUID, db: DbSession, _perm=READ) -> CollectionResultOut:
    row = collection_repo.get_result(db.connection(), result_id)
    if not row:
        raise ApiError(404, "not_found", "采集结果不存在")
    return _result_out(row)


@router.post(
    "/results/{result_id}/materialize",
    response_model=AsyncJobAcceptedOut,
    status_code=202,
    responses={
        **error_responses(401, 403, 404, 409, 422),
        409: idempotency_conflict_response(),
        202: {
            "model": AsyncJobAcceptedOut,
            "description": "入库已受理（异步解析/入库）；重复重试不会重复创建已成功关联的素材",
            "content": {"application/json": {"example": RUN_ACCEPTED_EXAMPLE}},
        },
    },
    summary="单条入库（异步）",
)
async def materialize_result(
    result_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=RUN,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AsyncJobAcceptedOut:
    conn = db.connection()
    if not collection_repo.get_result(conn, result_id):
        raise ApiError(404, "not_found", "采集结果不存在")
    idem_row = None
    if idempotency_key:
        fingerprint = idempotency_service.request_fingerprint(
            {"result_id": str(result_id)}
        )
        try:
            idem_row = idempotency_service.begin_request(
                conn,
                "collection.materialize_result",
                user.id,
                idempotency_key,
                fingerprint,
            )
        except idempotency_service.IdempotencyReplay as replay:
            return AsyncJobAcceptedOut.model_validate(replay.row["response_body"])
        except idempotency_service.IdempotencyConflict:
            raise ApiError(
                409, "idempotency_conflict", "该幂等键已被用于不同的请求内容"
            ) from None
        if idem_row.get("response_status") == 202:
            return AsyncJobAcceptedOut.model_validate(idem_row["response_body"])
    job = materialization_service.accept_job(
        conn, "collection.materialize", result_id, user.id
    )
    db.commit()
    accepted = AsyncJobAcceptedOut(
        async_job_id=job["id"],
        resource_type="collection_result",
        resource_id=result_id,
        status="accepted",
    )
    body = accepted.model_dump(mode="json")
    if idem_row is not None:
        idempotency_service.store_response(db.connection(), idem_row["id"], 202, body)
        db.commit()
    return accepted


BULK_RESULT_EXAMPLE = {
    "items": [
        {
            "result_id": "11111111-1111-4111-8111-111111111111",
            "status": "materialized",
            "material_id": "22222222-2222-4222-8222-222222222222",
            "error": None,
        },
        {
            "result_id": "33333333-3333-4333-8333-333333333333",
            "status": "duplicate",
            "material_id": "44444444-4444-4444-8444-444444444444",
            "error": None,
        },
        {
            "result_id": "55555555-5555-4555-8555-555555555555",
            "status": "failed",
            "material_id": None,
            "error": "正文解析失败",
        },
    ],
    "counts": {
        "materialized": 1,
        "duplicate": 1,
        "new_progress": 0,
        "ignored": 0,
        "failed": 1,
    },
}


@router.post(
    "/results/bulk-materialize",
    response_model=BulkResultOut,
    responses={
        **error_responses(401, 403, 422),
        409: idempotency_conflict_response(),
        200: {
            "model": BulkResultOut,
            "description": "逐项结果：批量中允许混合成功与失败",
            "content": {"application/json": {"example": BULK_RESULT_EXAMPLE}},
        },
    },
    summary="批量入库（返回逐项结果）",
)
async def bulk_materialize(
    payload: BulkMaterializeIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=RUN,
) -> BulkResultOut:
    result = materialization_service.bulk_materialize(
        db.connection(), payload.result_ids, user.id
    )
    db.commit()
    return BulkResultOut.model_validate(result)


@router.post(
    "/results/{result_id}/ignore",
    responses={
        **error_responses(401, 403, 404, 409),
        200: {
            "model": ErrorEnvelope,
            "description": "结果已置为 ignored，不建素材",
            "content": {
                "application/json": {
                    "example": {
                        "error": {"code": "ignored", "message": "结果已忽略，不建素材"}
                    }
                }
            },
        },
    },
    summary="忽略采集结果",
)
async def ignore_result(
    result_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> ErrorEnvelope:
    materialization_service.ignore(db.connection(), result_id)
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="collection.result.ignore",
        object_type="collection_result",
        object_id=result_id,
    )
    db.commit()
    return ErrorEnvelope.model_validate(
        {"error": {"code": "ignored", "message": "结果已忽略，不建素材"}}
    )


@router.post(
    "/results/{result_id}/retry-parse",
    response_model=AsyncJobAcceptedOut,
    status_code=202,
    responses={
        **error_responses(401, 403, 404, 409, 422),
        409: idempotency_conflict_response(),
        202: {
            "model": AsyncJobAcceptedOut,
            "description": "解析重试已受理；重复重试不重复创建已成功关联的素材",
            "content": {"application/json": {"example": RUN_ACCEPTED_EXAMPLE}},
        },
    },
    summary="重试解析失败的结果（异步）",
)
async def retry_parse(
    result_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=RUN,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> AsyncJobAcceptedOut:
    conn = db.connection()
    if not collection_repo.get_result(conn, result_id):
        raise ApiError(404, "not_found", "采集结果不存在")
    idem_row = None
    if idempotency_key:
        fingerprint = idempotency_service.request_fingerprint(
            {"result_id": str(result_id)}
        )
        try:
            idem_row = idempotency_service.begin_request(
                conn, "collection.retry_parse", user.id, idempotency_key, fingerprint
            )
        except idempotency_service.IdempotencyReplay as replay:
            return AsyncJobAcceptedOut.model_validate(replay.row["response_body"])
        except idempotency_service.IdempotencyConflict:
            raise ApiError(
                409, "idempotency_conflict", "该幂等键已被用于不同的请求内容"
            ) from None
        if idem_row.get("response_status") == 202:
            return AsyncJobAcceptedOut.model_validate(idem_row["response_body"])
    job = materialization_service.accept_job(
        conn, "collection.retry_parse", result_id, user.id
    )
    db.commit()
    accepted = AsyncJobAcceptedOut(
        async_job_id=job["id"],
        resource_type="collection_result",
        resource_id=result_id,
        status="accepted",
    )
    body = accepted.model_dump(mode="json")
    if idem_row is not None:
        idempotency_service.store_response(db.connection(), idem_row["id"], 202, body)
        db.commit()
    return accepted


# --- analysis (contract stubs; implemented in 3.16/3.20) ---


@router.get(
    "/analysis",
    response_model=PaginatedResponse[AnalysisResultOut],
    responses=error_responses(401, 403),
    summary="分页查询分析结果（按结果/素材/状态筛选）",
)
async def list_analyses(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    result_id: UUID | None = Query(default=None),
    material_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[AnalysisResultOut]:
    rows, total = analysis_management_service.list_analyses(
        db.connection(), page, page_size, result_id, material_id, status
    )
    return PaginatedResponse(
        items=[AnalysisResultOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/analysis/{analysis_id}",
    response_model=AnalysisResultOut,
    responses=error_responses(401, 403, 404),
    summary="分析结果详情（含结构化建议与原文引用）",
)
async def get_analysis(
    analysis_id: UUID, db: DbSession, _perm=READ
) -> AnalysisResultOut:
    return AnalysisResultOut.model_validate(
        analysis_management_service.get_analysis(db.connection(), analysis_id)
    )


@router.post(
    "/analysis/{analysis_id}/retry",
    status_code=202,
    response_model=AnalysisRetryOut,
    responses={**error_responses(401, 403, 404, 409)},
    summary="重试分析（从同一正文快照恢复，不重新抓取）",
)
async def retry_analysis(
    analysis_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=RUN,
) -> AnalysisRetryOut:
    job = analysis_management_service.retry_analysis(
        db.connection(), analysis_id, user.id
    )
    db.commit()
    return AnalysisRetryOut(analysis_id=analysis_id, async_job_id=job["id"])


@router.post(
    "/analysis/{analysis_id}/apply",
    response_model=ErrorEnvelope,
    responses={
        **error_responses(401, 403, 404, 409, 422),
        409: {
            "model": ErrorEnvelope,
            "description": "基准元数据版本失效，拒绝覆盖分析期间的人工编辑",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "conflict",
                            "message": "素材元数据版本已变化，请刷新后重试",
                        }
                    }
                }
            },
        },
    },
    summary="采用分析建议（base_metadata_version 冲突返回 409）",
)
async def apply_analysis(
    analysis_id: UUID,
    payload: AnalysisApplyIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> ErrorEnvelope:
    analysis_management_service.apply_analysis(
        db.connection(), analysis_id, payload, user.id
    )
    db.commit()
    return ErrorEnvelope.model_validate(
        {"error": {"code": "applied", "message": "分析建议已采用"}}
    )


@router.post(
    "/results/{result_id}/retain",
    response_model=CollectionResultOut,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="人工保留为待筛选素材（填写原因；不伪造分析成功）",
)
async def retain_result(
    result_id: UUID,
    payload: ManualRetentionIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> CollectionResultOut:
    if payload.result_id != result_id:
        raise ApiError(422, "result_mismatch", "结果 ID 不一致")
    row = analysis_management_service.retain_result(
        db.connection(), result_id, payload.reason, user.id
    )
    db.commit()
    return _result_out(row)


@router.get("/runs/{run_id}/candidates", responses=error_responses(401, 403, 404))
async def run_candidates(run_id: UUID, db: DbSession, _perm=READ):
    from sqlalchemy import text

    collection_service.get_run(db.connection(), run_id)
    rows = (
        db.connection()
        .execute(
            text(
                "SELECT * FROM collection_candidates WHERE run_id=:id ORDER BY created_at,id"
            ),
            {"id": str(run_id)},
        )
        .mappings()
        .all()
    )
    output = []
    for row in rows:
        item = dict(row)
        item["attempts"] = [
            dict(attempt)
            for attempt in db.connection()
            .execute(
                text(
                    "SELECT * FROM collection_stage_attempts WHERE candidate_id=:id ORDER BY created_at,id"
                ),
                {"id": row["id"]},
            )
            .mappings()
            .all()
        ]
        item["snapshot"] = (
            db.connection()
            .execute(
                text(
                    "SELECT id,markdown,content_hash,extractor_version,date_evidence FROM collection_snapshots WHERE candidate_id=:id ORDER BY captured_at DESC,id DESC LIMIT 1"
                ),
                {"id": row["id"]},
            )
            .mappings()
            .first()
        )
        output.append(item)
    return output


@router.post(
    "/runs/{run_id}/retry",
    status_code=202,
    response_model=AsyncJobAcceptedOut,
    responses=error_responses(401, 403, 404, 409),
)
async def retry_run(
    run_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=RUN
):
    from sqlalchemy import text
    from app.services import async_job_service, outbox_service

    run = collection_service.get_run(db.connection(), run_id)
    if run["status"] not in ("partial", "failed") or run["end_reason"] == "cancelled":
        raise ApiError(409, "run_not_retryable", "当前执行不可重试")
    job = async_job_service.create_job(
        db.connection(),
        "collection.run",
        "collection_run",
        run_id,
        payload={"run_id": str(run_id)},
        created_by=user.id,
    )
    db.connection().execute(
        text("UPDATE collection_runs SET async_job_id=:job WHERE id=:id"),
        {"id": str(run_id), "job": job["id"]},
    )
    outbox_service.publish_event(
        db.connection(),
        "collection.run.retry",
        "collection_run",
        run_id,
        payload={
            "task": "app.modules.async_execution.tasks.run_async_job",
            "kwargs": {"job_id": job["id"]},
        },
    )
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="collection.run.retry",
        object_type="collection_run",
        object_id=run_id,
    )
    db.commit()
    return AsyncJobAcceptedOut(
        async_job_id=job["id"],
        resource_type="collection_run",
        resource_id=run_id,
        status="accepted",
    )
