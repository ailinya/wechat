"""Direct accounts: short database transactions around external checks."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.adapters.wechat_client import WechatClient, WechatError, encrypt
from app.errors import ApiError
from app.services import async_job_service, outbox_service
from app.services.audit_service import record_operation


def account(conn, account_id, *, lock=False):
    row = conn.execute(text('SELECT * FROM wechat_accounts WHERE id=:id' + (' FOR UPDATE' if lock else '')), {'id': str(account_id)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '公众号不存在')
    return dict(row)


def require_available(row, capability=None):
    if row['status'] != 'active':
        raise ApiError(409, 'account_unavailable', '公众号已解绑或连接异常')
    if capability and not row['capabilities'].get(capability, {}).get('available'):
        raise ApiError(409, 'account_permission_missing', row['capabilities'].get(capability, {}).get('reason', '账号接口权限未验证'))


def check(db, settings, account_id, user_id, new_secret=None, client_factory=WechatClient):
    row = account(db.connection(), account_id)
    if row['status'] == 'unbound' and new_secret is None:
        raise ApiError(409, 'account_unbound', '请重新录入凭据接入已解绑账号')
    expected_version = row['credential_version']
    expected_status = row['status']
    if new_secret:
        row['secret_encrypted'] = encrypt(settings, new_secret)
    row['token_encrypted'] = None  # A connection check verifies the credential, not just its cached token.
    db.commit()
    client = client_factory(row, settings)
    error = None
    try:
        capabilities = client.capabilities()
    except WechatError as exc:
        error, capabilities = exc, {}
    current = account(db.connection(), account_id, lock=True)
    if current['credential_version'] != expected_version or current['status'] != expected_status:
        raise ApiError(409, 'account_changed', '账号已变更，请重新检测')
    params = {'id': str(account_id), 'caps': json.dumps(capabilities, ensure_ascii=False), 'status': 'invalid' if error else 'active', 'error': error.code if error else None,
              'secret': row['secret_encrypted'], 'version': expected_version + (1 if new_secret else 0),
              'token': encrypt(settings, client._token) if client._token and not error else None,
              'expires': client.token_expires_at if client._token and not error else None}
    # A failed replacement does not discard the existing working credential.
    if new_secret and error:
        record_operation(db.connection(), user_id=user_id, action='account.reconnect', object_type='wechat_account', object_id=account_id, result='denied', detail={'reason': error.code})
        db.commit()
        raise ApiError(503, error.code, error.message)
    db.connection().execute(text('UPDATE wechat_accounts SET status=:status,capabilities=CAST(:caps AS jsonb),error_code=:error,checked_at=now(),secret_encrypted=:secret,credential_version=:version,token_encrypted=:token,token_expires_at=:expires,updated_at=now() WHERE id=:id'), params)
    record_operation(db.connection(), user_id=user_id, action='account.check', object_type='wechat_account', object_id=account_id, result='denied' if error else 'success', detail={'error_code': params['error']})
    result = account(db.connection(), account_id)
    db.commit()
    return result


def create(db, settings, payload, user_id, client_factory=WechatClient):
    row = {'app_id': payload.app_id, 'secret_encrypted': encrypt(settings, payload.app_secret.get_secret_value()), 'publish_permission_confirmed': payload.publish_permission_confirmed}
    db.commit()
    client = client_factory(row, settings)
    try:
        caps = client.capabilities()
    except WechatError as exc:
        raise ApiError(503, exc.code, exc.message) from None
    conn = db.connection()
    conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:appid))'), {'appid': payload.app_id})
    if conn.execute(text('SELECT 1 FROM wechat_accounts WHERE app_id=:appid'), {'appid': payload.app_id}).scalar():
        raise ApiError(409, 'account_exists', '该 AppID 已绑定，请在原账号重新接入')
    account_id = conn.execute(text('INSERT INTO wechat_accounts(name,app_id,account_type,secret_encrypted,token_encrypted,token_expires_at,status,publish_permission_confirmed,publish_defaults,capabilities,checked_at,created_by) VALUES (:name,:appid,:type,:secret,:token,:expires,\'active\',:confirmed,CAST(:defaults AS jsonb),CAST(:caps AS jsonb),now(),:user) RETURNING id'),
        {'name': payload.name, 'appid': payload.app_id, 'type': payload.account_type, 'secret': row['secret_encrypted'], 'token': encrypt(settings, client._token), 'expires': client.token_expires_at, 'confirmed': payload.publish_permission_confirmed, 'defaults': json.dumps(payload.publish_defaults.model_dump()), 'caps': json.dumps(caps, ensure_ascii=False), 'user': user_id}).scalar_one()
    record_operation(conn, user_id=user_id, action='account.bind', object_type='wechat_account', object_id=account_id, detail={'publish_permission_confirmed': payload.publish_permission_confirmed})
    result = account(conn, account_id)
    db.commit()
    return result


def set_default(conn, account_id, user_id):
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('wechat.default'))"))
    row = account(conn, account_id, lock=True)
    require_available(row)
    conn.execute(text('UPDATE wechat_accounts SET is_default=false WHERE is_default'))
    conn.execute(text('UPDATE wechat_accounts SET is_default=true WHERE id=:id'), {'id': str(account_id)})
    record_operation(conn, user_id=user_id, action='account.default', object_type='wechat_account', object_id=account_id)
    return account(conn, account_id)


def enqueue(conn, job_type, resource_type, resource_id, payload, user_id):
    job = async_job_service.create_job(conn, job_type, resource_type, resource_id, payload, user_id)
    outbox_service.publish_event(conn, job_type, resource_type, resource_id, {'task': 'app.modules.async_execution.tasks.run_async_job', 'kwargs': {'job_id': str(job['id'])}})
    return job['id']


def cache_token(conn, row, client, settings):
    if client._token and client.expires_in > 60:
        conn.execute(text('UPDATE wechat_accounts SET token_encrypted=:token,token_expires_at=:expires WHERE id=:id AND credential_version=:version'), {'id': row['id'], 'version': row['credential_version'], 'token': encrypt(settings, client._token), 'expires': client.token_expires_at})


def start_sync(conn, account_id, user_id):
    row = account(conn, account_id, lock=True)
    require_available(row, 'materials')
    active = conn.execute(text("SELECT * FROM account_sync_runs WHERE account_id=:id AND status IN ('pending','running') ORDER BY created_at DESC LIMIT 1"), {'id': str(account_id)}).mappings().first()
    if active:
        return {'resource_id': active['id'], 'async_job_id': active['async_job_id'], 'status': active['status']}
    rid = conn.execute(text('INSERT INTO account_sync_runs(account_id,created_by) VALUES (:account,:user) RETURNING id'), {'account': str(account_id), 'user': user_id}).scalar_one()
    jid = enqueue(conn, 'account.sync', 'account_sync_run', rid, {'sync_run_id': str(rid)}, user_id)
    conn.execute(text('UPDATE account_sync_runs SET async_job_id=:job WHERE id=:id'), {'job': jid, 'id': rid})
    record_operation(conn, user_id=user_id, action='account.sync', object_type='account_sync_run', object_id=rid)
    return {'resource_id': rid, 'async_job_id': jid, 'status': 'pending'}
