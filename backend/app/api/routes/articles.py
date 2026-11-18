"""Article detail and phase 6 editing/review interface contracts."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.deps import DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.errors import ApiError
from app.schemas.articles import (AiEditIn, AiSuggestionOut, ArticleCreateIn, ArticleDetailOut,
    ArticleOrigin, ArticleRevisionCreateIn, ArticleRevisionOut, ArticleSaveOut, ArticleStatus,
    ArticleSummaryOut, ReviewCreateIn, ReviewOut, ReviewQueueItem, SubmitReviewIn, SubmitReviewOut)
from app.schemas.auth import PermissionCode
from app.schemas.common import ErrorEnvelope, PaginatedResponse

router = APIRouter(prefix="/articles", tags=["articles"])
review_router = APIRouter(tags=["article reviews"])
READ = Depends(require_permission(PermissionCode.ARTICLE_READ))
WRITE = Depends(require_permission(PermissionCode.ARTICLE_WRITE))
REVIEW = Depends(require_permission(PermissionCode.ARTICLE_REVIEW))
CSRF = Depends(verify_csrf)

NOT_IMPLEMENTED = {501: {'model': ErrorEnvelope, 'description': '契约已定义，业务实现将在阶段 6 后续任务完成'}}
VERSION_CONFLICT = {
    'model': ErrorEnvelope,
    'description': '基准修订不是当前修订，或审核状态不允许该操作',
    'content': {'application/json': {'examples': {
        'revision_conflict': {'summary': '基准版本已过期', 'value': {'error': {'code': 'revision_conflict', 'message': '文章已被修改，请读取最新版本后重试', 'field_errors': [{'field': 'base_revision_id', 'message': '不是当前修订'}]}}},
        'invalid_article_state': {'summary': '当前状态不允许操作', 'value': {'error': {'code': 'invalid_article_state', 'message': '文章当前状态不允许此操作'}}},
    }}},
}


def _not_implemented():
    raise ApiError(501, 'not_implemented', '该接口的实现将在阶段 6 后续任务完成')


@router.get('', response_model=PaginatedResponse[ArticleSummaryOut], responses={**error_responses(401, 403, 422), **NOT_IMPLEMENTED}, summary='文章列表（article:read；待实现）')
def list_articles(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: ArticleStatus | None = None, origin_type: ArticleOrigin | None = None, created_from: datetime | None = None, created_to: datetime | None = None, _perm=READ):
    """按创建时间倒序、ID 倒序稳定分页；公众号及发布时间筛选在阶段 7 接入。"""
    _not_implemented()


@router.post('', response_model=ArticleSaveOut, status_code=201, responses={**error_responses(401, 403, 422), **NOT_IMPLEMENTED}, summary='创建人工草稿（article:write；待实现）')
def create_article(payload: ArticleCreateIn, _perm=WRITE, _csrf=CSRF):
    _not_implemented()


@router.get("/{article_id}", response_model=ArticleDetailOut, responses=error_responses(401, 403, 404), summary='读取文章当前版本（article:read）')
def article_detail(article_id: UUID, db: DbSession, _perm=READ):
    conn = db.connection()
    row = conn.execute(text("SELECT a.id,a.status,a.origin_type,a.creation_task_id,a.created_at,r.id AS revision_id,r.version,r.title,r.summary,r.body_markdown,r.keywords FROM articles a JOIN article_revisions r ON r.id=a.current_revision_id WHERE a.id=:id"), {"id": str(article_id)}).mappings().first()
    if not row:
        raise ApiError(404, "not_found", "文章不存在")
    result = dict(row)
    result["materials"] = [dict(item) for item in conn.execute(text(
        "SELECT am.material_id,am.material_revision_id,m.title,r.content_markdown,COALESCE(src.url,CASE WHEN m.origin='link' THEN m.summary END) AS source_url "
        "FROM article_materials am JOIN materials m ON m.id=am.material_id "
        "JOIN material_revisions r ON r.id=am.material_revision_id "
        "LEFT JOIN LATERAL (SELECT cr.url FROM collection_results cr WHERE cr.id=r.created_from_result_id "
        "OR cr.material_id=m.id ORDER BY (cr.id=r.created_from_result_id) DESC NULLS LAST,cr.collected_at,cr.id LIMIT 1) src ON true "
        "WHERE am.article_revision_id=:revision ORDER BY am.reference_order"
    ), {"revision": row["revision_id"]}).mappings().all()]
    return result


@router.get('/{article_id}/revisions', response_model=PaginatedResponse[ArticleRevisionOut], responses={**error_responses(401, 403, 404, 422), **NOT_IMPLEMENTED}, summary='文章修订历史（article:read；待实现）')
def list_revisions(article_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _perm=READ):
    """按版本号倒序分页；包含各修订独立保存的素材引用。"""
    _not_implemented()


@router.get('/{article_id}/revisions/{revision_id}', response_model=ArticleRevisionOut, responses={**error_responses(401, 403, 404), **NOT_IMPLEMENTED}, summary='文章历史修订详情（article:read；待实现）')
def get_revision(article_id: UUID, revision_id: UUID, _perm=READ):
    _not_implemented()


@router.post('/{article_id}/revisions', status_code=201, response_model=ArticleSaveOut, responses={**error_responses(401, 403, 404, 422), 409: VERSION_CONFLICT, **NOT_IMPLEMENTED}, summary='保存新修订（article:write；待实现）')
def create_revision(article_id: UUID, payload: ArticleRevisionCreateIn, db: DbSession, _perm=WRITE, _csrf=CSRF):
    """基准不匹配返回 409；原子保存正文和引用，新修订为 draft 且需重新提审。"""
    current = db.connection().execute(text('SELECT current_revision_id FROM articles WHERE id=:id'), {'id': str(article_id)}).first()
    if current is None:
        raise ApiError(404, 'not_found', '文章不存在')
    if current.current_revision_id != payload.base_revision_id:
        raise ApiError(409, 'revision_conflict', '文章已被修改，请读取最新版本后重试', [{'field': 'base_revision_id', 'message': '不是当前修订'}])
    _not_implemented()


@router.post('/{article_id}/ai-actions', response_model=AiSuggestionOut, responses={**error_responses(401, 403, 404, 422, 503), 409: VERSION_CONFLICT, **NOT_IMPLEMENTED}, summary='生成 AI 编辑建议（article:write；待实现）')
def ai_action(article_id: UUID, payload: AiEditIn, _perm=WRITE, _csrf=CSRF):
    """只返回基于指定修订的建议，不保存或审核文章。"""
    _not_implemented()


@router.post('/{article_id}/submit-review', response_model=SubmitReviewOut, responses={**error_responses(401, 403, 404, 422), 409: VERSION_CONFLICT, **NOT_IMPLEMENTED}, summary='提交当前修订审核（article:write；待实现）')
def submit_review(article_id: UUID, payload: SubmitReviewIn, _perm=WRITE, _csrf=CSRF):
    _not_implemented()


@review_router.get('/reviews/queue', response_model=PaginatedResponse[ReviewQueueItem], responses={**error_responses(401, 403, 422), **NOT_IMPLEMENTED}, summary='待审核队列（article:review；待实现）')
def review_queue(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _perm=REVIEW):
    """按提审时间升序及文章 ID 升序稳定分页。"""
    _not_implemented()


@review_router.get('/article-revisions/{revision_id}/reviews', response_model=PaginatedResponse[ReviewOut], responses={**error_responses(401, 403, 404, 422), **NOT_IMPLEMENTED}, summary='修订审核历史（article:read；待实现）')
def list_reviews(revision_id: UUID, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _perm=READ):
    _not_implemented()


@review_router.post('/article-revisions/{revision_id}/reviews', response_model=ReviewOut, status_code=201, responses={**error_responses(401, 403, 404, 422), 409: VERSION_CONFLICT, **NOT_IMPLEMENTED}, summary='审核当前待审修订（article:review；待实现）')
def create_review(revision_id: UUID, payload: ReviewCreateIn, _perm=REVIEW, _csrf=CSRF):
    """审核绑定明确修订；旧修订或非待审状态返回 409。"""
    _not_implemented()
