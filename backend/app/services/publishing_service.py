"""Version-bound orders, explicit confirmation and immutable attempt history."""
import json

from sqlalchemy import text

from app.errors import ApiError
from app.services.article_service import article, check_revision
from app.services.wechat_account_service import account, require_available, enqueue
from app.services.audit_service import record_operation


def get_order(conn, order_id):
    row = conn.execute(text('SELECT * FROM publish_orders WHERE id=:id'), {'id': str(order_id)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '发布单不存在')
    return {**dict(row), 'resource_id': row['id']}


def lock_order(conn, order_id):
    initial = get_order(conn, order_id)
    art = article(conn, initial['article_id'], lock=True)
    acct = account(conn, initial['account_id'], lock=True)
    row = dict(conn.execute(text('SELECT * FROM publish_orders WHERE id=:id FOR UPDATE'), {'id': str(order_id)}).mappings().one())
    return row, art, acct


def validate(conn, art, acct, revision_id, capability='publish'):
    check_revision(art, revision_id)
    if art['status'] not in ('approved', 'published'):
        raise ApiError(409, 'article_not_approved', '当前文章版本尚未人工审核通过')
    action = conn.execute(text('SELECT action FROM reviews WHERE article_revision_id=:id ORDER BY created_at DESC,id DESC LIMIT 1'), {'id': str(revision_id)}).scalar()
    if action != 'approve':
        raise ApiError(409, 'article_not_approved', '当前版本缺少有效人工批准')
    require_available(acct, capability)


def create_order(conn, payload, user_id):
    aid = conn.execute(text('SELECT article_id FROM article_revisions WHERE id=:id'), {'id': payload.article_revision_id}).scalar()
    if not aid:
        raise ApiError(404, 'not_found', '文章版本不存在')
    art = article(conn, aid, lock=True)
    acct = account(conn, payload.account_id, lock=True)
    validate(conn, art, acct, payload.article_revision_id)
    if conn.execute(text("SELECT 1 FROM publish_orders WHERE article_revision_id=:revision AND account_id=:account AND status NOT IN ('failed','cancelled')"), {'revision': payload.article_revision_id, 'account': payload.account_id}).scalar():
        raise ApiError(409, 'publish_order_exists', '该版本在此账号已有有效发布单')
    oid = conn.execute(text('INSERT INTO publish_orders(article_id,article_revision_id,account_id,mode,scheduled_at,publish_note,publish_defaults,created_by) VALUES (:article,:revision,:account,:mode,:scheduled,:note,CAST(:defaults AS jsonb),:user) RETURNING id'), {'article': aid, 'revision': payload.article_revision_id, 'account': payload.account_id, 'mode': payload.mode, 'scheduled': payload.scheduled_at, 'note': payload.publish_note, 'defaults': json.dumps(acct['publish_defaults']), 'user': user_id}).scalar_one()
    record_operation(conn, user_id=user_id, action='publish.create', object_type='publish_order', object_id=oid)
    return get_order(conn, oid)


def queue_order(conn, row, user_id):
    jid = enqueue(conn, 'publish.execute', 'publish_order', row['id'], {'order_id': str(row['id'])}, user_id)
    conn.execute(text('UPDATE publish_orders SET async_job_id=:job,updated_at=now() WHERE id=:id'), {'job': jid, 'id': row['id']})
    return jid


def confirm(conn, oid, user_id):
    row, art, acct = lock_order(conn, oid)
    if row['status'] != 'awaiting_confirmation':
        if row['confirmed_at'] and row['status'] != 'cancelled':
            return get_order(conn, oid)
        raise ApiError(409, 'invalid_publish_state', '发布单不可确认')
    validate(conn, art, acct, row['article_revision_id'])
    conn.execute(text("UPDATE publish_orders SET status='confirmed',confirmed_by=:user,confirmed_at=now(),updated_at=now() WHERE id=:id"), {'user': user_id, 'id': row['id']})
    if row['mode'] == 'immediate':
        queue_order(conn, row, user_id)
    record_operation(conn, user_id=user_id, action='publish.confirm', object_type='publish_order', object_id=oid)
    return get_order(conn, oid)


def cancel(conn, oid, user_id):
    row, _, _ = lock_order(conn, oid)
    if row['status'] not in ('awaiting_confirmation', 'confirmed'):
        raise ApiError(409, 'publish_not_cancellable', '发布已开始或已结束，不能按未执行订单取消')
    conn.execute(text("UPDATE publish_orders SET status='cancelled',updated_at=now() WHERE id=:id"), {'id': row['id']})
    if row['async_job_id']:
        conn.execute(text("UPDATE async_jobs SET status='cancelled',finished_at=now() WHERE id=:id AND status='pending'"), {'id': row['async_job_id']})
    record_operation(conn, user_id=user_id, action='publish.cancel', object_type='publish_order', object_id=oid)
    return get_order(conn, oid)


def retry(conn, oid, user_id):
    row, art, acct = lock_order(conn, oid)
    if row['status'] != 'failed' or not row['confirmed_at']:
        raise ApiError(409, 'publish_retry_blocked', '仅已确认失败的发布单可重试；未知结果须先核对')
    validate(conn, art, acct, row['article_revision_id'])
    other = conn.execute(text("SELECT 1 FROM publish_orders WHERE article_revision_id=:revision AND account_id=:account AND id<>:id AND status NOT IN ('failed','cancelled')"), {'revision': row['article_revision_id'], 'account': row['account_id'], 'id': row['id']}).scalar()
    if other:
        raise ApiError(409, 'publish_order_exists', '该账号已有其他有效发布单')
    conn.execute(text("UPDATE publish_orders SET status='confirmed',error_code=NULL,updated_at=now() WHERE id=:id"), {'id': row['id']})
    queue_order(conn, row, user_id)
    record_operation(conn, user_id=user_id, action='publish.retry', object_type='publish_order', object_id=oid)
    return get_order(conn, oid)


def finish(conn, oid, attempt_id, state, *, error=None, result=None, external_id=None, url=None):
    conn.execute(text('UPDATE publish_attempts SET status=:status,error_code=:error,result=CAST(:result AS jsonb),article_id_external=COALESCE(:external,article_id_external),article_url=COALESCE(:url,article_url),finished_at=CASE WHEN :terminal THEN now() ELSE finished_at END WHERE id=:id'), {'status': state, 'terminal': state in ('succeeded', 'failed'), 'error': error, 'result': json.dumps(result or {}), 'external': external_id, 'url': url, 'id': attempt_id})
    conn.execute(text('UPDATE publish_orders SET status=:status,error_code=:error,updated_at=now() WHERE id=:id'), {'status': state, 'error': error, 'id': oid})
    if state == 'succeeded':
        conn.execute(text("UPDATE articles SET status='published',updated_at=now() WHERE id=(SELECT article_id FROM publish_orders WHERE id=:id) AND current_revision_id=(SELECT article_revision_id FROM publish_orders WHERE id=:id)"), {'id': oid})


def apply_query(conn, oid, attempt, value):
    code = value.get('publish_status')
    if code == 1:
        finish(conn, oid, attempt['id'], 'publishing', result={'publish_status': 1})
    elif code in (0, 5, 6):
        details = value.get('article_detail') or {}
        items = details.get('item') or []
        url = items[0].get('article_url') if items else None
        finish(conn, oid, attempt['id'], 'succeeded', result={'publish_status': code}, external_id=value.get('article_id'), url=url)
    elif code in (2, 3, 4):
        finish(conn, oid, attempt['id'], 'failed', error=f'wechat_publish_{code}', result={'publish_status': code})
    else:
        raise ApiError(503, 'invalid_publish_status', '微信返回未知发布状态，保留待核对')
