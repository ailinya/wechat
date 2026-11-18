"""Local test-database API -> outbox -> Redis -> Worker -> real model check."""
import json
import time
from datetime import datetime,timezone
from pathlib import Path
import httpx


def verify():
    with httpx.Client(base_url='http://127.0.0.1:8013',trust_env=False,timeout=90) as client:
        response=client.post('/api/v1/auth/login',json={'account':'admin','password':'correct-password'})
        response.raise_for_status()
        headers={'X-CSRF-Token':client.cookies.get('wetchat_csrf')}
        models=client.get('/api/v1/model-configs?page_size=100').json()['items']
        model=next(row for row in models if row['name']=='DeepSeek 素材分析' and row['enabled'])
        connection=client.post(f"/api/v1/model-configs/{model['id']}/test",headers=headers)
        connection.raise_for_status()
        if not connection.json()['reachable']:
            raise RuntimeError(connection.json()['error'])
        material=client.post('/api/v1/materials',headers=headers,json={
            'title':'DeepSeek 接入验收样例（测试数据）',
            'content_markdown':'以下为固定测试样例，非真实报道。星河公司于2026年11月17日发布了新型传感器。该传感器的采样率为每秒200次，比上一代提高25%。公司表示将于12月开始交付。'})
        material.raise_for_status()
        material_id=material.json()['id']
        accepted=client.post(f'/api/v1/materials/{material_id}/analysis',headers=headers,json={'model_config_id':model['id']})
        accepted.raise_for_status()
        job_id=accepted.json()['async_job_id']
        for _ in range(45):
            job=client.get(f'/api/v1/async-jobs/{job_id}').json()
            if job['status'] in ('succeeded','failed','cancelled'):
                break
            time.sleep(1)
        records=client.get(f'/api/v1/collection/analysis?material_id={material_id}').json()['items']
        evidence={'checked_at':datetime.now(timezone.utc).isoformat(),'model_name':model['model_name'],'connection_test':connection.json(),
            'material_id':material_id,'job_id':job_id,'job_status':job['status'],'analysis_statuses':[row['status'] for row in records],
            'analysis_ids':[row['id'] for row in records],'usage':[row['usage'] for row in records],
            'summary':[row['suggestions']['summary'] for row in records if row['suggestions']],
            'errors':[row['error'] for row in records if row['error']]}
        evidence['passed']=job['status']=='succeeded' and any(row['status']=='succeeded' and not row['stale'] for row in records)
        return evidence


if __name__=='__main__':
    evidence=verify()
    output=Path(__file__).resolve().parents[2]/'doc/development/analysis-worker-live-evidence.json'
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False,indent=2))
