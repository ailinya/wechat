"""Opt-in live acceptance on TEST_DATABASE_URL, which is reset by the test fixture."""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from app.credentials import resolve_setting
from app.services import async_job_service
from app.services.creation_worker import creation_job
from app.services.material_embedding_service import material_embedding_job


@pytest.mark.skipif(os.environ.get('CREATION_LIVE_TEST') != '1', reason='explicit live acceptance only')
def test_live_material_search_to_pending_draft(client, db_engine):
    started = time.monotonic()
    assert client.post('/api/v1/auth/login', json={'account': 'admin', 'password': 'correct-password'}).status_code == 200
    headers = {'X-CSRF-Token': client.cookies.get('wetchat_csrf')}
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name,credential_ref,timeout_seconds,max_output_tokens) VALUES ('live-generation','openai-compatible','generation','https://example.test','environment','OPENAI_API_KEY',90,2500) RETURNING id")).scalar_one()
    response = client.post('/api/v1/materials', headers=headers, json={'title': '合成样例：电池回收', 'content_markdown': '星河实验室于2026年11月发布电池回收试点。试点每月处理100吨废旧电池，并回收其中的锂和镍。该数字为测试样例。'})
    assert response.status_code == 201, response.text
    material = response.json()
    with db_engine.begin() as conn:
        job_id = conn.execute(text("SELECT async_job_id FROM material_embedding_runs WHERE material_revision_id=:id"), {'id': material['current_revision_id']}).scalar_one()
        assert async_job_service.claim_job(conn, str(job_id))
        job = async_job_service.get_job(conn, str(job_id))
    material_embedding_job(db_engine, job)
    with db_engine.begin() as conn:
        async_job_service.finish_job(conn, str(job_id), 'succeeded')
    search = client.post('/api/v1/materials/search', headers=headers, json={'query': '电池回收试点', 'scope': 'all', 'keyword_mode': 'hybrid'})
    assert search.status_code == 200, search.text
    found = search.json()
    assert found['mode'] == 'hybrid' and not found['degraded']
    selected = next(item for item in found['items'] if item['material_id'] == material['id'])
    request = client.post('/api/v1/creation-tasks', headers=headers, json={'mode': 'topic', 'topic': '电池回收试点', 'model_config_id': str(model), 'min_words': 100, 'max_words': 300, 'materials': [{'material_id': selected['material_id'], 'revision_id': selected['matched_revision_id']}]})
    assert request.status_code == 202 and request.json()['status'] == 'pending', request.text
    task = request.json()
    with db_engine.begin() as conn:
        assert async_job_service.claim_job(conn, task['async_job_id'])
        job = async_job_service.get_job(conn, task['async_job_id'])
    creation_job(db_engine, job)
    with db_engine.begin() as conn:
        async_job_service.finish_job(conn, task['async_job_id'], 'succeeded')
    outputs = client.get(f"/api/v1/creation-tasks/{task['resource_id']}/outputs").json()
    assert len(outputs) == 1
    article = client.get(f"/api/v1/articles/{outputs[0]['article_id']}").json()
    assert article['status'] == 'pending_review' and article['materials'][0]['material_revision_id'] == selected['matched_revision_id']
    evidence = {'checked_at': datetime.now(timezone.utc).isoformat(), 'sample': 'synthetic', 'embedding_model': resolve_setting('EMBEDDING_MODEL'), 'embedding_dimension': resolve_setting('EMBEDDING_DIMENSION'), 'text_model': resolve_setting('MODEL_NAME'), 'search_mode': found['mode'], 'search_degraded': found['degraded'], 'search_score': selected['relevance_score'], 'article_status': article['status'], 'citation_count': len(article['materials']), 'elapsed_seconds': round(time.monotonic() - started, 2), 'passed': True}
    evidence_path = os.environ.get('CREATION_LIVE_EVIDENCE')
    if evidence_path:
        Path(evidence_path).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
