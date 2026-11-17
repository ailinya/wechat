"""Role and permission endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.errors import ApiError
from app.repositories import auth_repository as repo
from app.schemas.auth import PermissionCode, RoleSummary
from app.schemas.common import PaginatedResponse
from app.schemas.users import RoleCreate, RoleOut, RolePermissionUpdate, RoleWithUsers

router = APIRouter(prefix="/roles", tags=["roles"])

READ = Depends(require_permission(PermissionCode.ROLE_READ))
WRITE = Depends(require_permission(PermissionCode.ROLE_WRITE))
CSRF = Depends(verify_csrf)


def _role_out(row: dict, db) -> RoleOut:
    conn = db.connection()
    perms = repo.permissions_for_role(conn, row["id"])
    from app.schemas.auth import PermissionOut
    return RoleOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        permissions=[
            PermissionOut(
                id=p["id"],
                code=PermissionCode(p["code"]),
                module=p["module"],
                action=p["action"],
            )
            for p in perms
            if p["code"] in PermissionCode._value2member_map_
        ],
    )


@router.get(
    "",
    response_model=PaginatedResponse[RoleOut],
    responses={**error_responses(401, 403, 422)},
    summary="分页查询角色",
)
async def list_roles(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[RoleOut]:
    rows, total = repo.list_roles(db.connection(), page, page_size)
    return PaginatedResponse(
        items=[_role_out(row, db) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=RoleOut,
    responses={**error_responses(401, 403, 409, 422)},
    status_code=201,
    summary="创建角色",
)
async def create_role(
    payload: RoleCreate,
    db: DbSession,
    _csrf=CSRF,
    _perm=WRITE,
) -> RoleOut:
    conn = db.connection()
    if repo.role_id_by_name(conn, payload.name):
        raise ApiError(409, "conflict", "角色名称已存在")
    role_id = repo.create_role(conn, payload.name, payload.description)
    db.commit()
    return _role_out(repo.get_role(conn, role_id), db)


@router.get(
    "/{role_id}",
    response_model=RoleWithUsers,
    responses={**error_responses(401, 403, 404)},
    summary="角色详情（含关联用户）",
)
async def get_role(
    role_id: UUID,
    db: DbSession,
    _perm=READ,
) -> RoleWithUsers:
    conn = db.connection()
    row = repo.get_role(conn, role_id)
    if not row:
        raise ApiError(404, "not_found", "角色不存在")
    base = _role_out(row, db)
    users = repo.users_for_role(conn, role_id)
    return RoleWithUsers(
        **base.model_dump(),
        users=[RoleSummary(id=u["id"], name=u["name"]) for u in users],
    )


@router.put(
    "/{role_id}/permissions",
    response_model=RoleOut,
    responses={**error_responses(401, 403, 404, 422)},
    summary="替换角色权限集合",
)
async def replace_role_permissions(
    role_id: UUID,
    payload: RolePermissionUpdate,
    db: DbSession,
    _csrf=CSRF,
    _perm=WRITE,
) -> RoleOut:
    conn = db.connection()
    if not repo.get_role(conn, role_id):
        raise ApiError(404, "not_found", "角色不存在")
    permission_ids = []
    for code in payload.permission_codes:
        pid = repo.permission_id_by_code(conn, code.value)
        if pid:
            permission_ids.append(pid)
    repo.replace_role_permissions(conn, role_id, permission_ids)
    db.commit()
    return _role_out(repo.get_role(conn, role_id), db)
