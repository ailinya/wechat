from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.adapters import wechat_client, object_storage
from app.schemas.articles import ArticleRevisionCreateIn
from app.schemas.wechat import ReconcileIn
from app.services import async_job_service
from app.services.article_service import save
from app.services.publishing_worker import publish_job, reconcile, schedule_once
from test_article_review import CHECKS
from test_wechat_accounts import SETTINGS, bind, login, wechat_transport


@pytest.fixture
def publishing(client, db_engine, wechat_transport, monkeypatch):
    headers = login(client)
    acct = bind(client, headers)
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        cover = conn.execute(text("INSERT INTO stored_objects(bucket,object_key,content_type,size_bytes,sha256,uploader_id) VALUES ('test','cover.png','image/png',8,:hash,:user) RETURNING id"), {'hash': 'c'*64, 'user': user}).scalar_one()
    created = client.post('/api/v1/articles', headers=headers, json={'title': '发布测试', 'body_markdown': '合成正文，不用于真实发布', 'cover_object_id': str(cover)}).json()
    aid, rid = created['article_id'], created['current_revision_id']
    assert client.post(f'/api/v1/articles/{aid}/submit-review', headers=headers, json={'base_revision_id': rid}).status_code == 200
    assert client.post(f'/api/v1/article-revisions/{rid}/reviews', headers=headers, json={'action': 'approve', 'checklist': CHECKS}).status_code == 201
    original = wechat_client.http_transport
    state = {'submit_count': 0, 'timeout': False, 'denied': False, 'query_error': False, 'publish_status': 0}
    def transport(path, payload, token=None, upload=None):
        if path in ('/cgi-bin/material/add_material', '/cgi-bin/media/uploadimg'):
            return {'media_id': 'cover-media', 'url': 'https://mmbiz.qpic.cn/fixture.png'}
        if path == '/cgi-bin/draft/add':
            return {'media_id': 'draft-media'}
        if path == '/cgi-bin/freepublish/submit':
            state['submit_count'] += 1
            if state['timeout']:
                raise wechat_client.WechatError('wechat_unreachable', uncertain=True)
            if state['denied']:
                return {'errcode': 48001}
            return {'publish_id': 'publish-1'}
        if path == '/cgi-bin/freepublish/get':
            if state['query_error']:
                raise wechat_client.WechatError('wechat_unreachable')
            return {'publish_status': state['publish_status'], 'article_id': 'external-article', 'article_detail': {'item': [{'article_url': 'https://mp.weixin.qq.com/s/fixture'}]}}
        return original(path, payload, token, upload)
    monkeypatch.setattr(wechat_client, 'http_transport', transport)
    monkeypatch.setattr(object_storage, 'get_object', lambda *args: b'fake-png')
    return {'headers': headers, 'account': acct, 'aid': aid, 'rid': rid, 'user': user, 'state': state}


def order(client, fixture, **options):
    response = client.post('/api/v1/publish-orders', headers=fixture['headers'], json={'article_revision_id': fixture['rid'], 'account_id': fixture['account']['id'], **options})
    assert response.status_code == 201, response.text
    return response.json()


def run_order(client, engine, row, headers):
    response = client.post(f"/api/v1/publish-orders/{row['id']}/confirm", headers=headers)
    assert response.status_code == 202, response.text
    with engine.begin() as conn:
        jid = response.json()['async_job_id']
        assert async_job_service.claim_job(conn, jid)
        job = async_job_service.get_job(conn, jid)
    publish_job(engine, job, settings=SETTINGS)
    return job


def test_explicit_confirmation_idempotency_and_redelivery(client, db_engine, publishing):
    f = publishing
    headers = {**f['headers'], 'Idempotency-Key': 'create-one'}
    payload = {'article_revision_id': f['rid'], 'account_id': f['account']['id']}
    a = client.post('/api/v1/publish-orders', headers=headers, json=payload)
    b = client.post('/api/v1/publish-orders', headers=headers, json=payload)
    assert a.status_code == 201 and a.json() == b.json()
    assert client.post('/api/v1/publish-orders', headers=headers, json={**payload, 'publish_note': 'different'}).status_code == 409
    assert f['state']['submit_count'] == 0
    row = a.json()
    job = run_order(client, db_engine, row, f['headers'])
    publish_job(db_engine, job, settings=SETTINGS)
    assert f['state']['submit_count'] == 1
    assert client.get(f"/api/v1/publish-orders/{row['id']}").json()['status'] == 'succeeded'
    assert client.post(f"/api/v1/publish-orders/{row['id']}/confirm", headers=f['headers']).json()['status'] == 'succeeded'
    attempts = client.get(f"/api/v1/publish-orders/{row['id']}/attempts").json()
    assert len(attempts) == 1 and attempts[0]['publish_id'] == 'publish-1'
    assert client.get(f"/api/v1/articles/{f['aid']}").json()['status'] == 'published'
    assert client.get('/api/v1/publish-orders').json()['total'] == 1
    assert client.post(f"/api/v1/async-jobs/{job['id']}/cancel", headers=f['headers']).status_code == 409


