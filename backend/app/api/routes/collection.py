"""Collection management endpoints (task 3.1 contracts).

Handlers are implemented in tasks 3.4-3.7; until then documented endpoints
answer 501 not_implemented. Contracts are complete: permissions, status
vocabularies and the batch per-item results are visible in /openapi.json.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.api.responses import error_responses, idempotency_conflict_response
from app.schemas.common import AsyncJobAccepted as AsyncJobAcceptedOut
from app.schemas.collection import (
    BulkMaterializeIn,
    BulkResultOut,
    CollectionResultOut,
    CollectionRunOut,
    CollectionSourceIn,
    CollectionSourceOut,
    CollectionTaskIn,
    CollectionTaskOut,
    SourceTestResult,
)
from app.schemas.common import ErrorEnvelope, PaginatedResponse

router = APIRouter(prefix="/collection", tags=["collection"])

WRITE = "collection:write"
RUN = "collection:run"
READ = "collection:read"


def _not_ready(description: str) -> dict:
    return {
        "model": ErrorEnvelope,
        "description": description,
        "content": {
            "application/json": {
                "example": {"error": {"code": "not_implemented", "message": "该接口的实现将在后续任务完成"}}
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=128),
) -> PaginatedResponse[CollectionSourceOut]:
    raise NotImplementedError


@router.post(
    "/sources",
    response_model=CollectionSourceOut,
    status_code=201,
    responses={**error_responses(400, 401, 403, 409, 422), 409: idempotency_conflict_response()},
    summary="创建采集来源",
)
async def create_source(payload: CollectionSourceIn, db: DbSession) -> CollectionSourceOut:
    raise NotImplementedError


@router.get("/sources/{source_id}", response_model=CollectionSourceOut,
            responses=error_responses(401, 403, 404), summary="来源详情")
async def get_source(source_id: UUID, db: DbSession) -> CollectionSourceOut:
    raise NotImplementedError


@router.patch("/sources/{source_id}", response_model=CollectionSourceOut,
              responses=error_responses(400, 401, 403, 404, 409, 422),
              summary="更新来源（重命名/启停/地址）")
async def update_source(source_id: UUID, payload: CollectionSourceIn, db: DbSession) -> CollectionSourceOut:
    raise NotImplementedError


@router.delete(
    "/sources/{source_id}",
    responses={**error_responses(401, 403, 404), 200: _not_ready("来源停用/删除语义：不破坏既有运行与结果追溯")},
    summary="删除来源（保留历史追溯）",
)
async def delete_source(source_id: UUID, db: DbSession) -> ErrorEnvelope:
    raise NotImplementedError


@router.post("/sources/{source_id}/test", response_model=SourceTestResult,
             responses={**error_responses(401, 403, 404, 503)},
             summary="来源连接测试（范围/超时/大小受限）")
async def test_source(source_id: UUID, db: DbSession) -> SourceTestResult:
    raise NotImplementedError



# --- tasks ---

@router.get("/tasks", response_model=PaginatedResponse[CollectionTaskOut],
            responses=error_responses(401, 403),
            summary="分页查询采集任务")
async def list_tasks(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionTaskOut]:
    raise NotImplementedError


@router.post("/tasks", response_model=CollectionTaskOut, status_code=201,
             responses={**error_responses(400, 401, 403, 409, 422), 409: idempotency_conflict_response()},
             summary="创建采集任务")
async def create_task(payload: CollectionTaskIn, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


@router.get("/tasks/{task_id}", response_model=CollectionTaskOut,
            responses=error_responses(401, 403, 404), summary="任务详情")
async def get_task(task_id: UUID, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


@router.patch("/tasks/{task_id}", response_model=CollectionTaskOut,
              responses=error_responses(400, 401, 403, 404, 409, 422),
              summary="更新任务（关键词/来源/调度/开关）")
async def update_task(task_id: UUID, payload: CollectionTaskIn, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


@router.delete("/tasks/{task_id}", response_model=CollectionTaskOut,
               responses={**error_responses(401, 403, 404)},
               summary="删除任务（置 archived；历史运行与来源关联保留）")
async def delete_task(task_id: UUID, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


@router.post("/tasks/{task_id}/pause", response_model=CollectionTaskOut,
             responses=error_responses(401, 403, 404, 409),
             summary="暂停任务（暂停后不再调度，历史保留）")
async def pause_task(task_id: UUID, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


@router.post("/tasks/{task_id}/resume", response_model=CollectionTaskOut,
             responses=error_responses(401, 403, 404, 409),
             summary="恢复任务调度")
async def resume_task(task_id: UUID, db: DbSession) -> CollectionTaskOut:
    raise NotImplementedError


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
async def run_task_now(task_id: UUID, db: DbSession) -> AsyncJobAcceptedOut:
    raise NotImplementedError


# --- runs ---

@router.get("/runs", response_model=PaginatedResponse[CollectionRunOut],
            responses=error_responses(401, 403),
            summary="分页查询执行记录（按任务/触发方式筛选）")
async def list_runs(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    task_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionRunOut]:
    raise NotImplementedError


@router.get("/runs/{run_id}", response_model=CollectionRunOut,
            responses=error_responses(401, 403, 404), summary="执行详情")
async def get_run(run_id: UUID, db: DbSession) -> CollectionRunOut:
    raise NotImplementedError


# --- results ---

@router.get("/results", response_model=PaginatedResponse[CollectionResultOut],
            responses=error_responses(401, 403),
            summary="分页查询采集结果（按 run/解析/入库状态筛选）")
async def list_results(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    run_id: UUID | None = Query(default=None),
    parse_status: str | None = Query(default=None),
    materialize_status: str | None = Query(default=None),
) -> PaginatedResponse[CollectionResultOut]:
    raise NotImplementedError


@router.get("/results/{result_id}", response_model=CollectionResultOut,
            responses=error_responses(401, 403, 404), summary="采集结果详情（含原文链接与来源）")
async def get_result(result_id: UUID, db: DbSession) -> CollectionResultOut:
    raise NotImplementedError


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
async def materialize_result(result_id: UUID, db: DbSession) -> AsyncJobAcceptedOut:
    raise NotImplementedError


BULK_RESULT_EXAMPLE = {
    "items": [
        {"result_id": "11111111-1111-4111-8111-111111111111", "status": "materialized", "material_id": "22222222-2222-4222-8222-222222222222", "error": None},
        {"result_id": "33333333-3333-4333-8333-333333333333", "status": "duplicate", "material_id": "44444444-4444-4444-8444-444444444444", "error": None},
        {"result_id": "55555555-5555-4555-8555-555555555555", "status": "failed", "material_id": None, "error": "正文解析失败"},
    ],
    "counts": {"materialized": 1, "duplicate": 1, "new_progress": 0, "ignored": 0, "failed": 1},
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
async def bulk_materialize(payload: BulkMaterializeIn, db: DbSession) -> BulkResultOut:
    raise NotImplementedError


@router.post(
    "/results/{result_id}/ignore",
    responses={
        **error_responses(401, 403, 404, 409),
        200: _not_ready("忽略：结果置为 ignored，不建素材"),
    },
    summary="忽略采集结果",
)
async def ignore_result(result_id: UUID, db: DbSession) -> ErrorEnvelope:
    raise NotImplementedError


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
async def retry_parse(result_id: UUID, db: DbSession) -> AsyncJobAcceptedOut:
    raise NotImplementedError
