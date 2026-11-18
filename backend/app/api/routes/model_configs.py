"""Model configuration endpoints (task 3.14 contract; 3.16 impl)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.schemas.auth import PermissionCode
from app.schemas.common import PaginatedResponse
from app.schemas.model_config import (
    ModelConfigIn,
    ModelConfigOut,
    ModelConnectionTestOut,
)
from app.schemas.model_config import ModelConfigUpdateIn
from app.services import audit_service, model_config_service

router = APIRouter(prefix="/model-configs", tags=["model-configs"])

READ = Depends(require_permission(PermissionCode.SETTINGS_READ))
WRITE = Depends(require_permission(PermissionCode.SETTINGS_WRITE))
CSRF = Depends(verify_csrf)


@router.get(
    "/{config_id}",
    response_model=ModelConfigOut,
    responses=error_responses(401, 403, 404),
)
async def get_model_config(config_id: UUID, db: DbSession, _perm=READ):
    return _out(model_config_service.get_config(db.connection(), config_id))


@router.patch(
    "/{config_id}",
    response_model=ModelConfigOut,
    responses=error_responses(401, 403, 404, 422),
)
async def update_model_config(
    config_id: UUID,
    payload: ModelConfigUpdateIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
):
    from sqlalchemy import text

    model_config_service.get_config(db.connection(), config_id)
    values = payload.model_dump(exclude_unset=True)
    if values:
        assignments = ",".join(f"{column}=:{column}" for column in values)
        row = (
            db.connection()
            .execute(
                text(
                    f"UPDATE model_configs SET {assignments},config_version=config_version+1,updated_at=now() WHERE id=:id RETURNING *"
                ),
                {"id": str(config_id), **values},
            )
            .mappings()
            .one()
        )
        audit_service.record_operation(
            db.connection(),
            user_id=user.id,
            action="model_config.update",
            object_type="model_config",
            object_id=config_id,
        )
        db.commit()
    else:
        row = model_config_service.get_config(db.connection(), config_id)
    return _out(row)


def _out(row: dict) -> ModelConfigOut:
    return ModelConfigOut(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        purpose=row["purpose"],
        endpoint=row["endpoint"],
        model_name=row["model_name"],
        credential_configured=bool(row.get("credential_ref")),
        enabled=row["enabled"],
        config_version=row["config_version"],
        max_input_tokens=row["max_input_tokens"],
        max_output_tokens=row["max_output_tokens"],
        timeout_seconds=row["timeout_seconds"],
        params=row.get("params") or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get(
    "",
    response_model=PaginatedResponse[ModelConfigOut],
    responses=error_responses(401, 403),
    summary="分页查询模型配置（凭据只返回是否已配置）",
)
async def list_model_configs(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    purpose: str | None = Query(
        default=None, description="analysis/generation/embedding"
    ),
) -> PaginatedResponse[ModelConfigOut]:
    rows, total = model_config_service.list_configs(
        db.connection(), page, page_size, purpose
    )
    return PaginatedResponse(
        items=[_out(row) for row in rows], total=total, page=page, page_size=page_size
    )


@router.post(
    "",
    response_model=ModelConfigOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 409, 422),
    summary="创建模型配置（凭据引用不回显）",
)
async def create_model_config(
    payload: ModelConfigIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> ModelConfigOut:
    config = model_config_service.create_config(db.connection(), payload, user.id)
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="model_config.create",
        object_type="model_config",
        object_id=config["id"],
        detail={"name": config["name"], "purpose": config["purpose"]},
    )
    db.commit()
    return _out(config)


@router.post(
    "/{config_id}/test",
    response_model=ModelConnectionTestOut,
    responses=error_responses(401, 403, 404, 503),
    summary="模型连接测试（脱敏失败原因）",
)
async def test_model_config(
    config_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> ModelConnectionTestOut:
    result = model_config_service.test_connection(db.connection(), config_id)
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="model_config.test",
        object_type="model_config",
        object_id=config_id,
        result="success" if result["reachable"] else "failed",
        detail={"error": result.get("error")},
    )
    db.commit()
    return ModelConnectionTestOut(**result)
