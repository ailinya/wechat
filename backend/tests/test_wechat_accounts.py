from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters import wechat_client
from app.config import Settings
from app.services.wechat_account_service import set_default
from app.services.wechat_sync_worker import sync_job

TEST_SECRET = 'test-only-wechat-secret-do-not-use'
SETTINGS = Settings(APP_SECRET_KEY='t'*40)


@pytest.fixture
def wechat_transport(monkeypatch):
    calls = []
    def transport(path, payload, token=None, upload=None):
        calls.append((path, payload))
        if path == '/cgi-bin/stable_token':
            if payload['secret'] == 'invalid-secret-0000':
                return {'errcode': 40125}
            return {'access_token': 'fixture-token-not-a-real-credential', 'expires_in': 7200}
        if path == '/cgi-bin/material/batchget_material':
            return {'total_count': 1, 'item': [{'media_id': 'news-one', 'content': {'news_item': [{'title': '微信历史图文', 'content': '<p>明确标识的确定性素材正文。</p>', 'url': 'https://example.test/news'}]}}]}
        return {'item': [], 'total_count': 0}
    monkeypatch.setattr(wechat_client, 'http_transport', transport)
    return calls


def login(client, account='admin', password='correct-password'):
    assert client.post('/api/v1/auth/login', json={'account': account, 'password': password}).status_code == 200
    return {'X-CSRF-Token': client.cookies.get('wetchat_csrf')}


def bind(client, headers, appid='wx0123456789abcdef', **options):
    response = client.post('/api/v1/wechat-accounts', headers=headers, json={'name': '测试公众号', 'app_id': appid, 'app_secret': TEST_SECRET, 'publish_permission_confirmed': True, **options})
    assert response.status_code == 201, response.text
    return response.json()


def test_account_contract_secret_and_unsupported_callback(client, db_engine, wechat_transport):
    headers = login(client)
    row = bind(client, headers, publish_permission_confirmed=False)
    assert row['status'] == 'active' and not row['capabilities']['publish']['available']
    assert 'secret' not in str(row) and 'fixture-token' not in str(row)
    assert client.get('/api/v1/wechat-accounts').json()['total'] == 1
    with db_engine.connect() as conn:
        saved = conn.execute(text('SELECT secret_encrypted FROM wechat_accounts')).scalar_one()
        assert saved != TEST_SECRET and wechat_client.decrypt(SETTINGS, saved) == TEST_SECRET
    for _ in range(2):
        assert client.get('/api/v1/wechat-accounts/callback?code=forged&state=expired').status_code == 410
    assert client.post('/api/v1/wechat-accounts/authorization', headers=headers).status_code == 410
    schema = client.get('/openapi.json').json()
    assert schema['components']['schemas']['AccountIn']['properties']['app_secret']['writeOnly']
    assert 'app_secret' not in schema['components']['schemas']['AccountOut']['properties']
    changed = client.patch(f"/api/v1/wechat-accounts/{row['id']}", headers=headers, json={'publish_permission_confirmed': True})
    assert changed.json()['capabilities']['publish']['available']
    assert client.put(f"/api/v1/wechat-accounts/{row['id']}/credentials", headers=headers, json={'app_secret': 'invalid-secret-0000'}).status_code == 503
    assert client.get(f"/api/v1/wechat-accounts/{row['id']}").json()['status'] == 'active'
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('target-fixture','fixture','generation','https://example.test','fixture') RETURNING id")).scalar_one()
    targets = client.get('/api/v1/creation-tasks/target-accounts').json()
    assert targets == [{'id': row['id'], 'name': row['name']}]
    rule = client.post('/api/v1/creation-rules', headers=headers, json={'name': '目标账号仅为建议', 'trigger_type': 'manual', 'model_config_id': str(model), 'target_account_id': row['id']})
    assert rule.status_code == 201, rule.text
    assert client.delete(f"/api/v1/wechat-accounts/{row['id']}", headers=headers).status_code == 204
    # Loss of a suggested account must not prevent disabling an automation rule.
    assert client.patch(f"/api/v1/creation-rules/{rule.json()['id']}", headers=headers, json={'enabled': False}).status_code == 200
    with db_engine.connect() as conn:
        logs = str(conn.execute(text('SELECT detail FROM operation_logs')).scalars().all())
        assert TEST_SECRET not in logs and 'fixture-token-not' not in logs
    login(client, 'editor', 'editor-password')
    assert client.get('/api/v1/wechat-accounts').status_code == 403
    assert client.post(f"/api/v1/wechat-accounts/{row['id']}/check", headers=headers).status_code == 403


