"""Durable submission boundary; lost responses never cause blind resubmission."""
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from sqlalchemy import text

from app.adapters import object_storage
from app.adapters.wechat_client import WechatClient, WechatError
from app.config import load_settings
from app.errors import ApiError
from app.services import async_job_service, publishing_service as service
from app.services.article_preview import preview
from app.services.article_service import revision
from app.services.audit_service import record_operation


def stored_image(engine, settings, object_id):
    with engine.connect() as conn:
        image = conn.execute(text('SELECT * FROM stored_objects WHERE id=:id'), {'id': str(object_id)}).mappings().first()
        if not image or image['content_type'] not in ('image/png', 'image/jpeg') or image['size_bytes'] > 10 * 1024 * 1024:
            raise WechatError('invalid_publish_image', '发布图片不存在，或格式/大小不符合微信限制')
        key, content_type = image['object_key'], image['content_type']
    return object_storage.get_object(settings, key), content_type


def build_draft_content(engine, settings, client, rev, defaults):
    if not rev['cover_object_id']:
        raise WechatError('cover_required', '微信发布须提供已登记的封面图片')
    if len(rev['title']) > 32 or len(rev['author']) > 16 or len(rev['summary']) > 120:
        raise WechatError('wechat_content_too_long', '微信标题最多32字、作者16字、摘要120字，请保存新版本后重新审核')
    soup = BeautifulSoup(preview(rev['body_markdown'], rev['layout_config']), 'html.parser')
    image_data = []
    if len(soup.find_all('img')) > 20:
        raise WechatError('publish_image_limit', '单篇正文最多支持20张上传图片')
    for image in soup.find_all('img'):
        match = re.fullmatch(r'/api/v1/files/([0-9a-fA-F-]{36})/image', image.get('src', ''))
        if not match:
            raise WechatError('external_image_not_uploaded', '正文外部图片须先上传到系统并替换后重新审核')
        image_data.append((image, stored_image(engine, settings, match[1])))
    cover_data = stored_image(engine, settings, rev['cover_object_id'])
    # Validate every image before creating remote assets.
    for image, (data, content_type) in image_data:
        image['src'] = client.upload(data, content_type)
    cover_id = client.upload(*cover_data, cover=True)
    html = str(soup)
    if len(html) > 20000 or len(html.encode()) >= 1024 * 1024:
        raise WechatError('wechat_content_too_long', '微信正文超出2万字符或1MB限制')
    return {'title': rev['title'], 'author': rev['author'], 'digest': rev['summary'], 'content': html, 'thumb_media_id': cover_id, 'need_open_comment': int(defaults.get('need_open_comment', False)), 'only_fans_can_comment': int(defaults.get('only_fans_can_comment', False))}


def prepare(engine, settings, client, rev, defaults):
    return client.draft(build_draft_content(engine, settings, client, rev, defaults))


