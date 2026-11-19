"""Bounded news-material sync with per-item durable deduplication."""
from sqlalchemy import text

from app.adapters.wechat_client import WechatClient, WechatError
from app.config import load_settings
from app.errors import ApiError
from app.services import async_job_service, document_parser, material_service
from app.services.wechat_account_service import account, require_available


def sync_job(engine, job, client_factory=WechatClient, settings=None):
    settings = settings or load_settings()
    rid = job['payload']['sync_run_id']
    with engine.begin() as conn:
        run = conn.execute(text("UPDATE account_sync_runs SET status='running' WHERE id=:id AND status='pending' AND async_job_id=:job RETURNING *"), {'id': rid, 'job': job['id']}).mappings().first()
        if not run:
            return
        run = dict(run)
    try:
        with engine.connect() as conn:
            row = account(conn, run['account_id'])
            require_available(row, 'materials')
        client = client_factory(row, settings)
        for page in range(20):
            with engine.connect() as conn:
                require_available(account(conn, row['id']), 'materials')
            batch = client.news(page * 20)
            items = batch.get('item', [])
            if not isinstance(items, list):
                raise WechatError('invalid_wechat_response')
            for item in items:
                for index, news in enumerate((item.get('content') or {}).get('news_item', [])):
                    parsed = document_parser.parse_html(news.get('content') or '')
                    if not parsed.content_markdown.strip() or not item.get('media_id'):
                        raise WechatError('invalid_synced_content', '微信图文缺少有效正文或标识')
                    with engine.begin() as conn:
                        # Serialize item links; no network calls while this lock is held.
                        current = account(conn, row['id'], lock=True)
                        require_available(current, 'materials')
                        if current['credential_version'] != row['credential_version']:
                            raise ApiError(409, 'account_changed', '账号凭据已变更')
                        found = conn.execute(text('SELECT material_id FROM account_synced_materials WHERE account_id=:account AND media_id=:media AND item_index=:idx'), {'account': row['id'], 'media': item['media_id'], 'idx': index}).scalar()
                        if found:
                            conn.execute(text('UPDATE account_sync_runs SET reused_count=reused_count+1 WHERE id=:id'), {'id': rid})
                        else:
                            material = material_service.create_material(conn, title=news.get('title') or '公众号历史图文', content_markdown=parsed.content_markdown, origin='article', user_id=run['created_by'], source_url=news.get('url'))
                            conn.execute(text('INSERT INTO account_synced_materials(account_id,media_id,item_index,material_id,sync_run_id) VALUES (:account,:media,:idx,:material,:run)'), {'account': row['id'], 'media': item['media_id'], 'idx': index, 'material': material['id'], 'run': rid})
                            conn.execute(text('UPDATE account_sync_runs SET imported_count=imported_count+1 WHERE id=:id'), {'id': rid})
            total = batch.get('total_count', 0)
            if not items or (page + 1) * 20 >= total:
                break
        else:
            raise WechatError('sync_limit_reached', '本次同步达到 400 条图文组上限，已保存部分结果')
        with engine.begin() as conn:
            from app.services.wechat_account_service import cache_token
            cache_token(conn, row, client, settings)
            conn.execute(text("UPDATE account_sync_runs SET status='succeeded',finished_at=now() WHERE id=:id"), {'id': rid})
            conn.execute(text('UPDATE wechat_accounts SET last_synced_at=now() WHERE id=:id'), {'id': row['id']})
    except Exception as exc:
        code = exc.code if isinstance(exc, (WechatError, ApiError, document_parser.ParseError)) else 'sync_internal_error'
        with engine.begin() as conn:
            conn.execute(text("UPDATE account_sync_runs SET status='failed',error_code=:code,finished_at=now() WHERE id=:id"), {'id': rid, 'code': code})
            async_job_service.finish_job(conn, job['id'], 'failed', last_error=code)
