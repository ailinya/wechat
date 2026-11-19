"""Publication orders: creating is separate from operational confirmation."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text

from app.api.deps import DbSession, get_settings, require_permission, verify_csrf
from app.api.responses import error_responses
from app.api.routes.wechat_accounts import idempotent, paginate
from app.config import Settings
from app.database import get_engine
from app.schemas.auth import PermissionCode
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.schemas.wechat import PublishAttemptOut, PublishOrderIn, PublishOrderOut, ReconcileIn
from app.services import publishing_service as service
from app.services.publishing_worker import reconcile

router = APIRouter(prefix='/publish-orders', tags=['publishing'])
READ = Depends(require_permission(PermissionCode.PUBLISH_READ))
CONFIRM = Depends(require_permission(PermissionCode.PUBLISH_CONFIRM))
EXECUTE = Depends(require_permission(PermissionCode.PUBLISH_EXECUTE))
CSRF = Depends(verify_csrf)
CONFLICT = {'model': ErrorEnvelope, 'description': '当前版本未批准、账号受限、发布状态冲突或幂等键内容冲突', 'content': {'application/json': {'examples': {
    'unapproved': {'value': {'error': {'code': 'article_not_approved', 'message': '当前版本尚未人工批准'}}},
    'unknown': {'value': {'error': {'code': 'publish_retry_blocked', 'message': '未知结果须先核对'}}},
    'version': {'value': {'error': {'code': 'revision_conflict', 'message': '文章已被修改'}}},
    'idempotency': {'value': {'error': {'code': 'idempotency_conflict', 'message': '幂等键已用于不同请求'}}},
}}}}


@router.get('', response_model=PaginatedResponse[PublishOrderOut], responses=error_responses(401, 403, 422))
def list_orders(db: DbSession, article_id: UUID | None = None, account_id: UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=READ):
    where, params = [], {}
    if article_id:
        where.append('article_id=:article'); params['article'] = str(article_id)
    if account_id:
        where.append('account_id=:account'); params['account'] = str(account_id)
    sql = 'SELECT *,id AS resource_id FROM publish_orders' + (' WHERE ' + ' AND '.join(where) if where else '')
    return paginate(db.connection(), sql, params, page, page_size)


@router.post('', response_model=PublishOrderOut, status_code=201, responses={**error_responses(401, 403, 404, 422), 409: CONFLICT})
def create_order(payload: PublishOrderIn, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=CONFIRM, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'publish.create', user.id, payload.model_dump(mode='json'), lambda: service.create_order(db.connection(), payload, user.id), PublishOrderOut, 201)
    db.commit()
    return result


@router.get('/{order_id}', response_model=PublishOrderOut, responses=error_responses(401, 403, 404))
def get_order(order_id: UUID, db: DbSession, user=READ):
    return service.get_order(db.connection(), order_id)


@router.post('/{order_id}/confirm', response_model=PublishOrderOut, status_code=202, responses={**error_responses(401, 403, 404, 422), 409: CONFLICT})
def confirm_order(order_id: UUID, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=CONFIRM, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'publish.confirm', user.id, {'order_id': str(order_id)}, lambda: service.confirm(db.connection(), order_id, user.id), PublishOrderOut, 202)
    db.commit()
    return result


@router.post('/{order_id}/cancel', response_model=PublishOrderOut, responses={**error_responses(401, 403, 404), 409: CONFLICT})
def cancel_order(order_id: UUID, db: DbSession, user=CONFIRM, _csrf=CSRF):
    result = service.cancel(db.connection(), order_id, user.id)
    db.commit()
    return result


@router.post('/{order_id}/retry', response_model=PublishOrderOut, status_code=202, responses={**error_responses(401, 403, 404, 422), 409: CONFLICT})
def retry_order(order_id: UUID, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=EXECUTE, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'publish.retry', user.id, {'order_id': str(order_id)}, lambda: service.retry(db.connection(), order_id, user.id), PublishOrderOut, 202)
    db.commit()
    return result


@router.get('/{order_id}/attempts', response_model=list[PublishAttemptOut], responses=error_responses(401, 403, 404))
def attempts(order_id: UUID, db: DbSession, user=READ):
    service.get_order(db.connection(), order_id)
    return [dict(row) for row in db.connection().execute(text('SELECT * FROM publish_attempts WHERE order_id=:id ORDER BY attempt_no'), {'id': str(order_id)}).mappings()]


@router.post('/{order_id}/reconcile', response_model=PublishOrderOut, responses={**error_responses(401, 403, 404, 422, 503), 409: CONFLICT})
def reconcile_order(order_id: UUID, payload: ReconcileIn, db: DbSession, settings: Settings = Depends(get_settings), user=EXECUTE, _csrf=CSRF):
    db.commit()  # Release authentication transaction before external result query.
    return reconcile(get_engine(settings), settings, order_id, payload, user.id)
