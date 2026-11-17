"""Material library endpoints (task 3.1 contracts).

Handlers are implemented in tasks 3.6-3.8; contracts are complete here.
Favorites are user-isolated; DELETE is a soft delete preserving references.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.api.responses import error_responses
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.schemas.materials import (
    BulkActionIn,
    BulkActionOut,
    FavoriteOut,
    MaterialCategoryIn,
    MaterialCategoryOut,
    MaterialCreateIn,
    MaterialDeleteOut,
    MaterialDetailOut,
    MaterialOut,
    MaterialRevisionOut,
    MaterialUpdateIn,
    TagIn,
    TagOut,
)

router = APIRouter(prefix="/materials", tags=["materials"])

WRITE = "material:write"
READ = "material:read"


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


# --- materials ---


@router.get(
    "",
    response_model=PaginatedResponse[MaterialOut],
    responses=error_responses(401, 403),
    summary="分页查询素材（状态/分类/标签/关键词/我的收藏筛选）",
)
async def list_materials(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    usage_status: str | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    tag_id: UUID | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=128),
    favorite_mine: bool = Query(default=False),
) -> PaginatedResponse[MaterialOut]:
    raise NotImplementedError



@router.post(
    "",
    response_model=MaterialOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 422),
    summary="手工创建素材（首修订，版本号 1）",
)
async def create_material(payload: MaterialCreateIn, db: DbSession) -> MaterialOut:
    raise NotImplementedError



@router.get(
    "/favorites",
    response_model=PaginatedResponse[MaterialOut],
    responses=error_responses(401, 403),
    summary="我的收藏列表（按用户隔离）",
)
async def my_favorites(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedResponse[MaterialOut]:
    raise NotImplementedError



@router.post(
    "/bulk",
    response_model=BulkActionOut,
    responses=error_responses(401, 403, 422),
    summary="批量操作（归档/取消归档/标记使用/设置分类/增删标签，返回逐项结果）",
)
async def bulk_action(payload: BulkActionIn, db: DbSession) -> BulkActionOut:
    raise NotImplementedError


# --- categories ---


@router.get(
    "/categories",
    response_model=list[MaterialCategoryOut],
    responses=error_responses(401, 403),
    summary="分类树（层级）",
)
async def list_categories(db: DbSession) -> list[MaterialCategoryOut]:
    raise NotImplementedError



@router.post(
    "/categories",
    response_model=MaterialCategoryOut,
    status_code=201,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="创建分类（parent_id 不得形成循环）",
)
async def create_category(payload: MaterialCategoryIn, db: DbSession) -> MaterialCategoryOut:
    raise NotImplementedError



@router.get("/tags", response_model=list[TagOut],
            responses=error_responses(401, 403), summary="全部标签")
async def list_tags(db: DbSession) -> list[TagOut]:
    raise NotImplementedError



@router.post("/tags", response_model=TagOut, status_code=201,
             responses=error_responses(400, 401, 403, 409, 422),
             summary="创建标签（同名 409）")
async def create_tag(payload: TagIn, db: DbSession) -> TagOut:
    raise NotImplementedError



@router.patch("/tags/{tag_id}", response_model=TagOut,
              responses=error_responses(401, 403, 404, 409, 422),
              summary="重命名标签（素材关联保留）")
async def update_tag(tag_id: UUID, payload: TagIn, db: DbSession) -> TagOut:
    raise NotImplementedError



@router.delete("/tags/{tag_id}", responses=error_responses(401, 403, 404),
               summary="删除标签（关联解除，素材保留）")
async def delete_tag(tag_id: UUID, db: DbSession) -> None:
    raise NotImplementedError


@router.get(
    "/{material_id}",
    response_model=MaterialDetailOut,
    responses=error_responses(401, 403, 404),
    summary="素材详情（当前修订正文 + 收藏状态）",
)
async def get_material(material_id: UUID, db: DbSession) -> MaterialDetailOut:
    raise NotImplementedError



@router.patch(
    "/{material_id}",
    response_model=MaterialDetailOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新素材：正文/标题变更创建新修订；状态/分类/标签原地变更",
)
async def update_material(material_id: UUID, payload: MaterialUpdateIn, db: DbSession) -> MaterialDetailOut:
    raise NotImplementedError



DELETE_EXAMPLE = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "usage_status": "archived",
    "deleted_at": "2026-11-17T09:00:00Z",
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
async def delete_material(material_id: UUID, db: DbSession) -> MaterialDeleteOut:
    raise NotImplementedError



@router.get(
    "/{material_id}/revisions",
    response_model=list[MaterialRevisionOut],
    responses=error_responses(401, 403, 404),
    summary="素材全部修订（revision_no 唯一递增）",
)
async def list_revisions(material_id: UUID, db: DbSession) -> list[MaterialRevisionOut]:
    raise NotImplementedError



@router.get(
    "/{material_id}/relations",
    response_model=list[dict],
    responses=error_responses(401, 403, 404),
    summary="素材来源关联（采集结果/上传/链接等）",
)
async def list_relations(material_id: UUID, db: DbSession) -> list[dict]:
    raise NotImplementedError



@router.get(
    "/{material_id}/articles",
    response_model=list[dict],
    responses=error_responses(401, 403, 404),
    summary="引用该素材的文章版本（含当时使用的修订）",
)
async def list_articles(material_id: UUID, db: DbSession) -> list[dict]:
    raise NotImplementedError


# --- favorites (user-isolated) ---


@router.put(
    "/{material_id}/favorite",
    response_model=FavoriteOut,
    status_code=201,
    responses=error_responses(401, 403, 404, 409),
    summary="收藏素材（同用户重复收藏幂等返回原记录）",
)
async def favorite_material(material_id: UUID, db: DbSession) -> FavoriteOut:
    raise NotImplementedError



@router.delete(
    "/{material_id}/favorite",
    responses={**error_responses(401, 404), 204: {"description": "已取消收藏（他人收藏不受影响）"}},
    summary="取消收藏",
)
async def unfavorite_material(material_id: UUID, db: DbSession) -> None:
    raise NotImplementedError


# --- bulk actions ---


@router.patch(
    "/categories/{category_id}",
    response_model=MaterialCategoryOut,
    responses=error_responses(400, 401, 403, 404, 409, 422),
    summary="更新分类（改名/移动父级；循环引用返回 409）",
)
async def update_category(category_id: UUID, payload: MaterialCategoryIn, db: DbSession) -> MaterialCategoryOut:
    raise NotImplementedError



@router.delete(
    "/categories/{category_id}",
    responses={
        **error_responses(401, 403, 404, 409),
        409: {
            "model": ErrorEnvelope,
            "description": "分类下仍有素材或子分类时的删除策略冲突",
            "content": {
                "application/json": {
                    "example": {"error": {"code": "category_not_empty", "message": "分类下仍有素材或子分类"}}
                }
            },
        },
        200: _not_ready("删除分类：素材置为未分类，引用不受影响"),
    },
    summary="删除分类",
)
async def delete_category(category_id: UUID, db: DbSession) -> ErrorEnvelope:
    raise NotImplementedError


# --- tags ---
