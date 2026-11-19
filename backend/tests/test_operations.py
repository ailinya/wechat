"""Real PostgreSQL aggregates, privacy, export and platform management checks."""
import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.wechat_client import WechatError
from app.schemas.operations import ReportFilters
from app.services import analytics_service, notification_service, operations_service
from app.schemas.auth import CurrentUser, PermissionCode
from test_wechat_accounts import SETTINGS, bind, login, wechat_transport
from test_publishing import publishing, order, run_order


@pytest.fixture
def ops(client, db_engine):
    headers = login(client)
    with db_engine.begin() as conn:
        admin = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        task = conn.execute(text("INSERT INTO collection_tasks(name) VALUES ('统计任务') RETURNING id")).scalar_one()
        first = conn.execute(text("INSERT INTO collection_runs(task_id,trigger,status,created_at,finished_at) VALUES (:task,'manual','succeeded','2026-11-18T16:00:00Z',now()) RETURNING id"), {'task': task}).scalar_one()
        conn.execute(text("INSERT INTO collection_runs(task_id,trigger,status,created_at,finished_at) VALUES (:task,'manual','failed','2026-11-19T15:59:59Z',now())"), {'task': task})
        conn.execute(text("INSERT INTO collection_runs(task_id,trigger,status,created_at) VALUES (:task,'manual','partial','2026-11-19T16:00:00Z')"), {'task': task})
        conn.execute(text("INSERT INTO collection_results(run_id,title,url,dedup_key,parse_status) VALUES (:run,'=HYPERLINK(\"https://evil.test\")','https://example.test/article',:key,'parsed')"), {'run': first, 'key': str(uuid4())})
    article = client.post('/api/v1/articles', headers=headers, json={'title': '=SUM(1,2)', 'body_markdown': '统计种子正文'}).json()
    return {'headers': headers, 'user': admin, 'task': task, 'article': article}


def test_report_filters_local_midnight_export_and_summary(client, ops):
    filters = {'start_date': '2026-11-19', 'end_date': '2026-11-20', 'timezone': 'Asia/Shanghai', 'collection_task_id': str(ops['task'])}
    response = client.get('/api/v1/analytics/collection', params={**filters,'page_size':1})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['total'] == 2 and len(value['items']) == 1
    assert value['summary']['success_rate'] == 0.5 and value['summary']['quantity'] == 1
    assert value['trend'] == [{'day':'2026-11-19','count':2}]
    exported = client.get('/api/v1/analytics/collection/export', params=filters)
    assert exported.status_code == 200, exported.text
    assert len(list(csv.reader(io.StringIO(exported.text.lstrip('\ufeff'))))) == 3
    assert client.get('/api/v1/analytics/collection', params={**filters, 'timezone':'No/Such'}).status_code == 422
    assert client.get('/api/v1/analytics/collection', params={**filters,'account_id':str(uuid4())}).status_code == 422
    assert client.get('/api/v1/analytics/collection', params={**filters,'end_date':'2026-11-19'}).status_code == 422


@pytest.mark.parametrize('kind', ['materials','creation','reviews','publishing','accounts'])
def test_all_report_queries_and_dashboard(client, ops, kind):
    response = client.get('/api/v1/analytics/'+kind)
    assert response.status_code == 200, response.text
    assert response.json()['summary']['success_rate'] is None
    response = client.get('/api/v1/dashboard')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['counters']['published_articles'] == 0 and value['recent_articles'][0]['title'] == '=SUM(1,2)'
    assert any(row['status']=='failed' for row in value['alerts'])


def test_export_formula_hardening_and_unavailable_metrics(client, db_engine, ops, wechat_transport):
    account = bind(client, ops['headers'], name='=SUM(1,2)', publish_permission_confirmed=False)
    result = client.get('/api/v1/analytics/accounts').json()
    assert result['total'] == 1
    assert result['items'][0]['metrics']['reads'] == {'value':None,'available':False,'reason':'尚未采集或接口不可用'}
    exported = client.get('/api/v1/analytics/accounts/export')
    rows = list(csv.reader(io.StringIO(exported.text.lstrip('\ufeff'))))
    assert rows[1][1].startswith("'=") and rows[1][11:14] == ['','','']
    other = bind(client, ops['headers'], 'wxfedcba9876543210')
    assert client.get('/api/v1/analytics/accounts', params={'account_id': account['id']}).json()['total'] == 1
    assert client.get('/api/v1/analytics/accounts', params={'account_id': other['id']}).json()['items'][0]['account_id'] == other['id']


