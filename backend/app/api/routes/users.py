"""User management endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.errors import ApiError
from app.repositories import auth_repository as repo
from app.schemas.auth import PermissionCode, RoleSummary
from app.schemas.common import PaginatedResponse
from app.schemas.users import UserCreate, UserOut, UserUpdate
from app.services.auth_service import hash_password

router = APIRouter(prefix="/users", tags=["users"])

READ = Depends(require_permission(PermissionCode.USER_READ))
WRITE = Depends(require_permission(PermissionCode.USER_WRITE))
CSRF = Depends(verify_csrf)


def _user_out(row: dict, db) -> UserOut:
    role_rows = repo.roles_for_user(db.connection(), row["id"])
    return UserOut(
        id=row["id"],
        account=row["account"],
        name=row["name"],
        contact=row.get("contact"),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        roles=[RoleSummary(id=r["id"], name=r["name"]) for r in role_rows],
    )


@router.get(
    "",
    response_model=PaginatedResponse[UserOut],
    responses={**error_responses(401, 403, 422)},
    summary="分页查询用户",
)
async def list_users(
    db: DbSession,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
) -> PaginatedResponse[UserOut]:
    rows, total = repo.list_users(db.connection(), page, page_size, status, keyword)
    return PaginatedResponse(
        items=[_user_out(row, db) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=UserOut,
    responses={**error_responses(401, 403, 409, 422)},
    status_code=201,
    summary="创建用户",
)
async def create_user(
    payload: UserCreate,
    db: DbSession,
    _csrf=CSRF,
    _perm=WRITE,
) -> UserOut:
    conn = db.connection()
    if repo.find_user_by_account(conn, payload.account):
        raise ApiError(409, "conflict", "账号已存在")
    role_ids = _resolve_role_ids(conn, payload.role_ids)
    user_id = repo.create_user(
        conn,
        account=payload.account,
        name=payload.name,
        contact=payload.contact,
        password_hash=hash_password(payload.password),
        role_ids=role_ids,
    )
    db.commit()
    return _user_out(repo.get_user(db.connection(), user_id), db)


@router.get(
    "/{user_id}",
    response_model=UserOut,
    responses={**error_responses(401, 403, 404)},
    summary="用户详情",
)
async def get_user(
    user_id: UUID,
    db: DbSession,
    _perm=READ,
) -> UserOut:
    row = repo.get_user(db.connection(), user_id)
    if not row:
        raise ApiError(404, "not_found", "用户不存在")
    return _user_out(row, db)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    responses={**error_responses(401, 403, 404, 409, 422)},
    summary="更新用户（含启停与角色分配）",
)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: DbSession,
    _csrf=CSRF,
    _perm=WRITE,
) -> UserOut:
    conn = db.connection()
    row = repo.get_user(conn, user_id)
    if not row:
        raise ApiError(404, "not_found", "用户不存在")
    role_ids = _resolve_role_ids(conn, payload.role_ids) if payload.role_ids is not None else None
    repo.update_user(
        conn,
        user_id,
        name=payload.name,
        contact=payload.contact,
        status=payload.status,
        role_ids=role_ids,
    )
    db.commit()
    return _user_out(repo.get_user(db.connection(), user_id), db)


def _resolve_role_ids(conn, role_ids: list[UUID]) -> list[UUID]:
    return [rid for rid in role_ids if repo.get_role(conn, rid)]
