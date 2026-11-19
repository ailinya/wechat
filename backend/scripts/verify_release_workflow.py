"""Real deployed API/Worker/Redis/Postgres/RustFS; explicit external adapters."""
import json
from uuid import uuid4
from release_support import ROOT, api, client, wait_job, wait_until, approve, CHECKS, save


def main():
    c=client()
    suffix=uuid4().hex[:8]
    assert c.get('/ready').json()['status']=='ready'
    source=api(c,'/collection/sources','POST',{'name':'[fixture] release source '+suffix,'source_type':'web_page','page_kind':'article','base_url':'https://acceptance.example.test/article/'+suffix})
    task=api(c,'/collection/tasks','POST',{'name':'[fixture] release collect '+suffix,'source_ids':[source['id']],'max_fetch':1,'auto_materialize':True,'analysis_enabled':False})
    run=api(c,f"/collection/tasks/{task['id']}/run",'POST')
    wait_job(c,run['async_job_id'])
    results=api(c,'/collection/results?run_id='+run['resource_id'])
    assert results['total']==1,results
    item=results['items'][0]
    assert item['material_id'],'Collection result was not materialized'
    material=api(c,'/materials/'+item['material_id'])
    search=api(c,'/materials/search','POST',{'query':'电池回收','scope':'all','keyword_mode':'keyword_only'})
    candidate=next(row for row in search['items'] if row['material_id']==material['id'])
    assert candidate['source']['url'].startswith('https://acceptance.example.test/')
    model=api(c,'/model-configs','POST',{'name':'[fixture] release generation '+suffix,'provider':'openai-compatible','purpose':'generation','endpoint':'https://acceptance.example.test/v1','model_name':'acceptance-fixture'})
    creation=api(c,'/creation-tasks','POST',{'mode':'topic','topic':'电池回收进展 '+suffix,'model_config_id':model['id'],'min_words':100,'max_words':800,'batch_count':2,'materials':[{'material_id':material['id'],'revision_id':material['current_revision_id']}]})
    wait_job(c,creation['async_job_id'])
    outputs=api(c,'/creation-tasks/'+creation['resource_id']+'/outputs')
    assert len(outputs)==2
    article_id=outputs[0]['article_id']
    article=api(c,'/articles/'+article_id)
    original=article['revision_id']
    assert article['status']=='pending_review'
    api(c,f'/article-revisions/{original}/reviews','POST',{'action':'return','comment':'[fixture] 请补充合成测试说明'})
    cover=api(c,'/__acceptance__/cover','POST')
    def edit(base,title,body):
        return api(c,f'/articles/{article_id}/revisions','POST',{'base_revision_id':base,'title':title,'body_markdown':body,'summary':'仅供独立环境验收','cover_object_id':cover['id'],'materials':[{'material_id':material['id'],'material_revision_id':material['current_revision_id']}]})
    v2=edit(original,'[fixture] 已审核样例-'+suffix,article['body_markdown']+'\n\n合成测试说明。')
    approve(c,article_id,v2['current_revision_id'])
    v3=edit(v2['current_revision_id'],'[fixture] 草稿验收-'+suffix,article['body_markdown']+'\n\n这是第三版合成测试正文。')
    accounts=api(c,'/wechat-accounts?page_size=100')['items']
    account=next((a for a in accounts if a['app_id']=='wx0123456789abcdef'),None)
    if not account:
        account=api(c,'/wechat-accounts','POST',{'name':'[fixture] 个人订阅号','account_type':'subscription','app_id':'wx0123456789abcdef','app_secret':'acceptance-only-not-real-secret','publish_permission_confirmed':False})
    assert not account['capabilities']['publish']['available']
    api(c,'/wechat-draft-deliveries','POST',{'article_revision_id':v2['current_revision_id'],'account_id':account['id'],'confirm_sync':True},expected=(409,))
    approve(c,article_id,v3['current_revision_id'])
    before=api(c,'/__acceptance__/state')['draft_writes']
    api(c,'/__acceptance__/faults','POST',{'wechat_timeout_once':True})
    payload={'article_revision_id':v3['current_revision_id'],'account_id':account['id'],'confirm_sync':True,'note':'[fixture] 仅模拟微信外部适配'}
    headers={'Idempotency-Key':'release-'+suffix}
    delivery=api(c,'/wechat-draft-deliveries','POST',payload,headers=headers)
    replay=api(c,'/wechat-draft-deliveries','POST',payload,headers=headers)
    assert replay==delivery
    wait_job(c,delivery['async_job_id'],expected='failed')
    row=api(c,'/wechat-draft-deliveries/'+delivery['id'])
    assert row['status']=='unknown'
    api(c,'/wechat-draft-deliveries/'+delivery['id']+'/retry','POST',expected=(409,))
    row=api(c,'/wechat-draft-deliveries/'+delivery['id']+'/reconcile','POST',{'outcome':'query'})
    assert row['status']=='awaiting_manual_publish'
    assert api(c,'/articles/'+article_id)['status']=='approved'
    assert api(c,'/__acceptance__/state')['draft_writes']==before+1
    manual=api(c,'/wechat-draft-deliveries/'+delivery['id']+'/manual-published','POST',{'content_matches_revision':True,'article_url':'https://mp.weixin.qq.com/s/acceptance-fixture-'+suffix,'note':'[fixture] 模拟人工发布登记；未调用真实发布'})
    assert manual['publication_source']=='operator'
    report=api(c,'/analytics/publishing?account_id='+account['id'])
    assert report['summary']['denominator']==0
    references=api(c,'/materials/'+material['id']+'/articles')
    assert {row['article_id'] for row in outputs} <= {row['article_id'] for row in references}
    api(c,'/materials/'+material['id'],'PATCH',{'content_markdown':'后续进展合成样例。当前素材已产生新修订，文章仍引用原始采集快照。'})
    updated=api(c,'/articles/'+article_id)
    assert updated['materials'][0]['material_revision_id']==material['current_revision_id']
    assert '100吨' in updated['materials'][0]['content_markdown']
    record={'article_id':article_id,'revision_id':v3['current_revision_id'],'material_id':material['id'],'material_revision_id':material['current_revision_id'],'collection_run_id':run['resource_id'],'creation_task_id':creation['resource_id'],'model_id':model['id'],'account_id':account['id'],'cover_id':cover['id'],'delivery_id':delivery['id']}
    (ROOT/'.acceptance/workflow.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    save('workflow',{'passed':True,'checks':['collection','materialization','indexed_search','two_article_reuse','return_edit_reapprove','stale_approval_blocked','draft_timeout_reconcile_no_duplicate','operator_sourced_record','statistics','historical_citation_preserved'],'records':record,'infrastructure':'deployed containers; actual PostgreSQL/Redis/Worker/Beat/dispatcher/RustFS','external_services':'deterministic acceptance adapters','real_publish_executed':False,'manual_publication':'simulated evidence'})


if __name__=='__main__':
    main()
