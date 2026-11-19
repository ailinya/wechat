"""Explicitly confirmed draft delivery and operator-sourced publication records."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import text

from app.api.deps import DbSession, get_settings, require_permission, verify_csrf
from app.api.responses import error_responses
from app.api.routes.wechat_accounts import idempotent, paginate
from app.config import Settings
from app.database import get_engine
from app.schemas.auth import PermissionCode
from app.schemas.common import PaginatedResponse
from app.schemas.wechat_drafts import DraftAttemptOut, DraftDeliveryIn, DraftDeliveryOut, DraftReconcileIn, ManualPublicationIn
from app.services import wechat_draft_service as service
from app.services.wechat_draft_worker import reconcile

router = APIRouter(prefix='/wechat-draft-deliveries', tags=['wechat drafts'])
READ = Depends(require_permission(PermissionCode.PUBLISH_READ))
CONFIRM = Depends(require_permission(PermissionCode.PUBLISH_CONFIRM))
CSRF = Depends(verify_csrf)
ERRORS = error_responses(401, 403, 404, 409, 422)


@router.get('', response_model=PaginatedResponse[DraftDeliveryOut], responses=ERRORS)
def list_deliveries(db: DbSession, article_id: UUID | None = None, account_id: UUID | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=READ):
    where, params = [], {}
    for name, value in [('article_id', article_id), ('account_id', account_id)]:
        if value:
            where.append(f'{name}=:{name}')
            params[name] = str(value)
    sql = 'SELECT *,id AS resource_id FROM wechat_draft_deliveries' + (' WHERE ' + ' AND '.join(where) if where else '')
    return paginate(db.connection(), sql, params, page, page_size)


@router.post('', response_model=DraftDeliveryOut, status_code=202, responses=ERRORS)
def create_delivery(payload: DraftDeliveryIn, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=CONFIRM, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'wechat_draft.create', user.id, payload.model_dump(mode='json'), lambda: service.create_delivery(db.connection(), payload, user.id), DraftDeliveryOut)
    db.commit()
    return result


@router.get('/{delivery_id}', response_model=DraftDeliveryOut, responses=ERRORS)
def detail(delivery_id: UUID, db: DbSession, user=READ):
    return service.get_delivery(db.connection(), delivery_id)


@router.get('/{delivery_id}/attempts', response_model=list[DraftAttemptOut], responses=ERRORS)
def attempts(delivery_id: UUID, db: DbSession, user=READ):
    service.get_delivery(db.connection(), delivery_id)
    return [dict(row) for row in db.connection().execute(text('SELECT * FROM wechat_draft_attempts WHERE delivery_id=:id ORDER BY attempt_no'), {'id': str(delivery_id)}).mappings()]


@router.post('/{delivery_id}/retry', response_model=DraftDeliveryOut, status_code=202, responses=ERRORS)
def retry(delivery_id: UUID, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=CONFIRM, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'wechat_draft.retry', user.id, {'delivery_id': str(delivery_id)}, lambda: service.retry(db.connection(), delivery_id, user.id), DraftDeliveryOut)
    db.commit()
    return result


@router.post('/{delivery_id}/cancel', response_model=DraftDeliveryOut, responses=ERRORS)
def cancel(delivery_id: UUID, db: DbSession, user=CONFIRM, _csrf=CSRF):
    result = service.cancel(db.connection(), delivery_id, user.id)
    db.commit()
    return result


@router.post('/{delivery_id}/reconcile', response_model=DraftDeliveryOut, responses={**ERRORS, **error_responses(503)})
def reconcile_delivery(delivery_id: UUID, payload: DraftReconcileIn, db: DbSession, settings: Settings = Depends(get_settings), user=CONFIRM, _csrf=CSRF):
    db.commit()
    return reconcile(get_engine(settings), settings, delivery_id, payload, user.id)


@router.post('/{delivery_id}/manual-published', response_model=DraftDeliveryOut, responses=ERRORS)
def manual_published(delivery_id: UUID, payload: ManualPublicationIn, db: DbSession, user=CONFIRM, _csrf=CSRF):
    result = service.mark_manual_publication(db.connection(), delivery_id, payload, user.id)
    db.commit()
    return result