def test_platform_persistence_versioning_roles_audit_and_permissions(client, db_engine, ops):
    old = client.get('/api/v1/settings/platform').json()
    new = {key: old[key] for key in ['name','description','brand_mark','timezone','version']}
    new.update(name='测试智媒平台', timezone='UTC')
    saved = client.put('/api/v1/settings/platform', headers=ops['headers'], json=new)
    assert saved.status_code == 200, saved.text
    assert client.get('/api/v1/platform').json()['name'] == '测试智媒平台'
    assert client.put('/api/v1/settings/platform', headers=ops['headers'], json=new).status_code == 409
    assert client.put('/api/v1/settings/platform', headers=ops['headers'], json={**new,'timezone':'bad'}).status_code == 422
    assert client.put('/api/v1/settings/platform', json=new).status_code == 403
    role = client.post('/api/v1/roles', headers=ops['headers'], json={'name':'metrics-only'}).json()
    assert client.put(f"/api/v1/roles/{role['id']}/permissions", headers=ops['headers'], json={'permission_codes':['analytics:read','analytics:export']}).status_code == 200
    user = client.post('/api/v1/users', headers=ops['headers'], json={'account':'metrics','name':'统计','password':'test-password','role_ids':[role['id']]}).json()
    assert 'password' not in str(user)
    assert client.patch(f"/api/v1/users/{user['id']}", headers=ops['headers'], json={'role_ids':[str(uuid4())]}).status_code == 422
    login(client,'metrics','test-password')
    assert client.get('/api/v1/analytics/collection').status_code == 403
    assert client.get('/api/v1/analytics/collection/export').status_code == 403
    assert client.get('/api/v1/dashboard').json()['counters']['materials_total'] is None
    headers = login(client,'editor','editor-password')
    assert client.get('/api/v1/settings/operation-logs').status_code == 403
    assert client.put('/api/v1/settings/platform', headers=headers, json=new).status_code == 403
    login(client)
    logs = client.get('/api/v1/settings/operation-logs',params={'action':'permission.denied'}).json()
    assert logs['total'] >= 1 and logs['items'][0]['result']=='denied'


def test_private_notification_delivery_preferences_idempotence_and_revocation(client, db_engine, ops):
    aid, rid = ops['article']['article_id'], ops['article']['current_revision_id']
    assert client.post(f'/api/v1/articles/{aid}/submit-review', headers=ops['headers'], json={'base_revision_id':rid}).status_code == 200
    with db_engine.begin() as conn:
        first = notification_service.deliver(conn)
    assert first > 0
    with db_engine.begin() as conn:
        assert notification_service.deliver(conn) == 0
    mine = client.get('/api/v1/notifications').json()
    notification = next(n for n in mine['items'] if n['category']=='review')
    assert client.post(f"/api/v1/notifications/{notification['id']}/read", headers=ops['headers']).json()['read_at']
    headers = login(client,'editor','editor-password')
    assert client.post(f"/api/v1/notifications/{notification['id']}/read", headers=headers).status_code == 404
    assert client.put('/api/v1/notifications/preferences',headers=headers,json={'category':'review','channel':'email','enabled':True}).status_code == 422
    assert client.put('/api/v1/notifications/preferences',headers=headers,json={'category':'review','enabled':False}).status_code == 200
    assert not next(p for p in client.get('/api/v1/notifications/preferences').json() if p['category']=='review')['enabled']
    ops['headers'] = login(client)
    article2 = client.post('/api/v1/articles',headers=ops['headers'],json={'title':'偏好关闭后新事件','body_markdown':'正文'}).json()
    client.post(f"/api/v1/articles/{article2['article_id']}/submit-review",headers=ops['headers'],json={'base_revision_id':article2['current_revision_id']})
    with db_engine.begin() as conn:
        notification_service.deliver(conn)
    login(client,'editor','editor-password')
    assert all(n['title']!='偏好关闭后新事件' for n in client.get('/api/v1/notifications').json()['items'])
    with db_engine.begin() as conn:
        editor_role = conn.execute(text("SELECT id FROM roles WHERE name='editor'")).scalar_one()
        conn.execute(text("DELETE FROM role_permissions WHERE role_id=:role AND permission_id=(SELECT id FROM permissions WHERE code='article:read')"),{'role':editor_role})
    assert all(n['category']!='review' for n in client.get('/api/v1/notifications').json()['items'])


