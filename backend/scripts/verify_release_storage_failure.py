"""Stop real RustFS during draft preparation; recover without duplicate remote writes."""
import json
from uuid import uuid4
from release_support import ROOT, api, approve, client, compose, save, wait_job, wait_until


def main():
    c = client()
    record = json.loads((ROOT/'.acceptance/workflow.json').read_text())
    created = api(c, '/articles','POST',{'title':'[fixture] 存储故障 '+uuid4().hex[:8],'body_markdown':'对象存储故障恢复合成正文。','cover_object_id':record['cover_id']})
    approve(c,created['article_id'],created['current_revision_id'])
    before = api(c,'/__acceptance__/state')['draft_writes']
    try:
        compose('stop','rustfs')
        delivery = api(c,'/wechat-draft-deliveries','POST',{'article_revision_id':created['current_revision_id'],'account_id':record['account_id'],'confirm_sync':True})
        wait_job(c,delivery['async_job_id'],expected='failed')
        failed = api(c,'/wechat-draft-deliveries/'+delivery['id'])
        assert failed['status'] == 'failed'
        assert failed['error_code'] == 'storage_unavailable', failed['error_code']
        assert api(c,'/__acceptance__/state')['draft_writes'] == before
    finally:
        compose('start','rustfs')
    wait_until(lambda:c.get('/ready').status_code==200)
    retried = api(c,'/wechat-draft-deliveries/'+delivery['id']+'/retry','POST')
    wait_job(c,retried['async_job_id'])
    assert api(c,'/wechat-draft-deliveries/'+delivery['id'])['status'] == 'awaiting_manual_publish'
    assert api(c,'/__acceptance__/state')['draft_writes'] == before+1
    attempts = api(c,'/wechat-draft-deliveries/'+delivery['id']+'/attempts')
    assert len(attempts)==2
    save('storage-preparation-failure',{'passed':True,'checks':['actual_rustfs_stop','preparation_failure_preserved','no_remote_write_before_storage_recovers','explicit_retry_single_remote_write','two_attempts_retained'],'external_wechat':'deterministic adapter','real_publish_executed':False})


if __name__ == '__main__':
    main()