def publish_job(engine, job, client_factory=WechatClient, settings=None):
    settings = settings or load_settings()
    oid = job['payload']['order_id']
    attempt_id = None
    submitted = False
    publish_id = None
    try:
        with engine.begin() as conn:
            row, art, acct = service.lock_order(conn, oid)
            if row['status'] != 'confirmed' or not row['confirmed_at'] or str(row['async_job_id']) != str(job['id']) or not async_job_service.is_active(conn, job['id']):
                return
            service.validate(conn, art, acct, row['article_revision_id'])
            if row['mode'] == 'scheduled' and row['scheduled_at'] > datetime.now(timezone.utc):
                return
            attempt_no = conn.execute(text('SELECT COALESCE(max(attempt_no),0)+1 FROM publish_attempts WHERE order_id=:id'), {'id': row['id']}).scalar_one()
            attempt_id = conn.execute(text("INSERT INTO publish_attempts(order_id,attempt_no,status) VALUES (:id,:number,'preparing') RETURNING id"), {'id': row['id'], 'number': attempt_no}).scalar_one()
            conn.execute(text("UPDATE publish_orders SET status='preparing',updated_at=now() WHERE id=:id"), {'id': row['id']})
            rev = revision(conn, row['article_id'], row['article_revision_id'])
        client = client_factory(acct, settings)
        media_id = prepare(engine, settings, client, rev, row['publish_defaults'])
        with engine.begin() as conn:
            current, art, current_acct = service.lock_order(conn, oid)
            if current['status'] != 'preparing' or str(current['async_job_id']) != str(job['id']) or not async_job_service.is_active(conn, job['id']):
                return
            service.validate(conn, art, current_acct, row['article_revision_id'])
            if current_acct['credential_version'] != acct['credential_version']:
                raise ApiError(409, 'account_changed', '准备期间账号配置变更，请重新确认')
            from app.services.wechat_account_service import cache_token
            cache_token(conn, acct, client, settings)
            conn.execute(text("UPDATE publish_attempts SET status='submitting',draft_media_id=:media WHERE id=:id"), {'media': media_id, 'id': attempt_id})
            conn.execute(text("UPDATE publish_orders SET status='submitting',updated_at=now() WHERE id=:id"), {'id': row['id']})
        submitted = True
        publish_id = client.publish(media_id)
        with engine.begin() as conn:
            current, _, _ = service.lock_order(conn, oid)
            # An expired job is allowed to record its single late response; it may never send again.
            if str(current['async_job_id']) != str(job['id']):
                return
            conn.execute(text("UPDATE publish_attempts SET publish_id=:publish,status='publishing' WHERE id=:id"), {'publish': publish_id, 'id': attempt_id})
            conn.execute(text("UPDATE publish_orders SET status='publishing',updated_at=now() WHERE id=:id"), {'id': row['id']})
        result = client.query(publish_id)
        with engine.begin() as conn:
            current, _, _ = service.lock_order(conn, oid)
            if current['status'] not in ('publishing', 'unknown'):
                return
            attempt = dict(conn.execute(text('SELECT * FROM publish_attempts WHERE id=:id'), {'id': attempt_id}).mappings().one())
            service.apply_query(conn, row['id'], attempt, result)
            record_operation(conn, user_id=row['confirmed_by'], action='publish.execute', object_type='publish_order', object_id=row['id'], detail={'attempt_id': str(attempt_id), 'publish_status': result.get('publish_status')})
    except Exception as exc:
        # Never let the generic worker retry a submission after a lost response.
        code = exc.code if isinstance(exc, (ApiError, WechatError)) else 'publish_internal_error'
        unknown = bool(publish_id) or (submitted and (not isinstance(exc, WechatError) or exc.uncertain))
        state = 'unknown' if unknown else 'failed'
        with engine.begin() as conn:
            current, _, _ = service.lock_order(conn, oid)
            if str(current['async_job_id']) != str(job['id']) or current['status'] in ('cancelled', 'succeeded'):
                return
            if attempt_id:
                service.finish(conn, current['id'], attempt_id, state, error=code)
            else:
                conn.execute(text("UPDATE publish_orders SET status='failed',error_code=:code,updated_at=now() WHERE id=:id"), {'code': code, 'id': current['id']})
            async_job_service.finish_job(conn, job['id'], 'failed', last_error=code)
            if code in ('wechat_48001', 'wechat_48004', 'wechat_48002', 'wechat_40001', 'wechat_40014', 'wechat_42001'):
                # A permission rejection is evidence about the current credential, not a reason to resend.
                conn.execute(text("UPDATE wechat_accounts SET capabilities=jsonb_set(capabilities,'{publish}',CAST(:cap AS jsonb)),error_code=:code,updated_at=now() WHERE id=:id AND credential_version=:version"), {'cap': '{"available":false,"reason":"微信拒绝发布权限，请恢复权限后重新检测"}', 'code': code, 'id': current['account_id'], 'version': acct['credential_version']})
            record_operation(conn, user_id=current['confirmed_by'], action='publish.execute', object_type='publish_order', object_id=current['id'], result='denied', detail={'reason': code, 'state': state})