@pytest.mark.parametrize('mutation', ['edit', 'unbind', 'revoke'])
def test_revalidate_after_confirmation_before_external_call(client, db_engine, publishing, mutation):
    f = publishing
    row = order(client, f)
    response = client.post(f"/api/v1/publish-orders/{row['id']}/confirm", headers=f['headers'])
    assert response.status_code == 202
    with db_engine.begin() as conn:
        if mutation == 'edit':
            save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='新版', body_markdown='新正文'), f['user'], f['aid'])
        elif mutation == 'unbind':
            conn.execute(text("UPDATE wechat_accounts SET status='unbound' WHERE id=:id"), {'id': f['account']['id']})
        else:
            conn.execute(text("UPDATE wechat_accounts SET capabilities='{}' WHERE id=:id"), {'id': f['account']['id']})
        assert async_job_service.claim_job(conn, response.json()['async_job_id'])
        job = async_job_service.get_job(conn, response.json()['async_job_id'])
    publish_job(db_engine, job, settings=SETTINGS)
    assert f['state']['submit_count'] == 0
    assert client.get(f"/api/v1/publish-orders/{row['id']}").json()['status'] == 'failed'


def test_unknown_requires_reconciliation_and_preserves_attempts(client, db_engine, publishing):
    f = publishing
    row = order(client, f)
    f['state']['timeout'] = True
    job = run_order(client, db_engine, row, f['headers'])
    publish_job(db_engine, job, settings=SETTINGS)
    assert f['state']['submit_count'] == 1
    assert client.get(f"/api/v1/publish-orders/{row['id']}").json()['status'] == 'unknown'
    assert client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers=f['headers']).status_code == 409
    assert client.post(f"/api/v1/publish-orders/{row['id']}/reconcile", headers=f['headers'], json={}).status_code == 409
    # Internal service uses the same isolated database and deterministic client.
    result = reconcile(db_engine, SETTINGS, row['id'], ReconcileIn(outcome='not_published', note='测试后台逐项检查，确认未发布'), f['user'])
    assert result['status'] == 'failed'
    f['state']['timeout'] = False
    retry = client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers={**f['headers'], 'Idempotency-Key': 'retry-once'})
    assert retry.status_code == 202, retry.text
    repeated = client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers={**f['headers'], 'Idempotency-Key': 'retry-once'})
    assert retry.json() == repeated.json()
    with db_engine.begin() as conn:
        async_job_service.claim_job(conn, retry.json()['async_job_id'])
        job = async_job_service.get_job(conn, retry.json()['async_job_id'])
    publish_job(db_engine, job, settings=SETTINGS)
    attempts = client.get(f"/api/v1/publish-orders/{row['id']}/attempts").json()
    assert len(attempts) == 2 and attempts[0]['error_code'] == 'manually_confirmed_not_published'
    assert attempts[1]['status'] == 'succeeded' and f['state']['submit_count'] == 2


def test_lost_query_after_accepted_submit_never_allows_retry(client, db_engine, publishing):
    f = publishing
    row = order(client, f)
    f['state']['query_error'] = True
    run_order(client, db_engine, row, f['headers'])
    assert client.get(f"/api/v1/publish-orders/{row['id']}").json()['status'] == 'unknown'
    assert client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers=f['headers']).status_code == 409
    f['state']['query_error'] = False
    result = reconcile(db_engine, SETTINGS, row['id'], ReconcileIn(), f['user'])
    assert result['status'] == 'succeeded' and f['state']['submit_count'] == 1


def test_submitting_freezes_revision_until_external_result(client, db_engine, publishing, monkeypatch):
    from app.errors import ApiError
    f = publishing
    row = order(client, f)
    original = wechat_client.http_transport
    attempted = []
    def while_submitting(path, payload, token=None, upload=None):
        if path == '/cgi-bin/freepublish/submit':
            with db_engine.begin() as conn:
                with pytest.raises(ApiError) as failure:
                    save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='竞态修改', body_markdown='新正文'), f['user'], f['aid'])
                assert failure.value.code == 'publication_in_progress'
                attempted.append(True)
        return original(path, payload, token, upload)
    monkeypatch.setattr(wechat_client, 'http_transport', while_submitting)
    run_order(client, db_engine, row, f['headers'])
    assert attempted == [True] and service_status(client, row['id']) == 'succeeded'
    assert client.get(f"/api/v1/articles/{f['aid']}").json()['revision_id'] == f['rid']


