"""Evidence-backed assistance without review or publication side effects."""
from uuid import UUID
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.deps import CurrentUserDep, DbSession, require_permission, verify_csrf
from app.api.responses import error_responses
from app.errors import ApiError
from app.schemas.assistance import EnhancedSearchRequest, QualityRequest, TopicRequest
from app.schemas.auth import PermissionCode
from app.services import assistance_service
from app.services import assistance_analytics_service

router = APIRouter(prefix='/assistance', tags=['intelligence assistance'])
CSRF = Depends(verify_csrf)
ERRORS = error_responses(401, 403, 404, 409, 422, 503)


@router.get('/models', response_model=list[dict[str, str]], responses=ERRORS)
def analysis_models(db: DbSession,
                    _article=Depends(require_permission(PermissionCode.ARTICLE_READ)),
                    _material=Depends(require_permission(PermissionCode.MATERIAL_READ))):
    return [dict(row) for row in db.connection().execute(text("SELECT id::text,name,model_name FROM model_configs WHERE enabled AND purpose='analysis' ORDER BY name,id")).mappings()]


@router.post('/topics', response_model=dict, responses=ERRORS)
def topics(payload: TopicRequest, db: DbSession,
           user=Depends(require_permission(PermissionCode.CREATION_WRITE)),
           _materials=Depends(require_permission(PermissionCode.MATERIAL_READ)),
           _articles=Depends(require_permission(PermissionCode.ARTICLE_READ)), _csrf=CSRF):
    engine = db.get_bind()
    db.commit()
    return assistance_service.recommend_topics(engine, user.id, payload.material_ids, payload.model_config_id)


@router.get('/runs/{run_id}', response_model=dict, responses=ERRORS)
def run(run_id: UUID, db: DbSession, user: CurrentUserDep):
    row = assistance_service.run_detail(db.connection(), run_id, user.id)
    required = {'topic': {'creation:write', 'material:read', 'article:read'},
                'relation': {'material:read', 'material:search'},
                'search': {'material:read', 'material:search'},
                'quality': {'article:read', 'material:read'}}[row['kind']]
    if not required.issubset(user.permissions):
        raise ApiError(403, 'forbidden', '缺少查看此增强结果所需权限')
    return row


@router.post('/materials/{material_id}/relations', response_model=dict, responses=ERRORS)
def generate_relations(material_id: UUID, db: DbSession,
                       user=Depends(require_permission(PermissionCode.MATERIAL_SEARCH)),
                       _read=Depends(require_permission(PermissionCode.MATERIAL_READ)), _csrf=CSRF):
    started = time.monotonic()
    source = db.connection().execute(text("SELECT title FROM materials WHERE id=:id AND deleted_at IS NULL AND usage_status<>'archived'"), {'id': str(material_id)}).scalar_one_or_none()
    if source is None:
        raise ApiError(404, 'not_found', '素材不可用')
    engine = db.get_bind()
    db.commit()
    embed, snapshot, usage = assistance_service.prepare_embedding(engine, source, 'hybrid')
    conn = db.connection()
    result = assistance_service.suggest_relations(conn, user.id, material_id, embed=embed, model_snapshot=snapshot, usage=usage)
    conn.execute(text('UPDATE assistance_runs SET elapsed_ms=:elapsed WHERE id=:id'), {'id': result['run_id'], 'elapsed': int((time.monotonic()-started)*1000)})
    db.commit()
    return result


@router.get('/materials/{material_id}/relations', response_model=list[dict], responses=ERRORS)
def relations(material_id: UUID, db: DbSession,
              _search=Depends(require_permission(PermissionCode.MATERIAL_SEARCH)),
              _read=Depends(require_permission(PermissionCode.MATERIAL_READ))):
    return assistance_service.list_relations(db.connection(), material_id)


@router.post('/relations/{suggestion_id}/ignore', response_model=dict, responses=ERRORS)
def ignore_relation(suggestion_id: UUID, db: DbSession,
                    user=Depends(require_permission(PermissionCode.MATERIAL_WRITE)),
                    _search=Depends(require_permission(PermissionCode.MATERIAL_SEARCH)),
                    _read=Depends(require_permission(PermissionCode.MATERIAL_READ)), _csrf=CSRF):
    result = assistance_service.ignore_relation(db.connection(), suggestion_id, user.id)
    db.commit()
    return result


@router.post('/search', response_model=dict, responses=ERRORS)
def search(payload: EnhancedSearchRequest, db: DbSession,
           user=Depends(require_permission(PermissionCode.MATERIAL_SEARCH)),
           _read=Depends(require_permission(PermissionCode.MATERIAL_READ)), _csrf=CSRF):
    started = time.monotonic()
    engine = db.get_bind()
    db.commit()
    embed, snapshot, usage = assistance_service.prepare_embedding(engine, payload.query, payload.keyword_mode)
    conn = db.connection()
    result = assistance_service.enhanced_search(conn, user.id, payload, embed=embed, model_snapshot=snapshot, usage=usage)
    conn.execute(text('UPDATE assistance_runs SET elapsed_ms=:elapsed WHERE id=:id'), {'id': result['run_id'], 'elapsed': int((time.monotonic()-started)*1000)})
    db.commit()
    return result


@router.post('/articles/{article_id}/quality', response_model=dict, responses=ERRORS)
def quality(article_id: UUID, payload: QualityRequest, db: DbSession,
            user=Depends(require_permission(PermissionCode.ARTICLE_READ)),
            _materials=Depends(require_permission(PermissionCode.MATERIAL_READ)), _csrf=CSRF):
    engine = db.get_bind()
    db.commit()
    return assistance_service.assess_quality(engine, user.id, article_id, payload.revision_id, payload.model_config_id)


@router.get('/analytics/reuse', response_model=dict, responses=ERRORS)
def reuse(db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          _analytics=Depends(require_permission(PermissionCode.ANALYTICS_READ)),
          _material=Depends(require_permission(PermissionCode.MATERIAL_READ)),
          _article=Depends(require_permission(PermissionCode.ARTICLE_READ)),
          _publish=Depends(require_permission(PermissionCode.PUBLISH_READ)),
          _account=Depends(require_permission(PermissionCode.ACCOUNT_READ))):
    db.commit()
    return assistance_analytics_service.reuse_report(db.connection(execution_options={'isolation_level': 'REPEATABLE READ'}), page, page_size)