def test_metric_adapter_missing_fields_denial_and_config_race(client, db_engine, ops, wechat_transport):
    from app.services import wechat_account_service
    account = bind(client,ops['headers'],publish_permission_confirmed=False)
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date()-timedelta(days=1)
    class MetricsClient:
        _token = None
        def __init__(self,*args): pass
        def call(self,*args):
            return {'list':[{'msgid':'fixture_1','details':[{'stat_date':day.isoformat(),'int_page_read_count':0,'share_count':5}]}]}
    operations_service.collect_metrics(db_engine,SETTINGS,account['id'],day,ops['user'],MetricsClient)
    value = client.get('/api/v1/analytics/accounts').json()['items'][0]
    assert value['metrics']['reads']['available'] and value['metrics']['reads']['value']==0
    assert value['metrics']['likes']['value'] is None and not value['metrics']['likes']['available']
    assert value['collected_at']
    class Denied(MetricsClient):
        def call(self,*args): raise WechatError('wechat_48001','公众号无此接口权限')
    operations_service.collect_metrics(db_engine,SETTINGS,account['id'],day,ops['user'],Denied)
    assert any(row['status']=='unavailable' for row in client.get('/api/v1/analytics/accounts').json()['items'])
    class Changed(MetricsClient):
        def call(self,*args):
            with db_engine.begin() as conn:
                conn.execute(text('UPDATE wechat_accounts SET credential_version=credential_version+1 WHERE id=:id'),{'id':account['id']})
            return super().call(*args)
    from app.errors import ApiError
    with pytest.raises(ApiError): operations_service.collect_metrics(db_engine,SETTINGS,account['id'],day,ops['user'],Changed)


def test_logs_and_monitor_never_expose_credentials(client, db_engine, ops):
    with db_engine.begin() as conn:
        conn.execute(text("INSERT INTO operation_logs(user_id,action,object_type,result,detail) VALUES (:user,'test.sensitive','test','success',CAST(:value AS jsonb))"), {'user':ops['user'],'value':'{"password":"long-lived-secret","name":"Bearer stolen-value","nested":{"api_key":"secret"}}'})
        conn.execute(text("INSERT INTO async_jobs(job_type,resource_type,resource_id,payload,last_error) VALUES ('test.secret','test',gen_random_uuid(),'{\"secret\":\"do-not-echo\"}','sensitive-error')"))
    logs = client.get('/api/v1/settings/operation-logs',params={'action':'test.sensitive'})
    assert logs.status_code==200, logs.text
    assert 'long-lived-secret' not in logs.text and 'stolen-value' not in logs.text
    jobs = client.get('/api/v1/settings/jobs')
    assert jobs.status_code==200 and 'do-not-echo' not in jobs.text and 'sensitive-error' not in jobs.text


def test_operations_migration_roundtrip_and_nullable_constraints(db_engine, monkeypatch):
    from conftest import TEST_URL
    monkeypatch.setenv('DATABASE_URL',TEST_URL)
    cfg = Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    command.downgrade(cfg,'0020_wechat_draft_deliveries')
    command.upgrade(cfg,'head')
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT value->>'timezone' FROM system_settings WHERE key='platform'")).scalar_one()=='Asia/Shanghai'
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text("INSERT INTO notification_preferences(user_id,category,channel) VALUES ((SELECT id FROM users LIMIT 1),'review','email')"))


from zoneinfo import ZoneInfo


def test_publish_draft_manual_counts_and_notification_event_keys(client, db_engine, publishing):
    from app.services.wechat_draft_worker import draft_job
    from app.services import async_job_service
    f=publishing
    row=client.post('/api/v1/wechat-draft-deliveries',headers=f['headers'],json={'article_revision_id':f['rid'],'account_id':f['account']['id'],'confirm_sync':True}).json()
    with db_engine.begin() as conn:
        async_job_service.claim_job(conn,row['async_job_id'])
        job=async_job_service.get_job(conn,row['async_job_id'])
    draft_job(db_engine,job,settings=SETTINGS)
    before=client.get('/api/v1/analytics/publishing').json()
    assert before['summary']['by_source']=={'draft_sync':1}
    assert before['summary']['denominator']==0 and before['summary']['by_status']=={'synced':1}
    assert any(item['status']=='awaiting_manual_publish' for item in client.get('/api/v1/dashboard').json()['todos'])
    with db_engine.begin() as conn:
        notification_service.deliver(conn)
    manual=client.post(f"/api/v1/wechat-draft-deliveries/{row['id']}/manual-published",headers=f['headers'],json={'content_matches_revision':True,'article_url':'https://mp.weixin.qq.com/s/fixture','note':'确定性人工登记'})
    assert manual.status_code==200
    api=order(client,f)
    run_order(client,db_engine,api,f['headers'])
    result=client.get('/api/v1/analytics/publishing').json()
    assert result['summary']['denominator']==1 and result['summary']['success_rate']==1
    assert result['summary']['by_source']=={'api_publish':1,'draft_sync':1,'operator':1}
    assert result['summary']['by_status']['manual_published']==1
    assert client.get('/api/v1/dashboard').json()['counters']['published_articles']==1
    with db_engine.begin() as conn:
        notification_service.deliver(conn)
        assert notification_service.deliver(conn)==0
    mine=client.get('/api/v1/notifications').json()['items']
    assert len([n for n in mine if n['category']=='publishing'])==3


