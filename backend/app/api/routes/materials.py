"""Material library endpoints (tasks 3.1 contracts, 3.8 implementation).

Favorites are user-isolated; DELETE is a soft delete preserving references.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.adapters import object_storage
from app.api.deps import (
    CurrentUserDep,
    DbSession,
    get_settings,
    require_permission,
    verify_csrf,
)
from app.api.responses import error_responses
from app.config import Settings
from app.errors import ApiError
from app.repositories import material_repository as repo
from app.schemas.auth import PermissionCode
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.schemas.materials import (
    BulkActionIn,
    BulkActionOut,
    FavoriteOut,
    EmbeddingRebuildIn,
    EmbeddingRebuildOut,
    MaterialSearchIn,
    MaterialSearchOut,
    MaterialCategoryIn,
    MaterialCategoryOut,
    MaterialCreateIn,
    MaterialDeleteOut,
    MaterialDetailOut,
    MaterialLinkIn,
    MaterialOut,
    MaterialRevisionOut,
    MaterialUpdateIn,
    MaterialUploadIn,
    TagIn,
    TagOut,
)
from app.services import material_embedding_service, material_search_service, material_service
from app.schemas.analysis import MaterialAnalysisIn

router = APIRouter(prefix="/materials", tags=["materials"])

READ = Depends(require_permission(PermissionCode.MATERIAL_READ))
WRITE = Depends(require_permission(PermissionCode.MATERIAL_WRITE))
REBUILD = Depends(require_permission(PermissionCode.SETTINGS_WRITE))
SEARCH = Depends(require_permission(PermissionCode.MATERIAL_SEARCH))
CSRF = Depends(verify_csrf)


@router.post("/search", response_model=MaterialSearchOut, responses=error_responses(401, 403, 422))
def search_materials(payload: MaterialSearchIn, db: DbSession, _csrf=CSRF, _perm=SEARCH):
    return MaterialSearchOut(**material_search_service.search(db.connection(), payload))


@router.post(
    "/{material_id}/analysis",
    status_code=202,
    responses=error_responses(401, 403, 404, 409),
)
async def request_analysis(
    material_id: UUID,
    payload: MaterialAnalysisIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
):
    from app.services import async_job_service, outbox_service, audit_service

    material_service.get_detail(db.connection(), material_id, user.id)
    job = async_job_service.create_job(
        db.connection(),
        "material.analysis",
        "material",
        material_id,
        payload={"material_id": str(material_id), **payload.model_dump(mode="json")},
        created_by=user.id,
    )
    outbox_service.publish_event(
        db.connection(),
        "material.analysis.requested",
        "material",
        material_id,
        payload={
            "task": "app.modules.async_execution.tasks.run_async_job",
            "kwargs": {"job_id": job["id"]},
        },
    )
    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="material.analysis.request",
        object_type="material",
        object_id=material_id,
    )
    db.commit()
    return {
        "async_job_id": str(job["id"]),
        "resource_id": str(material_id),
        "resource_type": "material",
        "status": "accepted",
    }


@router.post(
    "/{material_id}/embedding-rebuild",
    response_model=EmbeddingRebuildOut,
    status_code=202,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="为素材正文修订异步重建向量",
)
async def request_embedding_rebuild(
    material_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    payload: EmbeddingRebuildIn | None = None,
    _csrf=CSRF,
    _perm=REBUILD,
) -> EmbeddingRebuildOut:
    result = material_embedding_service.enqueue_rebuild(
        db.connection(),
        material_id,
        revision_id=payload.revision_id if payload else None,
        user_id=user.id,
    )
    from app.services import audit_service

    audit_service.record_operation(
        db.connection(),
        user_id=user.id,
        action="material.embedding.rebuild",
        object_type="material",
        object_id=material_id,
    )
    db.commit()
    return EmbeddingRebuildOut(**result)


def _category_out(row: dict) -> MaterialCategoryOut:
    return MaterialCategoryOut(
        id=row["id"],
        name=row["name"],
        parent_id=row.get("parent_id"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _tag_out(row: dict) -> TagOut:
    return TagOut(id=row["id"], name=row["name"])


def _material_out(row: dict, db) -> MaterialOut:
    return MaterialOut(
        id=row["id"],
        title=row["title"],
        origin=row["origin"],
        usage_status=row["usage_status"],
        current_revision_id=row["current_revision_id"],
        category_id=row.get("category_id"),
        metadata_version=row.get("metadata_version", 1),
        summary=row.get("summary", ""),
        tags=[
            _tag_out(tag) for tag in repo.tags_for_material(db.connection(), row["id"])
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _revision_out(row: dict) -> MaterialRevisionOut:
    import json

    files = row.get("file_ids") or []
    if isinstance(files, str):
        files = json.loads(files)
    return MaterialRevisionOut(
        id=row["id"],
        material_id=row["material_id"],
        revision_no=row["revision_no"],
        content_markdown=row["content_markdown"],
        file_ids=[str(f) for f in files],
        created_by=row.get("created_by"),
        created_at=row["created_at"],
    )


def _detail_out(detail: dict, db) -> MaterialDetailOut:
    base = _material_out(detail["material"], db)
    return MaterialDetailOut(
        **base.model_dump(),
        current_revision=_revision_out(detail["revision"]),
        favorite_count=detail["favorite_count"],
        favorited_by_me=detail["favorited_by_me"],
    )


# --- materials ---


@router.get(
    "",
    response_model=PaginatedResponse[MaterialOut],
    responses=error_responses(401, 403),
    summary="分页查询素材（状态/分类/标签/关键词/我的收藏筛选）",
)
async def list_materials(
    db: DbSession,
    user: CurrentUserDep,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    usage_status: str | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    tag_id: UUID | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
    favorite_mine: bool = Query(default=False),
) -> PaginatedResponse[MaterialOut]:
    rows, total = material_service.list_materials(
        db.connection(),
        page,
        page_size,
        user.id,
        usage_status=usage_status,
        category_id=category_id,
        tag_id=tag_id,
        keyword=keyword,
        favorite_mine=favorite_mine,
    )
    return PaginatedResponse(
        items=[_material_out(row, db) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=MaterialOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 422),
    summary="手工创建素材（首修订，版本号 1）",
)
async def create_material(
    payload: MaterialCreateIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialOut:
    material = material_service.create_from_text(db.connection(), payload, user.id)
    db.commit()
    return _material_out(material, db)


@router.post(
    "/from-link",
    response_model=MaterialOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 422),
    summary="从网页链接创建素材（抓取并解析正文）",
)
async def create_from_link(
    payload: MaterialLinkIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialOut:
    material = material_service.create_from_link(
        db.connection(), payload.url, payload.title, user.id
    )
    db.commit()
    return _material_out(material, db)


@router.post(
    "/from-upload",
    response_model=MaterialOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 422, 503),
    summary="从已登记上传对象创建素材（服务端解析）",
)
async def create_from_upload(
    payload: MaterialUploadIn,
    db: DbSession,
    user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialOut:
    conn = db.connection()
    stored = (
        conn.execute(
            "SELECT * FROM stored_objects WHERE id = :id",
            {"id": str(payload.object_id)},
        )
        .mappings()
        .first()
    )
    if not stored:
        raise ApiError(404, "not_found", "上传对象不存在")
    meta = dict(stored)
    data = object_storage.get_object(settings, meta["object_key"])
    material = material_service.create_from_upload(
        conn,
        object_id=payload.object_id,
        object_meta=meta,
        data=data,
        title=payload.title,
        user_id=user.id,
    )
    db.commit()
    return _material_out(material, db)


@router.get(
    "/favorites",
    response_model=PaginatedResponse[MaterialOut],
    responses=error_responses(401, 403),
    summary="我的收藏列表（按用户隔离）",
)
async def my_favorites(
    db: DbSession,
    user: CurrentUserDep,
    _perm=READ,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[MaterialOut]:
    rows, total = material_service.list_materials(
        db.connection(),
        page,
        page_size,
        user.id,
        usage_status=None,
        category_id=None,
        tag_id=None,
        keyword=None,
        favorite_mine=True,
    )
    return PaginatedResponse(
        items=[_material_out(row, db) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/bulk",
    response_model=BulkActionOut,
    responses=error_responses(401, 403, 422),
    summary="批量操作（归档/取消归档/标记使用/设置分类/增删标签，返回逐项结果）",
)
async def bulk_action(
    payload: BulkActionIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> BulkActionOut:
    result = material_service.bulk_action(db.connection(), payload, user.id)
    db.commit()
    return BulkActionOut.model_validate(result)


# --- categories ---


@router.get(
    "/categories",
    response_model=list[MaterialCategoryOut],
    responses=error_responses(401, 403),
    summary="分类树（层级）",
)
async def list_categories(db: DbSession, _perm=READ) -> list[MaterialCategoryOut]:
    return [_category_out(row) for row in repo.list_categories(db.connection())]


@router.post(
    "/categories",
    response_model=MaterialCategoryOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="创建分类（parent_id 不得形成循环）",
)
async def create_category(
    payload: MaterialCategoryIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialCategoryOut:
    category = material_service.create_category(
        db.connection(), payload.name, payload.parent_id
    )
    db.commit()
    return _category_out(category)


@router.patch(
    "/categories/{category_id}",
    response_model=MaterialCategoryOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新分类（改名/移动父级；循环引用返回 409）",
)
async def update_category(
    category_id: UUID,
    payload: MaterialCategoryIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialCategoryOut:
    category = material_service.update_category(
        db.connection(), category_id, payload.name, payload.parent_id
    )
    db.commit()
    return _category_out(category)


@router.delete(
    "/categories/{category_id}",
    responses=error_responses(401, 403, 404, 409),
    summary="删除分类（非空返回 409）",
)
async def delete_category(
    category_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> None:
    material_service.delete_category(db.connection(), category_id)
    db.commit()


# --- tags ---


@router.get(
    "/tags",
    response_model=list[TagOut],
    responses=error_responses(401, 403),
    summary="全部标签",
)
async def list_tags(db: DbSession, _perm=READ) -> list[TagOut]:
    return [_tag_out(row) for row in repo.list_tags(db.connection())]


@router.post(
    "/tags",
    response_model=TagOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 409, 422),
    summary="创建标签（同名 409）",
)
async def create_tag(
    payload: TagIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> TagOut:
    tag = material_service.create_tag(db.connection(), payload.name)
    db.commit()
    return _tag_out(tag)


@router.patch(
    "/tags/{tag_id}",
    response_model=TagOut,
    responses=error_responses(401, 403, 404, 409, 422),
    summary="重命名标签（素材关联保留）",
)
async def update_tag(
    tag_id: UUID,
    payload: TagIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> TagOut:
    tag = material_service.update_tag(db.connection(), tag_id, payload.name)
    db.commit()
    return _tag_out(tag)


@router.delete(
    "/tags/{tag_id}",
    responses=error_responses(401, 403, 404),
    summary="删除标签（关联解除，素材保留）",
)
async def delete_tag(
    tag_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> None:
    material_service.delete_tag(db.connection(), tag_id)
    db.commit()


# --- material detail / update / delete ---


@router.get(
    "/{material_id}",
    response_model=MaterialDetailOut,
    responses=error_responses(401, 403, 404),
    summary="素材详情（当前修订正文 + 收藏状态）",
)
async def get_material(
    material_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _perm=READ,
) -> MaterialDetailOut:
    detail = material_service.get_detail(db.connection(), material_id, user.id)
    return _detail_out(detail, db)


@router.patch(
    "/{material_id}",
    response_model=MaterialDetailOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新素材：正文/标题变更创建新修订；状态/分类/标签原地变更",
)
async def update_material(
    material_id: UUID,
    payload: MaterialUpdateIn,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialDetailOut:
    detail = material_service.update_material(
        db.connection(), material_id, payload, user.id
    )
    db.commit()
    return _detail_out(detail, db)


DELETE_EXAMPLE = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "usage_status": "archived",
    "deleted_at": "2026-11-18T09:00:00Z",
    "references_preserved": True,
}


@router.delete(
    "/{material_id}",
    response_model=MaterialDeleteOut,
    responses={
        **error_responses(401, 403, 404),
        200: {
            "model": MaterialDeleteOut,
            "description": "软删除；已有引用（文章版本/采集结果/来源）保持可解析",
            "content": {"application/json": {"example": DELETE_EXAMPLE}},
        },
    },
    summary="删除素材（软删除；引用保持可解析）",
)
async def delete_material(
    material_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> MaterialDeleteOut:
    from datetime import datetime, timezone

    result = material_service.delete_material(db.connection(), material_id, user.id)
    db.commit()
    return MaterialDeleteOut(
        id=result["id"],
        usage_status=result["usage_status"],
        deleted_at=datetime.now(timezone.utc),
        references_preserved=True,
    )


@router.get(
    "/{material_id}/revisions",
    response_model=list[MaterialRevisionOut],
    responses=error_responses(401, 403, 404),
    summary="素材全部修订（revision_no 唯一递增）",
)
async def list_revisions(
    material_id: UUID,
    db: DbSession,
    _perm=READ,
) -> list[MaterialRevisionOut]:
    if not repo.material_by_id(db.connection(), material_id):
        raise ApiError(404, "not_found", "素材不存在")
    return [
        _revision_out(row) for row in repo.list_revisions(db.connection(), material_id)
    ]


@router.get(
    "/{material_id}/relations",
    response_model=list[dict],
    responses=error_responses(401, 403, 404),
    summary="素材来源关联（采集结果/上传/链接等）",
)
async def list_relations(material_id: UUID, db: DbSession, _perm=READ) -> list[dict]:
    if not repo.material_by_id(db.connection(), material_id):
        raise ApiError(404, "not_found", "素材不存在")
    return repo.material_relations(db.connection(), material_id)


@router.get(
    "/{material_id}/articles",
    response_model=list[dict],
    responses=error_responses(401, 403, 404),
    summary="引用该素材的文章版本",
)
async def list_articles(material_id: UUID, db: DbSession, _perm=READ, _article=Depends(require_permission(PermissionCode.ARTICLE_READ))) -> list[dict]:
    if not repo.material_by_id(db.connection(), material_id):
        raise ApiError(404, "not_found", "素材不存在")
    from sqlalchemy import text
    rows = db.connection().execute(text("SELECT a.id AS article_id,ar.title AS article_title,ar.id AS article_revision_id,am.material_revision_id,ar.created_at AS used_at FROM article_materials am JOIN article_revisions ar ON ar.id=am.article_revision_id JOIN articles a ON a.id=ar.article_id WHERE am.material_id=:id ORDER BY ar.created_at DESC,ar.id"), {"id": str(material_id)}).mappings().all()
    return [dict(row) for row in rows]


# --- favorites (user-isolated) ---


@router.put(
    "/{material_id}/favorite",
    response_model=FavoriteOut,
    status_code=201,
    responses=error_responses(401, 403, 404, 409),
    summary="收藏素材（同用户重复收藏幂等返回原记录）",
)
async def favorite_material(
    material_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> FavoriteOut:
    row = material_service.favorite(db.connection(), material_id, user.id)
    db.commit()
    return FavoriteOut(
        material_id=row["material_id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
    )


@router.delete(
    "/{material_id}/favorite",
    responses={
        **error_responses(401, 404),
        204: {"description": "已取消收藏（他人收藏不受影响）"},
    },
    summary="取消收藏",
)
async def unfavorite_material(
    material_id: UUID,
    db: DbSession,
    user: CurrentUserDep,
    _csrf=CSRF,
    _perm=WRITE,
) -> None:
    material_service.unfavorite(db.connection(), material_id, user.id)
    db.commit()
