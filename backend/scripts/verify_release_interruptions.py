"""Hard worker loss, unknown external result and optional database outage drills."""
import argparse
import json
import subprocess
import time
from uuid import uuid4
from sqlalchemy import text
from release_support import ROOT, api, approve, client, compose, engine, save, wait_job, wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-only', action='store_true')
    args = parser.parse_args()
    c = client()
    if args.database_only:
        compose('stop','worker')
        queued = api(c,'/__acceptance__/health-job','POST')
        def dispatched():
            with engine().connect() as conn:
                return conn.execute(text("SELECT status FROM outbox_events WHERE payload->'kwargs'->>'job_id'=:id"),{'id':queued['async_job_id']}).scalar_one() == 'dispatched'
        wait_until(dispatched)
        try:
            compose('stop', 'postgres')
            # `compose start worker` also starts its dependencies, including the
            # database under test. Start this isolated container directly.
            subprocess.run(['docker','start','wetchat-acceptance-worker-1'], check=True, capture_output=True)
            response = c.get('/ready')
            assert response.status_code == 503 and not response.json()['checks']['database']['ready'], f'Unexpected readiness response: {response.status_code} {response.text[:300]}'
            assert c.get('/health').status_code == 200
            time.sleep(10)
        finally:
            compose('start', 'postgres')
            compose('start','worker')
        wait_until(lambda:c.get('/ready').status_code == 200)
        with engine().begin() as conn:
            conn.execute(text("UPDATE async_jobs SET updated_at=now()-interval '1 day' WHERE id=:id AND status='pending'"),{'id':queued['async_job_id']})
        recovery = api(c,'/settings/runtime/recover-stale','POST')
        wait_job(c,queued['async_job_id'])
        assert api(c,'/async-jobs/'+queued['async_job_id'])['attempts'] == 1
        job = api(c, '/__acceptance__/health-job', 'POST')
        wait_job(c, job['async_job_id'])
        save('database-outage', {'passed':True,'checks':['database_outage_readiness','liveness_independent','connection_pool_recovers','preexisting_dispatched_job_recovers_same_id_single_claim','post_recovery_job_succeeds'],'recovered_pending':recovery['recovered_pending'],'stale_clock_simulated_for_pending_recovery':True})
        return
    record = json.loads((ROOT/'.acceptance/workflow.json').read_text())
    material = api(c, '/materials/'+record['material_id'])
    try:
        api(c, '/__acceptance__/faults', 'POST', {'slow_model_seconds':30})
        creation = api(c, '/creation-tasks', 'POST', {'mode':'topic','topic':'[fixture] worker loss '+uuid4().hex,'model_config_id':record['model_id'],'min_words':100,'max_words':800,'materials':[{'material_id':material['id'],'revision_id':material['current_revision_id']}]})
        wait_until(lambda:api(c, '/async-jobs/'+creation['async_job_id']), lambda row:row['status']=='running')
        compose('kill', '-s', 'SIGKILL', 'worker')
        # Simulate elapsed stale timeout, preserving actual worker hard termination.
        with engine().begin() as conn:
            conn.execute(text("UPDATE async_jobs SET updated_at=now()-interval '1 day' WHERE id=:id"), {'id':creation['async_job_id']})
        api(c, '/settings/runtime/recover-stale', 'POST')
        assert api(c, '/async-jobs/'+creation['async_job_id'])['status'] == 'failed'
        assert api(c, '/creation-tasks/'+creation['resource_id']+'/outputs') == []
        api(c, '/__acceptance__/faults', 'POST', {})
        compose('start', 'worker')
        retry = api(c, '/creation-tasks/'+creation['resource_id']+'/retry', 'POST')
        wait_job(c, retry['async_job_id'])
        outputs = api(c, '/creation-tasks/'+creation['resource_id']+'/outputs')
        assert len(outputs) == 1
        article = api(c, '/articles/'+outputs[0]['article_id'])
        edited = api(c, '/articles/'+outputs[0]['article_id']+'/revisions', 'POST', {'base_revision_id':article['revision_id'],'title':'[fixture] unknown across restart','body_markdown':article['body_markdown'],'cover_object_id':record['cover_id'],'materials':[{'material_id':material['id'],'material_revision_id':material['current_revision_id']}]})
        approve(c, outputs[0]['article_id'], edited['current_revision_id'])
        before = api(c, '/__acceptance__/state')['draft_writes']
        api(c, '/__acceptance__/faults', 'POST', {'wechat_timeout_once':True})
        delivery = api(c, '/wechat-draft-deliveries', 'POST', {'article_revision_id':edited['current_revision_id'],'account_id':record['account_id'],'confirm_sync':True})
        wait_job(c, delivery['async_job_id'], expected='failed')
        compose('restart', 'worker')
        assert api(c, '/wechat-draft-deliveries/'+delivery['id'])['status'] == 'unknown'
        api(c, '/wechat-draft-deliveries/'+delivery['id']+'/retry', 'POST', expected=(409,))
        restored = api(c, '/wechat-draft-deliveries/'+delivery['id']+'/reconcile', 'POST', {'outcome':'query'})
        assert restored['status'] == 'awaiting_manual_publish'
        assert api(c, '/__acceptance__/state')['draft_writes'] == before+1
        save('worker-interruption', {'passed':True,'checks':['hard_kill_running_worker','stale_timeout_clock_simulated','explicit_recovery_and_retry','single_article_output','unknown_draft_survives_worker_restart','query_only_reconcile_no_duplicate'],'external_services':'deterministic model and WeChat adapters','real_publish_executed':False})
    finally:
        compose('start', 'worker')
        api(c, '/__acceptance__/faults', 'POST', {})


if __name__ == '__main__':
    main()