def test_model_secret_inputs_and_embedding_use_correct_adapter(client, db_engine, ops, monkeypatch):
    from app.adapters import embedding_client
    model={'name':'参数检查','provider':'openai-compatible','purpose':'analysis','endpoint':'https://example.test/v1/chat/completions','model_name':'fixture'}
    for bad in [{'credential_ref':'sk-plaintext-key'},{'params':{'api_key':'forbidden'}},{'endpoint':'https://user:password@example.test/v1'},{'endpoint':'https://example.test/v1?api_key=forbidden'}]:
        assert client.post('/api/v1/model-configs',headers=ops['headers'],json={**model,**bad}).status_code==422
    created=client.post('/api/v1/model-configs',headers=ops['headers'],json={**model,'purpose':'embedding'})
    assert created.status_code==201,created.text
    assert client.post(f"/api/v1/model-configs/{created.json()['id']}/test",headers=ops['headers']).status_code==409
    monkeypatch.setattr(embedding_client,'embed_texts',lambda texts:([[0.0]*1024],{}))
    result=client.post('/api/v1/settings/integrations/embedding/test',headers=ops['headers'])
    assert result.status_code==200 and result.json()['reachable']


def test_material_reuse_and_creation_retries_do_not_inflate_counts(client, db_engine, ops):
    import json
    material=client.post('/api/v1/materials',headers=ops['headers'],json={'title':'复用统计素材','content_markdown':'同一素材多次引用'}).json()
    ref={'material_id':material['id'],'material_revision_id':material['current_revision_id']}
    articles=[]
    for index in range(2):
        response=client.post('/api/v1/articles',headers=ops['headers'],json={'title':f'复用文章{index}','body_markdown':'引用正文','materials':[ref]})
        assert response.status_code==201,response.text
        articles.append(response.json())
    saved=client.post(f"/api/v1/articles/{articles[0]['article_id']}/revisions",headers=ops['headers'],json={'base_revision_id':articles[0]['current_revision_id'],'title':'复用文章新版','body_markdown':'更新正文','materials':[ref]})
    assert saved.status_code==201,saved.text
    with db_engine.begin() as conn:
        task=conn.execute(text("INSERT INTO creation_tasks(mode,topic,status,trigger_type,trigger_window,config_snapshot) VALUES ('topic','逻辑任务统计','succeeded','manual','fixture',CAST(:config AS jsonb)) RETURNING id"),{'config':json.dumps({'collection_task_ids':[str(ops['task'])]})}).scalar_one()
        for slot,article in enumerate(articles,1):
            conn.execute(text("UPDATE articles SET creation_task_id=:task,slot=:slot,origin_type='generated' WHERE id=:id"),{'task':task,'slot':slot,'id':article['article_id']})
        conn.execute(text('INSERT INTO creation_task_materials(creation_task_id,material_id,material_revision_id,selected) VALUES (:task,:material,:revision,true)'),{'task':task,'material':material['id'],'revision':material['current_revision_id']})
        conn.execute(text("INSERT INTO async_jobs(job_type,resource_type,resource_id,status,attempts) VALUES ('creation.generate','creation_task',:task,'failed',1),('creation.generate','creation_task',:task,'succeeded',2)"),{'task':task})
        conn.execute(text('UPDATE collection_results SET material_id=:material'),{'material':material['id']})
    creation=client.get('/api/v1/analytics/creation',params={'creation_task_id':str(task),'collection_task_id':str(ops['task'])})
    assert creation.status_code==200,creation.text
    assert creation.json()['total']==1 and creation.json()['summary']['quantity']==2 and creation.json()['summary']['attempts']==3
    materials=client.get('/api/v1/analytics/materials',params={'creation_task_id':str(task),'collection_task_id':str(ops['task'])})
    assert materials.status_code==200,materials.text
    assert materials.json()['total']==1 and materials.json()['items'][0]['reference_count']==2
    assert materials.json()['summary']['reused_materials']==1
