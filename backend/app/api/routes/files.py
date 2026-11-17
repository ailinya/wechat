"""File upload authorization, completion and download endpoints (task 2.6).

Grant creation accepts an optional Idempotency-Key (task 2.5): same key and
content replays the original grant, same key with different content is a
409 idempotency_conflict. Long-term storage credentials never leave the
server; clients only receive short-term presigned URLs.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.api.deps import CurrentUserDep, DbSession, get_settings
from app.api.responses import error_responses, idempotency_conflict_response
from app.config import Settings
from app.errors import ApiError
from app.schemas.common import ErrorEnvelope
from app.schemas.files import (
    DownloadGrantOut,
    StoredObjectOut,
    UploadCompleteRequest,
    UploadGrantOut,
    UploadGrantRequest,
)
from app.services import audit_service, file_storage_service, idempotency_service

router = APIRouter(prefix="/files", tags=["files"])

GRANT_EXAMPLE = {
    "id": "c1a7d9e0-2b3c-4d5e-8f60-718293a4b5c6",
    "bucket": "attachments",
    "object_key": "2026/11/c1a7d9e0-cover.png",
    "content_type": "image/png",
    "size_bytes": 204800,
    "expires_at": "2026-11-17T08:15:00Z",
    "upload_url": "https://rustfs.local/attachments/2026/11/c1a7d9e0-cover.png?X-Amz-Expires=900",
}

STORED_EXAMPLE = {
    "id": "9f8e7d6c-5b4a-4938-8271-6f5e4d3c2b1a",
    "bucket": "attachments",
    "object_key": "2026/11/c1a7d9e0-cover.png",
    "size_bytes": 204800,
    "content_type": "image/png",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "created_at": "2026-11-17T08:05:00Z",
}

DOWNLOAD_EXAMPLE = {
    "object_id": "9f8e7d6c-5b4a-4938-8271-6f5e4d3c2b1a",
    "url": "https://rustfs.local/attachments/2026/11/c1a7d9e0-cover.png?X-Amz-Expires=300",
    "expires_at": "2026-11-17T08:10:00Z",
}

FORBIDDEN_EXAMPLE = {"error": {"code": "forbidden", "message": "只能完成本人申请的上传授权"}}


def _grant_out(grant: dict) -> UploadGrantOut:
    return UploadGrantOut(
        id=grant["id"],
        bucket=grant["bucket"],
        object_key=grant["object_key"],
        content_type=grant["content_type"],
        size_bytes=grant["max_bytes"],
        expires_at=grant["expires_at"],
        upload_url=grant.get("upload_url"),
    )


def _stored_out(stored: dict) -> StoredObjectOut:
    return StoredObjectOut(
        id=stored["id"],
        bucket=stored["bucket"],
        object_key=stored["object_key"],
        size_bytes=stored["size_bytes"],
        content_type=stored["content_type"],
        sha256=stored["sha256"],
        created_at=stored["created_at"],
    )


@router.post(
    "/upload-grants",
    response_model=UploadGrantOut,
    status_code=201,
    responses={
        **error_responses(400, 401, 403, 409, 422, 503),
        409: idempotency_conflict_response(),
        201: {
            "model": UploadGrantOut,
            "description": "上传授权（含短期直传地址）",
            "content": {"application/json": {"example": GRANT_EXAMPLE}},
        },
    },
    summary="申请限定范围的上传授权",
)
async def create_upload_grant(
    payload: UploadGrantRequest,
    db: DbSession,
    user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> UploadGrantOut:
    conn = db.connection()
    idem_row = None
    if idempotency_key:
        fingerprint = idempotency_service.request_fingerprint(payload.model_dump())
        try:
            idem_row = idempotency_service.begin_request(
                conn, "files.upload_grant", user.id, idempotency_key, fingerprint
            )
        except idempotency_service.IdempotencyReplay as replay:
            # Same key + same content with a stored result: replay it.
            return UploadGrantOut.model_validate(replay.row["response_body"])
        except idempotency_service.IdempotencyConflict:
            raise ApiError(409, "idempotency_conflict", "该幂等键已被用于不同的请求内容") from None
        if idem_row.get("response_status") == 201:
            return UploadGrantOut.model_validate(idem_row["response_body"])

    try:
        grant = file_storage_service.create_grant(
            conn, settings, user.id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
    except ApiError as exc:
        db.rollback()
        audit_service.record_operation(
            db.connection(), user_id=user.id, action="file.upload_grant",
            object_type="upload_grant", result="denied",
            detail={"filename": payload.filename, "reason": exc.code},
        )
        db.commit()
        raise
    audit_service.record_operation(
        conn, user_id=user.id, action="file.upload_grant",
        object_type="upload_grant", object_id=grant["id"], result="success",
        detail={"filename": payload.filename, "size_bytes": payload.size_bytes},
    )
    db.commit()
    body = _grant_out(grant).model_dump(mode="json")
    if idem_row is not None:
        idempotency_service.store_response(db.connection(), idem_row["id"], 201, body)
        db.commit()
    return UploadGrantOut.model_validate(body)

@router.post(
    "/upload-grants/{grant_id}/complete",
    response_model=StoredObjectOut,
    responses={
        **error_responses(400, 401, 403, 404, 422),
        200: {
            "model": StoredObjectOut,
            "description": "登记完成；同一授权重复提交返回同一文件标识（幂等恢复）",
            "content": {"application/json": {"example": STORED_EXAMPLE}},
        },
        400: {
            "model": ErrorEnvelope,
            "description": "授权过期或对象与授权不符",
            "content": {
                "application/json": {
                    "examples": {
                        "grant_expired": {
                            "summary": "授权过期",
                            "value": {"error": {"code": "grant_expired", "message": "上传授权已过期，请重新申请"}},
                        },
                        "object_mismatch": {
                            "summary": "对象与授权不符",
                            "value": {"error": {"code": "object_mismatch", "message": "实际文件大小或类型与授权不符"}},
                        },
                        "object_not_uploaded": {
                            "summary": "对象不存在",
                            "value": {"error": {"code": "object_not_uploaded", "message": "对象尚未上传或不存在"}},
                        },
                    }
                }
            },
        },
        403: {
            "model": ErrorEnvelope,
            "description": "越权完成（他人授权）",
            "content": {"application/json": {"example": FORBIDDEN_EXAMPLE}},
        },
    },
    summary="完成登记（后端校验后创建可用文件记录）",
)
async def complete_upload(
    grant_id: UUID,
    payload: UploadCompleteRequest,
    db: DbSession,
    user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
) -> StoredObjectOut:
    stored = file_storage_service.complete_grant(
        db.connection(), settings, user.id, str(grant_id), payload.sha256
    )
    db.commit()
    return _stored_out(stored)


@router.post(
    "/{object_id}/download-grant",
    response_model=DownloadGrantOut,
    responses={
        **error_responses(401, 403, 404),
        200: {
            "model": DownloadGrantOut,
            "description": "短期下载授权",
            "content": {"application/json": {"example": DOWNLOAD_EXAMPLE}},
        },
    },
    summary="申请受控下载授权",
)
async def create_download_grant(
    object_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
) -> DownloadGrantOut:
    grant = file_storage_service.create_download_grant(
        db.connection(), settings, user.id, str(object_id), has_resource_access=False
    )
    db.commit()
    return DownloadGrantOut.model_validate(grant)
