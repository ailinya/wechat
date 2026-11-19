"""Direct-account CRUD, external checks and durable sync acceptance."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from sqlalchemy import text

from app.api.deps import DbSession, get_settings, require_permission, verify_csrf
from app.api.responses import error_responses
from app.config import Settings
from app.errors import ApiError
from app.schemas.auth import PermissionCode
from app.schemas.common import ErrorEnvelope, PaginatedResponse
from app.schemas.wechat import AccountIn, AccountOut, AccountPatch, Accepted, CredentialIn, SyncOut
from app.services import wechat_account_service as service
from app.services.audit_service import record_operation

router = APIRouter(prefix='/wechat-accounts', tags=['wechat accounts'])
READ = Depends(require_permission(PermissionCode.ACCOUNT_READ))
WRITE = Depends(require_permission(PermissionCode.ACCOUNT_WRITE))
CSRF = Depends(verify_csrf)


def paginate(conn, sql, params, page, size):
    total = conn.execute(text('SELECT count(*) FROM (' + sql + ') rows'), params).scalar_one()
    rows = conn.execute(text(sql + ' ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset'), {**params, 'limit': size, 'offset': (page-1)*size}).mappings().all()
    return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'page_size': size}


def idempotent(conn, key, scope, user, content, operation, response_model, status=202):
    from app.services import idempotency_service as idem
    row = None
    if key:
        try:
            row = idem.begin_request(conn, scope, user, key, idem.request_fingerprint(content))
        except idem.IdempotencyReplay as replay:
            return response_model.model_validate(replay.row['response_body'])
        except idem.IdempotencyConflict:
            raise ApiError(409, 'idempotency_conflict', '幂等键已用于不同请求') from None
    result = response_model.model_validate(operation())
    if row:
        idem.store_response(conn, row['id'], status, result.model_dump(mode='json'))
    return result


@router.get('', response_model=PaginatedResponse[AccountOut], responses=error_responses(401, 403, 422))
def list_accounts(db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), _user=READ):
    return paginate(db.connection(), 'SELECT * FROM wechat_accounts', {}, page, page_size)


@router.post('', response_model=AccountOut, status_code=201, responses=error_responses(401, 403, 409, 422, 503))
def bind_account(payload: AccountIn, db: DbSession, settings: Settings = Depends(get_settings), user=WRITE, _csrf=CSRF):
    return service.create(db, settings, payload, user.id)


@router.get('/authorization', responses={410: {'model': ErrorEnvelope, 'description': '直连不使用 OAuth'}})
@router.post('/authorization', responses={410: {'model': ErrorEnvelope, 'description': '直连不使用 OAuth'}})
@router.get('/callback', responses={410: {'model': ErrorEnvelope, 'description': '直连不使用 OAuth'}})
@router.post('/callback', responses={410: {'model': ErrorEnvelope, 'description': '直连不使用 OAuth'}})
def unsupported_oauth():
    raise ApiError(410, 'direct_mode_no_oauth', '自有公众号直连不使用 OAuth 回调')


@router.get('/{account_id}', response_model=AccountOut, responses=error_responses(401, 403, 404))
def get_account(account_id: UUID, db: DbSession, user=READ):
    return service.account(db.connection(), account_id)


@router.post('/{account_id}/check', response_model=AccountOut, responses=error_responses(401, 403, 404, 409, 503))
def check_account(account_id: UUID, db: DbSession, settings: Settings = Depends(get_settings), user=WRITE, _csrf=CSRF):
    return service.check(db, settings, account_id, user.id)


@router.put('/{account_id}/credentials', response_model=AccountOut, responses=error_responses(401, 403, 404, 409, 422, 503))
def reconnect(account_id: UUID, payload: CredentialIn, db: DbSession, settings: Settings = Depends(get_settings), user=WRITE, _csrf=CSRF):
    return service.check(db, settings, account_id, user.id, payload.app_secret.get_secret_value())


@router.patch('/{account_id}', response_model=AccountOut, responses=error_responses(401, 403, 404, 409, 422))
def update_account(account_id: UUID, payload: AccountPatch, db: DbSession, user=WRITE, _csrf=CSRF):
    conn = db.connection()
    row = service.account(conn, account_id, lock=True)
    service.require_available(row)
    values = payload.model_dump(exclude_none=True)
    if 'name' in values:
        conn.execute(text('UPDATE wechat_accounts SET name=:value WHERE id=:id'), {'value': values['name'], 'id': str(account_id)})
    if 'publish_defaults' in values:
        conn.execute(text('UPDATE wechat_accounts SET publish_defaults=CAST(:value AS jsonb) WHERE id=:id'), {'value': json.dumps(values['publish_defaults']), 'id': str(account_id)})
    if 'publish_permission_confirmed' in values:
        caps = row['capabilities']
        enabled = values['publish_permission_confirmed'] and caps.get('drafts', {}).get('available') and caps.get('published_read', {}).get('available')
        caps['publish'] = {'available': bool(enabled), 'reason': '运营确认且只读探测通过；微信执行时仍复验权限' if enabled else '未确认发布权限或只读探测不通过'}
        conn.execute(text('UPDATE wechat_accounts SET publish_permission_confirmed=:confirmed,capabilities=CAST(:caps AS jsonb) WHERE id=:id'), {'confirmed': values['publish_permission_confirmed'], 'caps': json.dumps(caps, ensure_ascii=False), 'id': str(account_id)})
    conn.execute(text('UPDATE wechat_accounts SET credential_version=credential_version+1,updated_at=now() WHERE id=:id'), {'id': str(account_id)})
    record_operation(conn, user_id=user.id, action='account.update', object_type='wechat_account', object_id=account_id, detail=values)
    result = service.account(conn, account_id)
    db.commit()
    return result


@router.put('/{account_id}/default', response_model=AccountOut, responses=error_responses(401, 403, 404, 409))
def default_account(account_id: UUID, db: DbSession, user=WRITE, _csrf=CSRF):
    result = service.set_default(db.connection(), account_id, user.id)
    db.commit()
    return result


@router.delete('/{account_id}', status_code=204, responses=error_responses(401, 403, 404))
def unbind_account(account_id: UUID, db: DbSession, user=WRITE, _csrf=CSRF):
    conn = db.connection()
    service.account(conn, account_id, lock=True)
    conn.execute(text("UPDATE wechat_accounts SET status='unbound',is_default=false,capabilities='{}',token_encrypted=NULL,token_expires_at=NULL,credential_version=credential_version+1,updated_at=now() WHERE id=:id"), {'id': str(account_id)})
    record_operation(conn, user_id=user.id, action='account.unbind', object_type='wechat_account', object_id=account_id)
    db.commit()
    return Response(status_code=204)


@router.post('/{account_id}/sync', response_model=Accepted, status_code=202, responses=error_responses(401, 403, 404, 409))
def sync_account(account_id: UUID, db: DbSession, key: str | None = Header(None, alias='Idempotency-Key', min_length=1, max_length=128), user=WRITE, _csrf=CSRF):
    result = idempotent(db.connection(), key, 'account.sync', user.id, {'account_id': str(account_id)}, lambda: service.start_sync(db.connection(), account_id, user.id), Accepted)
    db.commit()
    return result


@router.get('/{account_id}/sync-runs', response_model=PaginatedResponse[SyncOut], responses=error_responses(401, 403, 404, 422))
def sync_runs(account_id: UUID, db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=READ):
    service.account(db.connection(), account_id)
    return paginate(db.connection(), 'SELECT * FROM account_sync_runs WHERE account_id=:id', {'id': str(account_id)}, page, page_size)
