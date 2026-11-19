"""Release recovery boundaries against the disposable PostgreSQL database."""
import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.config import Settings
from app.errors import ApiError
from app.logging_config import JsonFormatter
from app.modules.async_execution import registry
from app.modules.async_execution.tasks_core import execute_job
from app.services import async_job_service, outbox_service, runtime_service
from test_wechat_accounts import login, wechat_transport
from test_publishing import publishing


def test_readiness_redacts_dependency_failures(monkeypatch):
    from app.services import readiness_service as service
    def broken(*args, **kwargs):
        raise RuntimeError('postgresql://user:private-password@host password=private-password')
    monkeypatch.setattr(service, 'probe_engine', broken)
    monkeypatch.setattr(service.redis.Redis, 'from_url', broken)
    monkeypatch.setattr(service, 'probe', broken)
    result = service.check(Settings(APP_SECRET_KEY='t'*40, DATABASE_URL='postgresql+psycopg://invalid'))
    assert result['status'] == 'degraded'
    assert set(result['checks']) == {'database', 'broker', 'storage'}
    assert all(not value['ready'] for value in result['checks'].values())
    assert 'private-password' not in json.dumps(result)


def test_json_logs_redact_credentials_and_exception():
    record = logging.LogRecord('test', logging.ERROR, '', 0, 'password=private-password Bearer private-token postgresql://user:private-url@host rediss://user:private-redis@host https://files.test/a?X-Amz-Signature=private-signature&X-Amz-Credential=private-credential', (), (RuntimeError, RuntimeError('private-exception'), None))
    record.request_id = 'correlation-123'
    value = JsonFormatter().format(record)
    assert all(secret not in value for secret in ['private-password', 'private-token', 'private-url', 'private-exception', 'private-redis', 'private-signature', 'private-credential'])
    assert json.loads(value)['request_id'] == 'correlation-123'
    assert json.loads(value)['error_type'] == 'RuntimeError'
    record.msg = json.dumps({'api_key':'private quoted value "trailing-private-fragment" with spaces'})
    assert 'trailing-private-fragment' not in JsonFormatter().format(record)
    record.msg = str({'password':'private multiword credential'})
    assert 'multiword credential' not in JsonFormatter().format(record)


def test_early_write_endpoints_require_csrf_before_side_effects(client, db_engine):
    login(client)
    target = str(uuid4())
    for path, body in [('/files/upload-grants',{'filename':'sample.png','content_type':'image/png','size_bytes':68}),('/files/upload-grants/'+target+'/complete',{'sha256':'a'*64}),('/files/'+target+'/download-grant',None),('/async-jobs/'+target+'/cancel',None),('/auth/logout',None)]:
        response = client.post('/api/v1'+path,json=body)
        assert response.status_code == 403, (path,response.text)
        assert response.json()['error']['code'] == 'csrf_failed'
    assert client.get('/api/v1/auth/me').status_code == 200
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM upload_grants')).scalar_one() == 0


def test_business_failure_not_reported_as_success(db_engine):
    with db_engine.begin() as conn:
        job = async_job_service.create_job(conn, 'tests.business_failed', 'test', uuid4())
    registry.register_engine_handler('tests.business_failed', lambda engine, job: {'status':'failed','error':'source_failed'})
    settings = Settings(APP_SECRET_KEY='t'*40, DATABASE_URL=db_engine.url.render_as_string(hide_password=False))
    assert execute_job(job['id'], settings) == {'status':'failed'}
    with db_engine.connect() as conn:
        assert async_job_service.get_job(conn, job['id'])['last_error'] == 'source_failed'


def test_outbox_retry_only_unexecuted_jobs_and_audit(client, db_engine):
    headers = login(client)
    with db_engine.begin() as conn:
        job = async_job_service.create_job(conn, 'system.healthcheck', 'test', uuid4())
        event = outbox_service.publish_event(conn, 'job.requested', 'test', uuid4(), {'kwargs':{'job_id':job['id']},'secret':'never-return'})
        conn.execute(text("UPDATE outbox_events SET status='failed',last_error='never-return' WHERE id=:id"), {'id':event})
    url = f'/api/v1/settings/outbox/{event}/retry'
    assert client.post(url).status_code == 403
    assert 'never-return' not in client.get('/api/v1/settings/outbox').text
    assert client.post(url, headers=headers).json()['async_job_id'] == str(job['id'])
    assert client.post(url, headers=headers).status_code == 409
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE outbox_events SET status='failed' WHERE id=:id"), {'id':event})
        async_job_service.claim_job(conn, job['id'])
    assert client.post(url, headers=headers).status_code == 409
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM operation_logs WHERE action='outbox.retry'")).scalar_one() == 1


