"""Async job query and cancellation endpoints (task 2.2).

Job acceptance (HTTP 202 with AsyncJobAcceptedOut) happens on the module
endpoints that create side effects (collection runs, creation tasks, ...);
their contracts reference the shared AsyncJobAcceptedOut schema.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, DbSession, verify_csrf
from app.api.responses import error_responses
from app.errors import ApiError
from app.services import audit_service
from app.repositories import async_job_repository as repo
from app.schemas.async_jobs import AsyncJobOut
from app.schemas.common import ErrorEnvelope, PaginatedResponse

router = APIRouter(prefix="/async-jobs", tags=["async-jobs"])

JOB_EXAMPLE = {
    "id": "0d1c6a3e-6f4a-4a5d-9a44-8d0b6c5f21aa",
    "job_type": "collection.fetch",
    "resource_type": "collection_task",
    "resource_id": "7b2d8c1a-1e2f-4b3c-8d4e-5f6a7b8c9d0e",
    "status": "running",
    "stage": "fetching",
    "progress": 40,
    "attempts": 1,
    "last_error": None,
    "started_at": "2026-11-17T08:00:05Z",
    "finished_at": None,
    "created_at": "2026-11-17T08:00:00Z",
    "updated_at": "2026-11-17T08:00:40Z",
}

ACCEPTED_EXAMPLE = {
    "async_job_id": "0d1c6a3e-6f4a-4a5d-9a44-8d0b6c5f21aa",
    "resource_type": "collection_run",
    "resource_id": "7b2d8c1a-1e2f-4b3c-8d4e-5f6a7b8c9d0e",
    "status": "accepted",
}


def _job_out(row: dict) -> AsyncJobOut:
    return AsyncJobOut(
        id=row["id"],
        job_type=row["job_type"],
        resource_type=row["resource_type"],
        resource_id=row["resource_id"],
        status=row["status"],
        stage=row["stage"],
        progress=row["progress"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "",
    response_model=PaginatedResponse[AsyncJobOut],
    responses={**error_responses(401, 422)},
    summary="分页查询当前用户的异步任务",
)
async def list_jobs(
    db: DbSession,
    user: CurrentUserDep,
    job_type: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[AsyncJobOut]:
    if status is not None and status not in ("pending", "running", "succeeded", "failed", "cancelled"):
        raise ApiError(422, "validation_error", "status 取值不合法")
    rows, total = repo.list_jobs(
        db.connection(), user.id, job_type, status, page, page_size
    )
    return PaginatedResponse(
        items=[_job_out(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get(
    "/{job_id}",
    response_model=AsyncJobOut,
    responses={
        **error_responses(401, 403, 404),
        200: {
            "model": AsyncJobOut,
            "description": "任务当前状态（未就绪时 status 为 pending/running）",
            "content": {"application/json": {"example": JOB_EXAMPLE}},
        },
    },
    summary="查询单个异步任务状态",
)
async def get_job(job_id: UUID, db: DbSession, user: CurrentUserDep) -> AsyncJobOut:
    row = repo.get_job(db.connection(), job_id)
    if not row:
        raise ApiError(404, "not_found", "任务不存在")
    if row["created_by"] != user.id:
        raise ApiError(403, "forbidden", "只能查询本人发起的任务")
    return _job_out(row)


@router.post(
    "/{job_id}/cancel",
    response_model=AsyncJobOut,
    responses={
        **error_responses(401, 403, 404, 409),
        409: {
            "model": ErrorEnvelope,
            "description": "任务已处于终态（完成/失败/已取消），无法取消",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "job_not_cancellable",
                            "message": "任务已完成或已取消，无法再次取消",
                        }
                    }
                }
            },
        },
    },
    summary="取消待执行或执行中的任务",
)
async def cancel_job(job_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=Depends(verify_csrf)) -> AsyncJobOut:
    row = repo.get_job(db.connection(), job_id)
    if not row:
        raise ApiError(404, "not_found", "任务不存在")
    if row['job_type'] in ('publish.execute', 'account.sync', 'wechat.draft'):
        raise ApiError(409, 'job_not_cancellable', '该任务请使用业务页面处理；发布只能在未执行时取消订单')
    if row["created_by"] != user.id:
        audit_service.record_operation(
            db.connection(), user_id=user.id, action="async_job.cancel",
            object_type="async_job", object_id=job_id, result="denied",
        )
        db.commit()
        raise ApiError(403, "forbidden", "只能取消本人发起的任务")
    cancelled = repo.cancel_job(db.connection(), job_id, user.id)
    if not cancelled:
        raise ApiError(409, "job_not_cancellable", "任务已完成或已取消，无法再次取消")
    audit_service.record_operation(
        db.connection(), user_id=user.id, action="async_job.cancel",
        object_type="async_job", object_id=job_id, result="success",
    )
    db.commit()
    return _job_out(cancelled)