def test_default_race_and_unbind_keep_sync_history(client, db_engine, wechat_transport):
    headers = login(client)
    a = bind(client, headers)
    b = bind(client, headers, 'wxfedcba9876543210')
    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
    def run(aid):
        with db_engine.begin() as conn:
            set_default(conn, aid, user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, (a['id'], b['id'])))
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM wechat_accounts WHERE is_default')).scalar_one() == 1
    response = client.post(f"/api/v1/wechat-accounts/{a['id']}/sync", headers={**headers, 'Idempotency-Key': 'sync-1'})
    assert response.status_code == 202, response.text
    again = client.post(f"/api/v1/wechat-accounts/{a['id']}/sync", headers={**headers, 'Idempotency-Key': 'sync-1'})
    assert again.json() == response.json()
    with db_engine.begin() as conn:
        job = dict(conn.execute(text('SELECT * FROM async_jobs WHERE id=:id'), {'id': response.json()['async_job_id']}).mappings().one())
    sync_job(db_engine, job, settings=SETTINGS)
    second = client.post(f"/api/v1/wechat-accounts/{a['id']}/sync", headers=headers).json()
    with db_engine.begin() as conn:
        job2 = dict(conn.execute(text('SELECT * FROM async_jobs WHERE id=:id'), {'id': second['async_job_id']}).mappings().one())
    sync_job(db_engine, job2, settings=SETTINGS)
    history = client.get(f"/api/v1/wechat-accounts/{a['id']}/sync-runs").json()
    assert history['total'] == 2
    assert history['items'][0]['reused_count'] == 1 and history['items'][1]['imported_count'] == 1
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM account_synced_materials')).scalar_one() == 1
    assert client.delete(f"/api/v1/wechat-accounts/{a['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/wechat-accounts/{a['id']}/sync-runs").json()['total'] == 2
    assert client.post(f"/api/v1/wechat-accounts/{a['id']}/sync", headers=headers).status_code == 409


def test_new_migrations_roundtrip_and_constraints(db_engine, monkeypatch):
    from conftest import TEST_URL
    monkeypatch.setenv('DATABASE_URL', TEST_URL)
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(cfg, '0017_article_reviews')
    command.upgrade(cfg, 'head')
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fk-fixture','fixture','generation','https://example.test','fixture') RETURNING id")).scalar_one()
    with pytest.raises(IntegrityError) as failure:
        with db_engine.begin() as conn:
            conn.execute(text("INSERT INTO creation_rules(name,trigger_type,model_config_id,target_account_id) VALUES ('bad','manual',:model,:account)"), {'model': model, 'account': uuid4()})
    assert failure.value.orig.diag.constraint_name == 'fk_rule_account'


def test_stale_check_does_not_restore_unbound_account(client, db_engine, wechat_transport, monkeypatch):
    headers = login(client)
    a = bind(client, headers)
    original = wechat_client.http_transport
    changed = False
    def during_check(path, payload, token=None, upload=None):
        nonlocal changed
        if not changed:
            changed = True
            with db_engine.begin() as conn:
                conn.execute(text("UPDATE wechat_accounts SET status='unbound',credential_version=credential_version+1 WHERE id=:id"), {'id': a['id']})
        return original(path, payload, token, upload)
    monkeypatch.setattr(wechat_client, 'http_transport', during_check)
    assert client.post(f"/api/v1/wechat-accounts/{a['id']}/check", headers=headers).status_code == 409
    assert client.get(f"/api/v1/wechat-accounts/{a['id']}").json()['status'] == 'unbound'
