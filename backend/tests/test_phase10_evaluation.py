"""Offline fixed-fixture comparison; expected labels are not human annotations."""
import json
import os
import time
from pathlib import Path

from sqlalchemy import text

from app.schemas.assistance import EnhancedSearchRequest
from app.schemas.materials import MaterialSearchIn
from app.services import assistance_service, material_search_service


def test_fixed_phase4_queries_compare_baseline_and_relation_expansion(db_engine):
    samples = [
        ('sensor', '传感器新品发布', '星河公司发布新型传感器，采样率每秒 200 次，比上一代提高 25%，计划于 12 月开始交付。'),
        ('battery', '新能源汽车电池回收', '某企业建设动力电池回收产线，采用梯次利用和材料再生工艺。'),
        ('weather', '城市气象服务升级', '气象部门升级短临预报系统，提高强降雨预警和城市内涝监测能力。'),
        ('history', '旧光学器件资料', '历史资料记述早期光学器件的一次升级。'),
    ]
    cases = [
        ('传感器采样率提升', {'sensor', 'history'}),
        ('动力电池循环利用', {'battery'}),
        ('暴雨预警和内涝', {'weather'}),
        ('古典诗词格律', set()),
    ]
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        ids, revisions = {}, {}
        for key, title, body in samples:
            mid = conn.execute(text("INSERT INTO materials(title,usage_status) VALUES (:title,'ready_to_use') RETURNING id"), {'title': title}).scalar_one()
            rid = conn.execute(text('INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:m,1,:body) RETURNING id'), {'m': mid, 'body': body}).scalar_one()
            conn.execute(text('UPDATE materials SET current_revision_id=:r WHERE id=:m'), {'r': rid, 'm': mid})
            ids[key], revisions[key] = mid, rid
        run = conn.execute(text("INSERT INTO assistance_runs(kind,status,created_by,algorithm_version) VALUES ('relation','succeeded',:user,'relations/1') RETURNING id"), {'user': user}).scalar_one()
        conn.execute(text("INSERT INTO assistance_relations(run_id,source_material_id,source_revision_id,target_material_id,target_revision_id,algorithm_version,score,evidence) VALUES (:run,:source,:sr,:target,:tr,'relations/1',0.9,'{}')"), {'run': run, 'source': ids['sensor'], 'sr': revisions['sensor'], 'target': ids['history'], 'tr': revisions['history']})
        reverse = {str(value): key for key, value in ids.items()}
        results = []
        for query, expected in cases:
            start = time.perf_counter()
            baseline = material_search_service.search(conn, MaterialSearchIn(query=query, scope='all', top_k=10, keyword_mode='keyword_only'))
            baseline_ms = (time.perf_counter()-start)*1000
            start = time.perf_counter()
            enhanced = assistance_service.enhanced_search(conn, user, EnhancedSearchRequest(query=query, scope='all', top_k=10, keyword_mode='keyword_only', expand_relations=True))
            enhanced_ms = (time.perf_counter()-start)*1000
            before = [reverse[str(item['material_id'])] for item in baseline['items']]
            after = [reverse[str(item['material_id'])] for item in enhanced['items']]
            def metrics(found):
                hits = len(set(found) & expected)
                return {'returned': found, 'recall': hits/len(expected) if expected else None, 'false_positives': sorted(set(found)-expected)}
            results.append({'query': query, 'expected': sorted(expected), 'baseline': {**metrics(before), 'elapsed_ms': round(baseline_ms, 2)}, 'enhanced': {**metrics(after), 'elapsed_ms': round(enhanced_ms, 2)}})
            if query == '传感器采样率提升':
                assert 'sensor' in before and 'history' not in before
                assert {'sensor', 'history'} <= set(after)
            if not expected:
                assert not before and not after
        evidence_path = os.getenv('PHASE10_EVIDENCE_PATH')
        if evidence_path:
            evidence = {'passed': True, 'labels': 'test author fixture expectations; not human annotations', 'scope': 'phase 4 four fixed queries plus one synthetic related historical material', 'mode': 'keyword_only, top_k=10, scope=all; no external model calls', 'cost': 'zero external calls for this fixture; production model costs depend on provider', 'limitation': 'Offline synthetic samples and pre-created association; not production recall or a human relevance assessment.', 'queries': results}
            Path(evidence_path).write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