def reconcile(engine, settings, oid, payload, user_id, client_factory=WechatClient):
    with engine.connect() as conn:
        row = service.get_order(conn, oid)
        from app.services.wechat_account_service import account
        acct = account(conn, row['account_id'])
        attempt = conn.execute(text('SELECT * FROM publish_attempts WHERE order_id=:id ORDER BY attempt_no DESC LIMIT 1'), {'id': row['id']}).mappings().first()
        if row['status'] not in ('publishing', 'unknown', 'submitting') or not attempt:
            raise ApiError(409, 'reconcile_not_allowed', '当前状态不需要核对')
        attempt = dict(attempt)
    if row['status'] == 'submitting':
        raise ApiError(409, 'publish_still_executing', '提交可能仍在执行，请等待执行结果或失联检测后核对')
    value = None
    client = None
    if attempt['publish_id']:
        try:
            client = client_factory(acct, settings)
            value = client.query(attempt['publish_id'])
        except WechatError as exc:
            raise ApiError(503, exc.code, exc.message) from None
    elif payload.outcome == 'query':
        raise ApiError(409, 'manual_reconciliation_required', '提交响应丢失且无微信任务 ID，需在公众号后台人工核对')
    elif payload.outcome == 'published':
        # Verify the claimed article exists on this account before recording a manual match.
        try:
            client = client_factory(acct, settings)
            client.call('/cgi-bin/freepublish/getarticle', {'article_id': payload.external_article_id})
        except WechatError as exc:
            raise ApiError(503, exc.code, exc.message) from None
    with engine.begin() as conn:
        current, _, _ = service.lock_order(conn, oid)
        latest = conn.execute(text('SELECT id FROM publish_attempts WHERE order_id=:id ORDER BY attempt_no DESC LIMIT 1'), {'id': current['id']}).scalar_one()
        if latest != attempt['id'] or current['status'] not in ('publishing', 'unknown'):
            raise ApiError(409, 'publish_state_changed', '发布结果已变化，请刷新')
        if client:
            from app.services.wechat_account_service import cache_token
            cache_token(conn, acct, client, settings)
        if value is not None:
            service.apply_query(conn, current['id'], attempt, value)
        else:
            service.finish(conn, current['id'], attempt['id'], 'succeeded' if payload.outcome == 'published' else 'failed', error=None if payload.outcome == 'published' else 'manually_confirmed_not_published', external_id=payload.external_article_id)
        conn.execute(text('UPDATE publish_attempts SET reconciled_by=:user,reconciliation_note=:note WHERE id=:id'), {'user': user_id, 'note': payload.note, 'id': attempt['id']})
        record_operation(conn, user_id=user_id, action='publish.reconcile', object_type='publish_order', object_id=current['id'], detail={'outcome': payload.outcome})
        return service.get_order(conn, oid)


def schedule_once(engine, settings=None, client_factory=WechatClient):
    settings = settings or load_settings()
    with engine.connect() as conn:
        due = conn.execute(text("SELECT id FROM publish_orders WHERE status='confirmed' AND async_job_id IS NULL AND mode='scheduled' AND scheduled_at<=now() ORDER BY scheduled_at LIMIT 100")).scalars().all()
    queued = 0
    for oid in due:
        with engine.begin() as conn:
            row, art, acct = service.lock_order(conn, oid)
            if row['status'] != 'confirmed' or row['async_job_id']:
                continue
            try:
                service.validate(conn, art, acct, row['article_revision_id'])
            except ApiError as exc:
                conn.execute(text("UPDATE publish_orders SET status='failed',error_code=:code,updated_at=now() WHERE id=:id"), {'code': exc.code, 'id': row['id']})
                continue
            service.queue_order(conn, row, row['confirmed_by'])
            queued += 1
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.job_stale_timeout_minutes)
    with engine.begin() as conn:
        conn.execute(text("UPDATE publish_attempts SET status='unknown',error_code='worker_interrupted' WHERE order_id IN (SELECT id FROM publish_orders WHERE status='submitting' AND updated_at<:cutoff) AND status='submitting'"), {'cutoff': cutoff})
        conn.execute(text("UPDATE publish_orders SET status='unknown',error_code='worker_interrupted',updated_at=now() WHERE status='submitting' AND updated_at<:cutoff"), {'cutoff': cutoff})
        conn.execute(text("UPDATE publish_attempts SET status='failed',error_code='preparation_interrupted',finished_at=now() WHERE order_id IN (SELECT id FROM publish_orders WHERE status='preparing' AND updated_at<:cutoff) AND status='preparing'"), {'cutoff': cutoff})
        conn.execute(text("UPDATE publish_orders SET status='failed',error_code='preparation_interrupted',updated_at=now() WHERE status='preparing' AND updated_at<:cutoff"), {'cutoff': cutoff})
        pending = conn.execute(text("SELECT DISTINCT p.id FROM publish_orders p JOIN publish_attempts a ON a.order_id=p.id WHERE p.status IN ('publishing','unknown') AND a.publish_id IS NOT NULL ORDER BY p.id LIMIT 100")).scalars().all()
    from app.schemas.wechat import ReconcileIn
    for oid in pending:
        try:
            reconcile(engine, settings, oid, ReconcileIn(), None, client_factory=client_factory)
        except ApiError:
            pass  # Durable order remains queryable; next bounded scheduler pass may poll again.
    return {'queued': queued, 'polled': len(pending)}
