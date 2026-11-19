"""Fault drills affect only the disposable acceptance Compose services."""
import json
from release_support import ROOT, api, client, compose, engine, save, wait_job, wait_until
from sqlalchemy import text


def main():
    c = client()
    checks = []
    def ready():
        return c.get('/ready').status_code == 200
    try:
        compose('stop', 'redis')
        response = c.get('/ready')
        assert response.status_code == 503 and not response.json()['checks']['broker']['ready']
        assert c.get('/health').status_code == 200
        job = api(c, '/__acceptance__/health-job', 'POST')
        with engine().connect() as conn:
            assert conn.execute(text('SELECT status FROM async_jobs WHERE id=:id'), {'id':job['async_job_id']}).scalar_one() == 'pending'
            assert conn.execute(text("SELECT count(*) FROM outbox_events WHERE payload->'kwargs'->>'job_id'=:id"), {'id':job['async_job_id']}).scalar_one() == 1
        compose('start', 'redis')
        wait_until(ready)
        wait_job(c, job['async_job_id'])
        checks.append('broker_outage_durable_outbox_recovery')
        compose('stop', 'worker')
        job = api(c, '/__acceptance__/health-job', 'POST')
        assert api(c, '/async-jobs/'+job['async_job_id'])['status'] == 'pending'
        compose('start', 'worker')
        wait_job(c, job['async_job_id'])
        assert api(c, '/async-jobs/'+job['async_job_id'])['attempts'] == 1
        checks.append('worker_restart_pending_job_once')
        compose('stop', 'rustfs')
        response = c.get('/ready')
        assert response.status_code == 503 and not response.json()['checks']['storage']['ready']
        assert c.get('/health').status_code == 200
        compose('start', 'rustfs')
        wait_until(ready)
        checks.append('object_storage_outage_readiness_and_recovery')
        record = json.loads((ROOT/'.acceptance/workflow.json').read_text())
        material = api(c, '/materials/'+record['material_id'])
        api(c, '/__acceptance__/faults', 'POST', {'model_timeout':True})
        creation = api(c, '/creation-tasks', 'POST', {'mode':'topic','topic':'[fixture] timeout drill','model_config_id':record['model_id'],'min_words':100,'max_words':800,'materials':[{'material_id':record['material_id'],'revision_id':material['current_revision_id']}]})
        wait_job(c, creation['async_job_id'], expected='failed')
        assert api(c, '/creation-tasks/'+creation['resource_id']+'/outputs') == []
        api(c, '/__acceptance__/faults', 'POST', {})
        retried = api(c, '/creation-tasks/'+creation['resource_id']+'/retry', 'POST')
        wait_job(c, retried['async_job_id'])
        outputs = api(c, '/creation-tasks/'+creation['resource_id']+'/outputs')
        assert len(outputs) == 1
        checks.append('model_timeout_retry_single_output')
        save('faults', {'passed':True,'checks':checks,'external_services':'deterministic adapters; model timeout injected','real_publish_executed':False})
    finally:
        compose('start', 'redis', 'worker', 'rustfs')
        try:
            api(c, '/__acceptance__/faults', 'POST', {})
        finally:
            c.close()


if __name__ == '__main__':
    main()
