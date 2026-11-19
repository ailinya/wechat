"""Approved draft deliveries, version binding and operator publication evidence."""
import json

from sqlalchemy import text

from app.errors import ApiError
from app.services.article_service import article
from app.services.publishing_service import validate
from app.services.wechat_account_service import account, enqueue
from app.services.audit_service import record_operation


def get_delivery(conn, delivery_id):
    row = conn.execute(text('SELECT *,id AS resource_id FROM wechat_draft_deliveries WHERE id=:id'), {'id': str(delivery_id)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '微信草稿交付不存在')
    return dict(row)


def lock_delivery(conn, delivery_id):
    initial = get_delivery(conn, delivery_id)
    art = article(conn, initial['article_id'], lock=True)
    acct = account(conn, initial['account_id'], lock=True)
    row = dict(conn.execute(text('SELECT * FROM wechat_draft_deliveries WHERE id=:id FOR UPDATE'), {'id': str(delivery_id)}).mappings().one())
    return row, art, acct


def queue(conn, row, user_id):
    job = enqueue(conn, 'wechat.draft', 'wechat_draft_delivery', row['id'], {'delivery_id': str(row['id'])}, user_id)
    conn.execute(text('UPDATE wechat_draft_deliveries SET async_job_id=:job,updated_at=now() WHERE id=:id'), {'job': job, 'id': row['id']})


def create_delivery(conn, payload, user_id):
    aid = conn.execute(text('SELECT article_id FROM article_revisions WHERE id=:id'), {'id': payload.article_revision_id}).scalar()
    if not aid:
        raise ApiError(404, 'not_found', '文章修订不存在')
    art = article(conn, aid, lock=True)
    acct = account(conn, payload.account_id, lock=True)
    validate(conn, art, acct, payload.article_revision_id, 'drafts')
    if conn.execute(text("SELECT 1 FROM wechat_draft_deliveries WHERE article_revision_id=:revision AND account_id=:account AND status NOT IN ('failed','cancelled')"), {'revision': payload.article_revision_id, 'account': payload.account_id}).scalar():
        raise ApiError(409, 'draft_delivery_exists', '该账号已有此版本的有效草稿交付，请查看原记录')
    did = conn.execute(text('INSERT INTO wechat_draft_deliveries(article_id,article_revision_id,account_id,publish_defaults,note,confirmed_by) VALUES (:article,:revision,:account,CAST(:defaults AS jsonb),:note,:user) RETURNING id'), {'article': aid, 'revision': payload.article_revision_id, 'account': payload.account_id, 'defaults': json.dumps(acct['publish_defaults']), 'note': payload.note, 'user': user_id}).scalar_one()
    queue(conn, get_delivery(conn, did), user_id)
    record_operation(conn, user_id=user_id, action='wechat_draft.confirm', object_type='wechat_draft_delivery', object_id=did, detail={'article_revision_id': str(payload.article_revision_id)})
    return get_delivery(conn, did)


def retry(conn, delivery_id, user_id):
    row, art, acct = lock_delivery(conn, delivery_id)
    if row['status'] != 'failed':
        raise ApiError(409, 'draft_retry_blocked', '仅明确失败的草稿交付可重试；未知结果须先核对')
    validate(conn, art, acct, row['article_revision_id'], 'drafts')
    other = conn.execute(text("SELECT 1 FROM wechat_draft_deliveries WHERE article_revision_id=:revision AND account_id=:account AND id<>:id AND status NOT IN ('failed','cancelled')"), {'revision': row['article_revision_id'], 'account': row['account_id'], 'id': row['id']}).scalar()
    if other:
        raise ApiError(409, 'draft_delivery_exists', '该版本已有其他有效草稿交付')
    conn.execute(text("UPDATE wechat_draft_deliveries SET status='pending',error_code=NULL,updated_at=now() WHERE id=:id"), {'id': row['id']})
    queue(conn, row, user_id)
    record_operation(conn, user_id=user_id, action='wechat_draft.retry', object_type='wechat_draft_delivery', object_id=row['id'])
    return get_delivery(conn, delivery_id)


def cancel(conn, delivery_id, user_id):
    row, _, _ = lock_delivery(conn, delivery_id)
    if row['status'] not in ('pending', 'preparing'):
        raise ApiError(409, 'draft_not_cancellable', '草稿已进入写入或已结束，不能取消；请先核对结果')
    conn.execute(text("UPDATE wechat_draft_deliveries SET status='cancelled',updated_at=now() WHERE id=:id"), {'id': row['id']})
    conn.execute(text("UPDATE async_jobs SET status='cancelled',finished_at=now() WHERE id=:id AND status IN ('pending','running')"), {'id': row['async_job_id']})
    conn.execute(text("UPDATE wechat_draft_attempts SET status='failed',error_code='delivery_cancelled',finished_at=now() WHERE delivery_id=:id AND status='preparing'"), {'id': row['id']})
    record_operation(conn, user_id=user_id, action='wechat_draft.cancel', object_type='wechat_draft_delivery', object_id=row['id'])
    return get_delivery(conn, delivery_id)


def finish(conn, delivery_id, attempt_id, status, *, media_id=None, error=None):
    attempt_status = 'synced' if status == 'awaiting_manual_publish' else status
    conn.execute(text('UPDATE wechat_draft_attempts SET status=:status,remote_media_id=COALESCE(:media,remote_media_id),error_code=:error,finished_at=CASE WHEN :terminal THEN now() ELSE finished_at END WHERE id=:id'), {'status': attempt_status, 'media': media_id, 'error': error, 'terminal': attempt_status in ('synced', 'failed'), 'id': attempt_id})
    conn.execute(text('UPDATE wechat_draft_deliveries SET status=:status,remote_media_id=COALESCE(:media,remote_media_id),error_code=:error,updated_at=now() WHERE id=:id'), {'status': status, 'media': media_id, 'error': error, 'id': delivery_id})


def mark_manual_publication(conn, delivery_id, payload, user_id):
    row, art, acct = lock_delivery(conn, delivery_id)
    if row['status'] == 'manual_published':
        if row['manual_article_url'] != payload.article_url or row['manual_note'] != payload.note:
            raise ApiError(409, 'manual_record_conflict', '已有人工发布记录，请保留原证据')
        return get_delivery(conn, delivery_id)
    if row['status'] != 'awaiting_manual_publish':
        raise ApiError(409, 'draft_not_synced', '草稿尚未同步完成')
    validate(conn, art, acct, row['article_revision_id'], 'drafts')
    conn.execute(text("UPDATE wechat_draft_deliveries SET status='manual_published',publication_source='operator',manual_published_by=:user,manual_published_at=now(),manual_article_url=:url,manual_note=:note,updated_at=now() WHERE id=:id"), {'user': user_id, 'url': payload.article_url, 'note': payload.note, 'id': row['id']})
    conn.execute(text("UPDATE articles SET status='published',updated_at=now() WHERE id=:id"), {'id': art['id']})
    record_operation(conn, user_id=user_id, action='wechat_draft.manual_published', object_type='wechat_draft_delivery', object_id=row['id'], detail={'source': 'operator', 'article_url': payload.article_url})
    return get_delivery(conn, delivery_id)