def test_schedule_and_cancel_and_old_version_blocked(client, db_engine, publishing):
    f = publishing
    row = order(client, f, mode='scheduled', scheduled_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    confirmation = client.post(f"/api/v1/publish-orders/{row['id']}/confirm", headers=f['headers'])
    assert confirmation.status_code == 202 and confirmation.json()['async_job_id'] is None
    schedule_once(db_engine, SETTINGS)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE publish_orders SET scheduled_at=now()-interval '1 minute' WHERE id=:id"), {'id': row['id']})
        save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='新版', body_markdown='新正文'), f['user'], f['aid'])
    assert schedule_once(db_engine, SETTINGS)['queued'] == 0
    assert client.get(f"/api/v1/publish-orders/{row['id']}").json()['status'] == 'failed'
    assert f['state']['submit_count'] == 0
    assert client.post('/api/v1/publish-orders', headers=f['headers'], json={'article_revision_id': f['rid'], 'account_id': f['account']['id']}).status_code == 409


def test_unapproved_and_permission_denied(client, db_engine, publishing):
    f = publishing
    login(client, 'editor', 'editor-password')
    assert client.post('/api/v1/publish-orders', headers=f['headers'], json={'article_revision_id': f['rid'], 'account_id': f['account']['id']}).status_code == 403
    f['headers'] = login(client)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE articles SET status='draft' WHERE id=:id"), {'id': f['aid']})
    assert client.post('/api/v1/publish-orders', headers=f['headers'], json={'article_revision_id': f['rid'], 'account_id': f['account']['id']}).status_code == 409


def test_unknown_survives_generic_worker_retries_and_stale_recovery(client, db_engine, publishing, monkeypatch):
    from conftest import TEST_URL
    from app.config import Settings
    from app.modules.async_execution.registry import register_engine_handler
    from app.modules.async_execution.tasks_core import execute_job
    f = publishing
    row = order(client, f)
    accepted = client.post(f"/api/v1/publish-orders/{row['id']}/confirm", headers=f['headers']).json()
    f['state']['timeout'] = True
    register_engine_handler('publish.execute', lambda engine, job: publish_job(engine, job, settings=SETTINGS))
    settings = Settings(APP_SECRET_KEY='t'*40, DATABASE_URL=TEST_URL, JOB_RETRY_BACKOFF_SECONDS=0)
    execute_job(accepted['async_job_id'], settings)
    execute_job(accepted['async_job_id'], settings)
    assert f['state']['submit_count'] == 1
    assert service_status(client, row['id']) == 'unknown'
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE publish_orders SET status='submitting',updated_at=now()-interval '2 days' WHERE id=:id"), {'id': row['id']})
        conn.execute(text("UPDATE publish_attempts SET status='submitting' WHERE order_id=:id"), {'id': row['id']})
    schedule_once(db_engine, SETTINGS)
    assert service_status(client, row['id']) == 'unknown'
    assert client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers=f['headers']).status_code == 409
    assert f['state']['submit_count'] == 1


def service_status(client, oid):
    return client.get(f'/api/v1/publish-orders/{oid}').json()['status']


def test_due_schedule_reentry_cancel_and_per_account_results(client, db_engine, publishing):
    f = publishing
    scheduled = order(client, f, mode='scheduled', scheduled_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    client.post(f"/api/v1/publish-orders/{scheduled['id']}/confirm", headers=f['headers'])
    assert client.post(f"/api/v1/publish-orders/{scheduled['id']}/cancel", headers=f['headers']).json()['status'] == 'cancelled'
    schedule_once(db_engine, SETTINGS)
    assert not client.get(f"/api/v1/publish-orders/{scheduled['id']}/attempts").json()
    first = order(client, f, mode='scheduled', scheduled_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    client.post(f"/api/v1/publish-orders/{first['id']}/confirm", headers=f['headers'])
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE publish_orders SET scheduled_at=now()-interval '1 minute' WHERE id=:id"), {'id': first['id']})
    assert schedule_once(db_engine, SETTINGS)['queued'] == 1
    assert schedule_once(db_engine, SETTINGS)['queued'] == 0
    with db_engine.begin() as conn:
        job_id = conn.execute(text('SELECT async_job_id FROM publish_orders WHERE id=:id'), {'id': first['id']}).scalar_one()
        async_job_service.claim_job(conn, job_id)
        job = async_job_service.get_job(conn, job_id)
    publish_job(db_engine, job, settings=SETTINGS)
    other = bind(client, f['headers'], 'wxfedcba9876543210')
    second = order(client, {**f, 'account': other})
    f['state']['denied'] = True
    run_order(client, db_engine, second, f['headers'])
    assert service_status(client, first['id']) == 'succeeded'
    assert service_status(client, second['id']) == 'failed'
    assert not client.get(f"/api/v1/wechat-accounts/{other['id']}").json()['capabilities']['publish']['available']
    detail = client.get(f"/api/v1/articles/{f['aid']}").json()
    assert detail['status'] == 'published'
    assert detail['publish_summary'] == {'succeeded': 1, 'failed': 1, 'cancelled': 1}
