"""Opt-in browser fixture: real API/DB and deterministic WeChat transport.

Only synthetic AppIDs/secrets are accepted. Never deploy this module.
"""
import base64
import os

from fastapi import Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import DbSession, require_permission
from app.adapters import wechat_client, object_storage
from app.config import load_settings
from app.database import get_engine
from app.main import create_app
from app.modules.async_execution.registry import register_engine_handler
from app.modules.async_execution.tasks_core import execute_job
from app.schemas.auth import PermissionCode
from app.services.publishing_worker import publish_job
from app.services.wechat_sync_worker import sync_job
from app.services.wechat_draft_worker import draft_job

if os.environ.get('WECHAT_E2E_FIXTURE') != '1' or not os.environ.get('DATABASE_URL', '').endswith('/wetchat_phase06_test'):
    raise RuntimeError('Fixture requires explicit opt-in and isolated wetchat_phase06_test')

settings = load_settings()
engine = get_engine(settings)
app = create_app(settings)
with engine.connect() as conn:
    has_admin = conn.execute(text("SELECT 1 FROM users WHERE account='admin'")).scalar()
if not has_admin:
    from tests.conftest import seed_users
    seed_users(engine)
state = {'timeout_next': False, 'submissions': 0}
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII=')


def transport(path, payload, token=None, upload=None):
    if path == '/cgi-bin/stable_token':
        if payload['appid'] not in ('wx0123456789abcdef', 'wxfedcba9876543210') or payload['secret'] != 'fixture-only-not-a-real-appsecret':
            return {'errcode': 40125}
        return {'access_token': 'fixture-only-token', 'expires_in': 7200}
    if path == '/cgi-bin/material/batchget_material':
        return {'total_count': 1, 'item': [{'media_id': 'fixture-news', 'content': {'news_item': [{'title': '[确定性fixture] 微信素材', 'content': '<p>仅供浏览器测试的中文图文。</p>'}]}}]}
    if path in ('/cgi-bin/material/add_material', '/cgi-bin/media/uploadimg'):
        return {'media_id': 'fixture-cover', 'url': 'https://mmbiz.qpic.cn/fixture.png'}
    if path == '/cgi-bin/draft/add':
        return {'media_id': 'fixture-draft'}
    if path == '/cgi-bin/freepublish/submit':
        state['submissions'] += 1
        if state['timeout_next']:
            state['timeout_next'] = False
            raise wechat_client.WechatError('wechat_unreachable', uncertain=True)
        return {'publish_id': f"fixture-publish-{state['submissions']}"}
    if path == '/cgi-bin/freepublish/get':
        return {'publish_status': 0, 'article_id': 'fixture-external-article', 'article_detail': {'item': [{'article_url': 'https://mp.weixin.qq.com/s/fixture'}]}}
    return {'item': [], 'total_count': 0}


wechat_client.http_transport = transport
object_storage.get_object = lambda *args: PNG
object_storage.presigned_get = lambda *args: '/api/v1/__test__/cover-image'
register_engine_handler('account.sync', sync_job)
register_engine_handler('publish.execute', publish_job)
register_engine_handler('wechat.draft', draft_job)


@app.post('/api/v1/__test__/cover')
def cover(db: DbSession, user=Depends(require_permission(PermissionCode.ARTICLE_WRITE))):
    result = db.connection().execute(text("INSERT INTO stored_objects(bucket,object_key,content_type,size_bytes,sha256,uploader_id) VALUES ('fixture',gen_random_uuid()::text,'image/png',:size,:sha,:user) RETURNING id"), {'size': len(PNG), 'sha': 'f'*64, 'user': user.id}).scalar_one()
    db.commit()
    return {'id': result}


@app.get('/api/v1/__test__/cover-image')
def cover_image(user=Depends(require_permission(PermissionCode.ARTICLE_READ))):
    return Response(PNG, media_type='image/png')


@app.post('/api/v1/__test__/drain/{job_id}')
def drain(job_id: str, user=Depends(require_permission(PermissionCode.PUBLISH_EXECUTE))):
    return execute_job(job_id, settings)


class Mode(BaseModel):
    timeout_next: bool


@app.post('/api/v1/__test__/mode')
def mode(payload: Mode, user=Depends(require_permission(PermissionCode.PUBLISH_EXECUTE))):
    state['timeout_next'] = payload.timeout_next
    return {'fixture': True}