def test_stale_job_recovery_preserves_recent_and_pending(db_engine):
    with db_engine.begin() as conn:
        jobs = [async_job_service.create_job(conn, 'system.healthcheck', 'test', uuid4()) for _ in range(3)]
        for job in jobs[:2]:
            async_job_service.claim_job(conn, job['id'])
        conn.execute(text("UPDATE async_jobs SET updated_at=now()-interval '1 day' WHERE id=:id"), {'id':jobs[0]['id']})
    settings = Settings(APP_SECRET_KEY='t'*40)
    assert runtime_service.recover_once(db_engine, settings)['reaped'] == 1
    assert runtime_service.recover_once(db_engine, settings)['reaped'] == 0
    with db_engine.connect() as conn:
        assert [async_job_service.get_job(conn, job['id'])['status'] for job in jobs] == ['failed','running','pending']


def test_lost_delivery_before_claim_restores_original_pending_job(db_engine):
    with db_engine.begin() as conn:
        job = async_job_service.create_job(conn, 'system.healthcheck', 'test', uuid4())
        event = outbox_service.publish_event(conn,'job.requested','test',uuid4(),{'task':'app.modules.async_execution.tasks.run_async_job','kwargs':{'job_id':job['id']}})
        outbox_service.mark_dispatched(conn,event)
        conn.execute(text("UPDATE async_jobs SET updated_at=now()-interval '1 day' WHERE id=:id"),{'id':job['id']})
    settings = Settings(APP_SECRET_KEY='t'*40)
    assert runtime_service.recover_once(db_engine,settings)['recovered_pending'] == 1
    assert runtime_service.recover_once(db_engine,settings)['recovered_pending'] == 0
    with db_engine.begin() as conn:
        assert conn.execute(text('SELECT status FROM outbox_events WHERE id=:id'),{'id':event}).scalar_one() == 'pending'
        assert async_job_service.claim_job(conn,job['id'])
        assert not async_job_service.claim_job(conn,job['id'])


def test_search_terms_unicode_and_repetition(db_engine):
    with db_engine.connect() as conn:
        once = conn.execute(text("SELECT material_search_terms('ＡＢＣ 电池回收 Straße 42')")).scalar_one()
        repeated = conn.execute(text("SELECT material_search_terms(repeat('ＡＢＣ 电池回收 Straße 42 ',60))")).scalar_one()
    assert once == repeated
    assert {'abc','电池','池回','回收','strasse','42'} <= set(once)


def test_collection_api_freezes_executable_source_config(client, db_engine, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from app.adapters import source_fetch
    from app.services.collection_pipeline import execute_collection
    monkeypatch.setattr(source_fetch, '_default_resolver', lambda host, port: ['93.184.216.34'])
    urls = []
    def fetch(url, timeout):
        urls.append(url)
        html = '<html><head><title>完整采集配置回归</title><meta property="article:published_time" content="'+(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()+'"></head><body><article>'+('<p>合成资料，电池回收每月100吨。仅用于验证采集来源快照和自动入库。</p>'*25)+'</article></body></html>'
        return 200, {'content-type':'text/html; charset=utf-8'}, html.encode()
    monkeypatch.setattr(source_fetch, '_default_transport', fetch)
    headers = login(client)
    source = client.post('/api/v1/collection/sources', headers=headers, json={'name':'配置快照','source_type':'web_page','page_kind':'article','base_url':'https://example.test/original'}).json()
    task = client.post('/api/v1/collection/tasks', headers=headers, json={'name':'真实受理回归','source_ids':[source['id']],'auto_materialize':True,'analysis_enabled':False}).json()
    accepted = client.post(f"/api/v1/collection/tasks/{task['id']}/run", headers=headers).json()
    with db_engine.begin() as conn:
        snapshot = conn.execute(text('SELECT config_snapshot FROM collection_runs WHERE id=:id'), {'id':accepted['resource_id']}).scalar_one()
        assert snapshot['sources'][0]['source_type'] == 'web_page'
        assert snapshot['sources'][0]['page_kind'] == 'article'
        assert conn.execute(text("SELECT detail->>'run_id' FROM operation_logs WHERE action='collection.task.run'")).scalar_one() == accepted['resource_id']
        conn.execute(text("UPDATE collection_sources SET base_url='https://example.test/changed' WHERE id=:id"), {'id':source['id']})
    assert execute_collection(db_engine, accepted['resource_id'])['status'] == 'succeeded'
    assert urls == ['https://example.test/original']
    results = client.get('/api/v1/collection/results', params={'run_id':accepted['resource_id']}).json()
    assert results['total'] == 1 and results['items'][0]['material_id']


def test_runtime_never_requeues_external_submitting(client, db_engine, publishing):
    from test_publishing import order
    fixture = publishing
    row = order(client, fixture)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE publish_orders SET status='submitting',updated_at=now()-interval '1 day' WHERE id=:id"), {'id':row['id']})
    runtime_service.recover_once(db_engine, Settings(APP_SECRET_KEY='t'*40))
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM publish_orders WHERE id=:id'), {'id':row['id']}).scalar_one() == 'unknown'
    assert client.post(f"/api/v1/publish-orders/{row['id']}/retry", headers=fixture['headers']).status_code == 409
