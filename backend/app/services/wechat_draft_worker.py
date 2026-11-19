"""Draft-only delivery. There is deliberately no publication call in this module."""
import json
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from sqlalchemy import text

from app.adapters.wechat_client import WechatClient, WechatError
from app.config import load_settings
from app.errors import ApiError
from app.services import async_job_service, wechat_draft_service as service
from app.services.article_service import revision
from app.services.publishing_service import validate
from app.services.publishing_worker import build_draft_content
from app.services.wechat_account_service import cache_token
from app.services.audit_service import record_operation


def draft_job(engine, job, client_factory=WechatClient, settings=None):
    settings = settings or load_settings()
    did = job['payload']['delivery_id']
    attempt_id = None
    writing = False
    media_id = None
    try:
        with engine.begin() as conn:
            row, art, acct = service.lock_delivery(conn, did)
            if row['status'] != 'pending' or str(row['async_job_id']) != str(job['id']) or not async_job_service.is_active(conn, job['id']):
                return
            validate(conn, art, acct, row['article_revision_id'], 'drafts')
            number = conn.execute(text('SELECT COALESCE(max(attempt_no),0)+1 FROM wechat_draft_attempts WHERE delivery_id=:id'), {'id': row['id']}).scalar_one()
            attempt_id = conn.execute(text("INSERT INTO wechat_draft_attempts(delivery_id,attempt_no,status) VALUES (:id,:number,'preparing') RETURNING id"), {'id': row['id'], 'number': number}).scalar_one()
            conn.execute(text("UPDATE wechat_draft_deliveries SET status='preparing',updated_at=now() WHERE id=:id"), {'id': row['id']})
            rev = revision(conn, row['article_id'], row['article_revision_id'])
        client = client_factory(acct, settings)
        payload = build_draft_content(engine, settings, client, rev, row['publish_defaults'])
        with engine.begin() as conn:
            current, art, current_acct = service.lock_delivery(conn, did)
            if current['status'] != 'preparing' or str(current['async_job_id']) != str(job['id']) or not async_job_service.is_active(conn, job['id']):
                return
            validate(conn, art, current_acct, row['article_revision_id'], 'drafts')
            if current_acct['credential_version'] != acct['credential_version']:
                raise ApiError(409, 'account_changed', '账号配置已变化，请重新核对')
            cache_token(conn, acct, client, settings)
            conn.execute(text("UPDATE wechat_draft_attempts SET status='syncing',expected_payload=CAST(:payload AS jsonb) WHERE id=:id"), {'payload': json.dumps(payload, ensure_ascii=False), 'id': attempt_id})
            conn.execute(text("UPDATE wechat_draft_deliveries SET status='syncing',updated_at=now() WHERE id=:id"), {'id': row['id']})
        writing = True
        media_id = client.draft(payload)
        with engine.begin() as conn:
            current, _, _ = service.lock_delivery(conn, did)
            if str(current['async_job_id']) != str(job['id']):
                return
            service.finish(conn, row['id'], attempt_id, 'awaiting_manual_publish', media_id=media_id)
            conn.execute(text("UPDATE wechat_accounts SET capabilities=jsonb_set(capabilities,'{draft_write}',CAST(:cap AS jsonb)),error_code=NULL WHERE id=:id AND credential_version=:version"), {'cap': '{"available":true,"reason":"已成功写入微信草稿；后续执行仍复验权限"}', 'id': row['account_id'], 'version': acct['credential_version']})
            record_operation(conn, user_id=row['confirmed_by'], action='wechat_draft.synced', object_type='wechat_draft_delivery', object_id=row['id'], detail={'attempt_id': str(attempt_id)})
    except Exception as exc:
        code = exc.code if isinstance(exc, (WechatError, ApiError)) else 'draft_internal_error'
        unknown = bool(media_id) or (writing and (not isinstance(exc, WechatError) or exc.uncertain))
        state = 'unknown' if unknown else 'failed'
        with engine.begin() as conn:
            current, _, _ = service.lock_delivery(conn, did)
            if str(current['async_job_id']) != str(job['id']) or current['status'] in ('cancelled', 'awaiting_manual_publish', 'manual_published'):
                return
            if attempt_id:
                service.finish(conn, current['id'], attempt_id, state, error=code)
            else:
                conn.execute(text("UPDATE wechat_draft_deliveries SET status='failed',error_code=:code,updated_at=now() WHERE id=:id"), {'id': current['id'], 'code': code})
            if writing and code in ('wechat_48001', 'wechat_48004', 'wechat_48002'):
                conn.execute(text("UPDATE wechat_accounts SET capabilities=jsonb_set(capabilities,'{draft_write}',CAST(:cap AS jsonb)),error_code=:code WHERE id=:id AND credential_version=:version"), {'cap': '{"available":false,"reason":"微信拒绝草稿写入，请在微信后台检查权限"}', 'code': code, 'id': current['account_id'], 'version': acct['credential_version']})
            async_job_service.finish_job(conn, job['id'], 'failed', last_error=code)
            record_operation(conn, user_id=current['confirmed_by'], action='wechat_draft.sync', object_type='wechat_draft_delivery', object_id=current['id'], result='denied', detail={'reason': code, 'state': state})


