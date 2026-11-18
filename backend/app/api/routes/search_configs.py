"""Search service configuration endpoints (task 3.14 contract; 3.17 impl)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.schemas.auth import PermissionCode
from app.schemas.common import PaginatedResponse
from app.schemas.search_config import SearchConfigIn, SearchConfigOut, SearchConfigUpdateIn, SearchConnectionTestOut
from app.repositories import search_config_repository as repo
from app.services import audit_service, search_config_service as service

router = APIRouter(prefix="/search-configs", tags=["search-configs"])

READ = Depends(require_permission(PermissionCode.SETTINGS_READ))
WRITE = Depends(require_permission(PermissionCode.SETTINGS_WRITE))
CSRF = Depends(verify_csrf)


def _out(row: dict) -> SearchConfigOut:
    return SearchConfigOut(**{**row, "credential_configured": bool(row.get("credential_ref"))})


@router.get("/{config_id}", response_model=SearchConfigOut, responses=error_responses(401, 403, 404))
async def get_search_config(config_id: UUID, db: DbSession, _perm=READ) -> SearchConfigOut:
    return _out(service.get_config(db.connection(), config_id))


@router.get(
    "",
    response_model=PaginatedResponse[SearchConfigOut],
    responses=error_responses(401, 403),
    summary="分页查询搜索配置（凭据只返回是否已配置）",
)
async def list_search_configs(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[SearchConfigOut]:
    rows, total = repo.list_configs(db.connection(), page, page_size)
    return PaginatedResponse(items=[_out(row) for row in rows], total=total, page=page, page_size=page_size)


@router.post(
    "",
    response_model=SearchConfigOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 409, 422),
    summary="创建搜索配置",
)
async def create_search_config(
    payload: SearchConfigIn, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE,
) -> SearchConfigOut:
    config = service.save_config(db.connection(), payload)
    audit_service.record_operation(db.connection(), user_id=user.id, action="search_config.create",
                                   object_type="search_config", object_id=config["id"],
                                   detail={"config_version": config["config_version"]})
    db.commit()
    return _out(config)


@router.patch("/{config_id}", response_model=SearchConfigOut,
              responses=error_responses(401, 403, 404, 409, 422), summary="更新或启停搜索配置")
async def update_search_config(config_id: UUID, payload: SearchConfigUpdateIn, db: DbSession,
                               user: CurrentUserDep, _csrf=CSRF, _perm=WRITE) -> SearchConfigOut:
    config = service.save_config(db.connection(), payload, config_id)
    audit_service.record_operation(db.connection(), user_id=user.id, action="search_config.update",
                                   object_type="search_config", object_id=config_id,
                                   detail={"config_version": config["config_version"]})
    db.commit()
    return _out(config)


@router.post(
    "/{config_id}/test",
    response_model=SearchConnectionTestOut,
    responses=error_responses(401, 403, 404, 503),
    summary="搜索服务连接测试（脱敏失败原因）",
)
def test_search_config(
    config_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF, _perm=WRITE,
) -> SearchConnectionTestOut:
    config = service.get_config(db.connection(), config_id)
    # Authentication/read transaction ends before a possibly slow network call.
    db.commit()
    result = service.probe(config)
    audit_service.record_operation(db.connection(), user_id=user.id, action="search_config.test",
                                   object_type="search_config", object_id=config_id,
                                   result="success" if result["reachable"] else "failed",
                                   detail={"error_code": result["error_code"]})
    db.commit()
    return SearchConnectionTestOut(**result)
