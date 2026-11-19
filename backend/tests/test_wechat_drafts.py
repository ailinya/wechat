"""Draft-only integration tests; all WeChat responses are deterministic fixtures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters import wechat_client
from app.errors import ApiError
from app.schemas.articles import ArticleRevisionCreateIn
from app.schemas.wechat_drafts import DraftDeliveryIn, DraftReconcileIn
from app.services import async_job_service, wechat_draft_service as service
from app.services.article_service import save
from app.services.wechat_draft_worker import draft_job, reconcile, recover_stale
from test_publishing import publishing
from test_wechat_accounts import SETTINGS, wechat_transport, login


@pytest.fixture
def drafts(client, db_engine, publishing, monkeypatch):
    f = publishing
    assert client.patch(f"/api/v1/wechat-accounts/{f['account']['id']}", headers=f['headers'], json={'publish_permission_confirmed': False}).status_code == 200
    original = wechat_client.http_transport
    state = {'writes': 0, 'timeout': False, 'denied': False, 'content': None, 'total': 1}
    def transport(path, payload, token=None, upload=None):
        if path == '/cgi-bin/draft/add':
            state['writes'] += 1
            state['content'] = payload['articles'][0]
            if state['timeout']:
                raise wechat_client.WechatError('wechat_unreachable', uncertain=True)
            if state['denied']:
                return {'errcode': 48001}
            return {'media_id': 'private-draft-fixture'}
        if path == '/cgi-bin/draft/batchget':
            return {'total_count': state['total'], 'item': [{'media_id': 'private-draft-fixture', 'content': {'news_item': [state['content']]}}] if state['content'] else []}
        assert path != '/cgi-bin/freepublish/submit', 'Draft delivery must never publish'
        return original(path, payload, token, upload)
    monkeypatch.setattr(wechat_client, 'http_transport', transport)
    return f, state


def create(client, f, **extra):
    response = client.post('/api/v1/wechat-draft-deliveries', headers={**f['headers'], 'Idempotency-Key': 'draft-once'}, json={'article_revision_id': f['rid'], 'account_id': f['account']['id'], 'confirm_sync': True, **extra})
    assert response.status_code == 202, response.text
    return response.json()


def run(engine, row):
    with engine.begin() as conn:
        assert async_job_service.claim_job(conn, row['async_job_id'])
        job = async_job_service.get_job(conn, row['async_job_id'])
    draft_job(engine, job, settings=SETTINGS)
    return job


def detail(client, row):
    return client.get(f"/api/v1/wechat-draft-deliveries/{row['id']}").json()


def test_draft_only_idempotency_redelivery_and_manual_evidence(client, db_engine, drafts):
    f, state = drafts
    row = create(client, f)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE wechat_draft_deliveries SET status='manual_published',remote_media_id='fixture',manual_published_by=:user,manual_published_at=now(),manual_article_url='https://mp.weixin.qq.com/s/fixture',publication_source='operator',manual_note=NULL WHERE id=:id"), {'id': row['id'], 'user': f['user']})
    assert create(client, f) == row
    assert client.post('/api/v1/wechat-draft-deliveries', headers=f['headers'], json={'article_revision_id': f['rid'], 'account_id': f['account']['id'], 'confirm_sync': True}).status_code == 409
    job = run(db_engine, row)
    draft_job(db_engine, job, settings=SETTINGS)
    assert state['writes'] == 1
    assert detail(client, row)['status'] == 'awaiting_manual_publish'
    article = client.get(f"/api/v1/articles/{f['aid']}").json()
    assert article['status'] == 'approved' and article['draft_summary'] == {'awaiting_manual_publish': 1}
    assert article['publish_summary'] == {}
    attempts = client.get(f"/api/v1/wechat-draft-deliveries/{row['id']}/attempts").json()
    assert len(attempts) == 1 and 'expected_payload' not in attempts[0]
    url = f"/api/v1/wechat-draft-deliveries/{row['id']}/manual-published"
    evidence = {'article_url': 'https://mp.weixin.qq.com/s/fixture-evidence', 'note': '确定性人工登记测试', 'content_matches_revision': True}
    for changes in [{'article_url': 'https://evil.test/s/a'}, {'content_matches_revision': False}, {'note': ' '}]:
        assert client.post(url, headers=f['headers'], json={**evidence, **changes}).status_code == 422
    result = client.post(url, headers=f['headers'], json=evidence)
    assert result.status_code == 200, result.text
    assert result.json()['publication_source'] == 'operator'
    assert client.post(url, headers=f['headers'], json=evidence).json() == result.json()
    assert client.get(f"/api/v1/articles/{f['aid']}").json()['status'] == 'published'
    assert state['writes'] == 1 and f['state']['submit_count'] == 0


def test_unknown_reconciliation_never_duplicates(client, db_engine, drafts):
    f, state = drafts
    row = create(client, f)
    state['timeout'] = True
    run(db_engine, row)
    assert detail(client, row)['status'] == 'unknown'
    assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/retry", headers=f['headers']).status_code == 409
    with db_engine.begin() as conn, pytest.raises(ApiError, match='先处理同步结果'):
        save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='新版', body_markdown='新正文'), f['user'], f['aid'])
    state['total'] = 401
    with pytest.raises(ApiError) as exc:
        reconcile(db_engine, SETTINGS, row['id'], DraftReconcileIn(), f['user'])
    assert exc.value.code == 'draft_scan_incomplete'
    state['total'] = 1
    result = reconcile(db_engine, SETTINGS, row['id'], DraftReconcileIn(), f['user'])
    assert result['status'] == 'awaiting_manual_publish' and result['remote_media_id'] == 'private-draft-fixture'
    assert state['writes'] == 1


@pytest.mark.parametrize('change', ['edit', 'unbind', 'credential'])
def test_prepare_revalidates_before_writing(client, db_engine, drafts, monkeypatch, change):
    f, state = drafts
    row = create(client, f)
    from app.services import wechat_draft_worker as worker
    original = worker.build_draft_content
    def prepare(*args):
        value = original(*args)
        with db_engine.begin() as conn:
            if change == 'edit':
                save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='新版本', body_markdown='新版正文'), f['user'], f['aid'])
            elif change == 'unbind':
                conn.execute(text("UPDATE wechat_accounts SET status='unbound' WHERE id=:id"), {'id': f['account']['id']})
            else:
                conn.execute(text('UPDATE wechat_accounts SET credential_version=credential_version+1 WHERE id=:id'), {'id': f['account']['id']})
        return value
    monkeypatch.setattr(worker, 'build_draft_content', prepare)
    run(db_engine, row)
    assert state['writes'] == 0 and detail(client, row)['status'] == 'failed'


def test_denied_retry_cancel_and_stale_version(client, db_engine, drafts):
    f, state = drafts
    row = create(client, f)
    state['denied'] = True
    run(db_engine, row)
    assert detail(client, row)['error_code'] == 'wechat_48001'
    state['denied'] = False
    retry = client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/retry", headers={**f['headers'], 'Idempotency-Key': 'retry-once'})
    assert retry.status_code == 202
    assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/retry", headers={**f['headers'], 'Idempotency-Key': 'retry-once'}).json() == retry.json()
    run(db_engine, retry.json())
    assert client.get(f"/api/v1/wechat-accounts/{f['account']['id']}").json()['capabilities']['draft_write']['available']
    with db_engine.begin() as conn:
        save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='新版', body_markdown='新正文'), f['user'], f['aid'])
    assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/manual-published", headers=f['headers'], json={'content_matches_revision': True, 'article_url': 'https://mp.weixin.qq.com/s/fixture', 'note': '人工登记'}).status_code == 409
    assert len(client.get(f"/api/v1/wechat-draft-deliveries/{row['id']}/attempts").json()) == 2


def test_cancel_and_stale_worker_recovery(client, db_engine, drafts):
    f, state = drafts
    row = create(client, f)
    assert client.post(f"/api/v1/async-jobs/{row['async_job_id']}/cancel", headers=f['headers']).status_code == 409
    assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/cancel", headers=f['headers']).json()['status'] == 'cancelled'
    with db_engine.begin() as conn:
        payload = DraftDeliveryIn(article_revision_id=f['rid'], account_id=f['account']['id'], confirm_sync=True)
        second = service.create_delivery(conn, payload, f['user'])
        conn.execute(text("UPDATE wechat_draft_deliveries SET status='syncing',updated_at=:old WHERE id=:id"), {'id': second['id'], 'old': datetime.now(timezone.utc)-timedelta(hours=2)})
        conn.execute(text("INSERT INTO wechat_draft_attempts(delivery_id,attempt_no,status) VALUES (:id,1,'syncing')"), {'id': second['id']})
    with db_engine.begin() as conn:
        recover_stale(conn, 30)
    assert detail(client, second)['status'] == 'unknown'
    assert state['writes'] == 0


def test_concurrent_create_and_editor_cannot_confirm(client, db_engine, drafts):
    f, _ = drafts
    def make(_):
        try:
            with db_engine.begin() as conn:
                return service.create_delivery(conn, DraftDeliveryIn(article_revision_id=f['rid'], account_id=f['account']['id'], confirm_sync=True), f['user'])['id']
        except ApiError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(make, range(2)))
    assert values.count('draft_delivery_exists') == 1
    headers = login(client, 'editor', 'editor-password')
    assert client.post('/api/v1/wechat-draft-deliveries', headers=headers, json={'article_revision_id': f['rid'], 'account_id': f['account']['id'], 'confirm_sync': True}).status_code == 403


def test_write_boundary_freezes_editing_and_cancellation(client, db_engine, drafts, monkeypatch):
    f, state = drafts
    row = create(client, f)
    original = wechat_client.http_transport
    def transport(path, payload, token=None, upload=None):
        if path == '/cgi-bin/draft/add':
            with db_engine.begin() as conn, pytest.raises(ApiError) as exc:
                save(conn, ArticleRevisionCreateIn(base_revision_id=f['rid'], title='不能插入的新版本', body_markdown='新版'), f['user'], f['aid'])
            assert exc.value.code == 'draft_delivery_in_progress'
            assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/cancel", headers=f['headers']).status_code == 409
        return original(path, payload, token, upload)
    monkeypatch.setattr(wechat_client, 'http_transport', transport)
    run(db_engine, row)
    assert detail(client, row)['status'] == 'awaiting_manual_publish' and state['writes'] == 1


def test_cancel_during_preparation_prevents_draft_write(client, db_engine, drafts, monkeypatch):
    f, state = drafts
    row = create(client, f)
    from app.services import wechat_draft_worker as worker
    original = worker.build_draft_content
    def prepare(*args):
        value = original(*args)
        assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/cancel", headers=f['headers']).status_code == 200
        return value
    monkeypatch.setattr(worker, 'build_draft_content', prepare)
    run(db_engine, row)
    assert detail(client, row)['status'] == 'cancelled' and state['writes'] == 0


def test_generic_execution_timeout_replay_and_confirm_unreviewed_block(client, db_engine, drafts):
    from conftest import TEST_URL
    from app.config import Settings
    from app.modules.async_execution.registry import register_engine_handler
    from app.modules.async_execution.tasks_core import execute_job
    f, state = drafts
    payload = {'article_revision_id': f['rid'], 'account_id': f['account']['id']}
    assert client.post('/api/v1/wechat-draft-deliveries', headers=f['headers'], json=payload).status_code == 422
    row = create(client, f)
    state['timeout'] = True
    register_engine_handler('wechat.draft', lambda engine, job: draft_job(engine, job, settings=SETTINGS))
    settings = Settings(APP_SECRET_KEY='t'*40, DATABASE_URL=TEST_URL, JOB_RETRY_BACKOFF_SECONDS=0)
    execute_job(row['async_job_id'], settings)
    execute_job(row['async_job_id'], settings)
    assert detail(client, row)['status'] == 'unknown' and state['writes'] == 1
    with db_engine.connect() as conn:
        assert async_job_service.get_job(conn, row['async_job_id'])['status'] == 'failed'
    assert client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/reconcile", headers=f['headers'], json={'outcome': 'not_synced'}).status_code == 422
    result = reconcile(db_engine, SETTINGS, row['id'], DraftReconcileIn(outcome='not_synced', note='测试后台确认无草稿'), f['user'])
    assert result['status'] == 'failed'
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE articles SET status='draft' WHERE id=:id"), {'id': f['aid']})
    assert client.post('/api/v1/wechat-draft-deliveries', headers=f['headers'], json={**payload, 'confirm_sync': True}).status_code == 409