def content_signature(payload):
    soup = BeautifulSoup(payload.get('content') or '', 'html.parser')
    return (payload.get('title', ''), payload.get('author', ''), payload.get('thumb_media_id', ''), ' '.join(soup.get_text(' ', strip=True).split()), tuple(image.get('src', '') for image in soup.find_all('img')))


def reconcile(engine, settings, delivery_id, payload, user_id, client_factory=WechatClient):
    with engine.connect() as conn:
        row = service.get_delivery(conn, delivery_id)
        from app.services.wechat_account_service import account, require_available
        acct = account(conn, row['account_id'])
        require_available(acct, 'drafts')
        attempt = conn.execute(text('SELECT * FROM wechat_draft_attempts WHERE delivery_id=:id ORDER BY attempt_no DESC LIMIT 1'), {'id': row['id']}).mappings().first()
        if row['status'] != 'unknown' or not attempt:
            raise ApiError(409, 'draft_reconcile_not_allowed', '仅结果未知的草稿交付需要核对')
        attempt = dict(attempt)
    match_id = None
    client = None
    if payload.outcome == 'query':
        if not attempt['expected_payload']:
            raise ApiError(409, 'draft_match_unavailable', '缺少待写入正文依据，请在微信后台人工核对')
        matches = set()
        complete = False
        client = client_factory(acct, settings)
        try:
            for page in range(20):
                batch = client.drafts(page * 20)
                for item in batch.get('item', []):
                    news = (item.get('content') or {}).get('news_item') or []
                    if len(news) == 1 and item.get('media_id') and content_signature(news[0]) == content_signature(attempt['expected_payload']):
                        expected_digest = attempt['expected_payload'].get('digest')
                        if not expected_digest or expected_digest == news[0].get('digest'):
                            matches.add(item['media_id'])
                if isinstance(batch.get('total_count'), int) and (page+1)*20 >= batch['total_count']:
                    complete = True
                    break
        except WechatError as exc:
            raise ApiError(503, exc.code, exc.message) from None
        if not complete:
            raise ApiError(409, 'draft_scan_incomplete', '草稿查询未覆盖全部记录，请在微信后台人工核对，不能直接重试')
        if len(matches) != 1:
            raise ApiError(409, 'draft_match_ambiguous' if matches else 'draft_not_found', '未找到唯一匹配草稿，请在微信后台核对，不能直接重试')
        match_id = next(iter(matches))
    with engine.begin() as conn:
        current, _, current_acct = service.lock_delivery(conn, delivery_id)
        latest = conn.execute(text('SELECT id FROM wechat_draft_attempts WHERE delivery_id=:id ORDER BY attempt_no DESC LIMIT 1'), {'id': current['id']}).scalar_one()
        if current['status'] != 'unknown' or latest != attempt['id'] or current_acct['credential_version'] != acct['credential_version']:
            raise ApiError(409, 'draft_state_changed', '草稿或账号状态已变化，请刷新')
        if client:
            cache_token(conn, acct, client, settings)
        service.finish(conn, current['id'], attempt['id'], 'awaiting_manual_publish' if match_id else 'failed', media_id=match_id, error=None if match_id else 'manually_confirmed_not_synced')
        conn.execute(text('UPDATE wechat_draft_attempts SET reconciled_by=:user,reconciliation_note=:note WHERE id=:id'), {'user': user_id, 'note': payload.note or '微信草稿唯一匹配核对', 'id': attempt['id']})
        record_operation(conn, user_id=user_id, action='wechat_draft.reconcile', object_type='wechat_draft_delivery', object_id=current['id'], detail={'outcome': payload.outcome})
        return service.get_delivery(conn, delivery_id)


def recover_stale(conn, minutes):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    conn.execute(text("UPDATE wechat_draft_attempts SET status='unknown',error_code='draft_worker_interrupted' WHERE delivery_id IN (SELECT id FROM wechat_draft_deliveries WHERE status='syncing' AND updated_at<:cutoff) AND status='syncing'"), {'cutoff': cutoff})
    conn.execute(text("UPDATE wechat_draft_deliveries SET status='unknown',error_code='draft_worker_interrupted',updated_at=now() WHERE status='syncing' AND updated_at<:cutoff"), {'cutoff': cutoff})
    conn.execute(text("UPDATE wechat_draft_attempts SET status='failed',error_code='draft_preparation_interrupted',finished_at=now() WHERE delivery_id IN (SELECT id FROM wechat_draft_deliveries WHERE status='preparing' AND updated_at<:cutoff) AND status='preparing'"), {'cutoff': cutoff})
    conn.execute(text("UPDATE wechat_draft_deliveries SET status='failed',error_code='draft_preparation_interrupted',updated_at=now() WHERE status='preparing' AND updated_at<:cutoff"), {'cutoff': cutoff})
