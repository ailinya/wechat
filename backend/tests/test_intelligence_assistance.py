"""Phase 10 isolation, provenance and human-control integration tests."""
import pytest
from alembic import command
from alembic.config import Config
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.services import assistance_service
from app.services import assistance_analytics_service
from app.schemas.assistance import EnhancedSearchRequest


def make_material(conn, title):
    material = conn.execute(text('INSERT INTO materials(title) VALUES (:title) RETURNING id'), {'title': title}).scalar_one()
    revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:material,1,:body) RETURNING id"), {'material': material, 'body': title}).scalar_one()
    conn.execute(text('UPDATE materials SET current_revision_id=:revision WHERE id=:material'), {'revision': revision, 'material': material})
    return material, revision


def test_assistance_schema_preserves_manual_links_and_revision_provenance(db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        a, ar = make_material(conn, '素材甲')
        b, br = make_material(conn, '素材乙')
        conn.execute(text("INSERT INTO material_relations(source_material_id,target_material_id,relation_type) VALUES (:a,:b,'related_to')"), {'a': a, 'b': b})
        run = conn.execute(text("INSERT INTO assistance_runs(kind,status,created_by,algorithm_version) VALUES ('relation','succeeded',:user,'test/1') RETURNING id"), {'user': user}).scalar_one()
        conn.execute(text('INSERT INTO assistance_run_materials(run_id,material_id,revision_id) VALUES (:run,:a,:ar)'), {'run': run, 'a': a, 'ar': ar})
        suggestion = conn.execute(text("INSERT INTO assistance_relations(run_id,source_material_id,source_revision_id,target_material_id,target_revision_id,algorithm_version,score,evidence) VALUES (:run,:a,:ar,:b,:br,'test/1',0.5,'{}') RETURNING id"), {'run': run, 'a': a, 'ar': ar, 'b': b, 'br': br}).scalar_one()
        conn.execute(text('UPDATE assistance_relations SET ignored_by=:user,ignored_at=now() WHERE id=:id'), {'user': user, 'id': suggestion})
        assert conn.execute(text('SELECT count(*) FROM material_relations')).scalar_one() == 1
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(text('INSERT INTO assistance_run_materials(run_id,material_id,revision_id) VALUES (:run,:b,:ar)'), {'run': run, 'b': b, 'ar': ar})


def test_assistance_migration_round_trip_preserves_existing_materials(db_engine, monkeypatch):
    with db_engine.begin() as conn:
        a, _ = make_material(conn, '保留原有数据')
    monkeypatch.setenv('DATABASE_URL', db_engine.url.render_as_string(hide_password=False))
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(cfg, '0024_material_counts')
    command.upgrade(cfg, 'head')
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT title FROM materials WHERE id=:id'), {'id': a}).scalar_one() == '保留原有数据'
        assert conn.execute(text('SELECT active_count FROM material_counts')).scalar_one() == 1


def test_topics_validate_evidence_detect_duplicates_and_reuse(db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        material, revision = make_material(conn, '动力电池回收')
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
        article = conn.execute(text("INSERT INTO articles(origin_type,status) VALUES ('manual','pending_review') RETURNING id")).scalar_one()
        article_rev = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:article,1,'电池回收进展','正文') RETURNING id"), {'article': article}).scalar_one()
        conn.execute(text('UPDATE articles SET current_revision_id=:revision WHERE id=:article'), {'article': article, 'revision': article_rev})

    class Client:
        calls = 0
        def complete_json(self, *_):
            self.calls += 1
            item = {'title': '电池回收进展', 'rationale': '素材有相关信息', 'evidence': [{'material_id': str(material), 'quote': '电池回收'}]}
            return {'content': {'candidates': [item, item]}, 'usage': {'total_tokens': 123}}

    client = Client()
    result = assistance_service.recommend_topics(db_engine, user, [material], model, client)
    repeated = assistance_service.recommend_topics(db_engine, user, [material], model, client)
    assert client.calls == 1 and repeated['id'] == result['id']
    assert result['status'] == 'succeeded' and result['usage']['total_tokens'] == 123
    candidate, = result['result']['candidates']
    assert candidate['evidence'][0]['revision_id'] == str(revision)
    assert candidate['duplicate_articles'][0]['id'] == str(article)
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM articles')).scalar_one() == 1
        assert conn.execute(text('SELECT status FROM articles WHERE id=:id'), {'id': article}).scalar_one() == 'pending_review'


def test_topics_reject_invented_evidence(db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        material, _ = make_material(conn, '已知素材')
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
    class Client:
        def complete_json(self, *_):
            return {'content': {'candidates': [{'title': '建议', 'rationale': '依据', 'evidence': [{'material_id': str(material), 'quote': '虚构证据'}]}]}}
    result = assistance_service.recommend_topics(db_engine, user, [material], model, Client())
    assert result['status'] == 'failed' and result['error_code'] == 'invalid_output'
    assert result['result'] == {}


def test_topic_endpoint_enforces_csrf_and_current_permissions(client, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        material, _ = make_material(conn, '固定素材正文')
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
    class Client:
        def __init__(self, **_): pass
        def complete_json(self, *_):
            return {'content': {'candidates': [{'title': '主题', 'rationale': '素材依据', 'evidence': [{'material_id': str(material), 'quote': '固定素材'}]}]}}
    monkeypatch.setattr(assistance_service, 'ModelClient', Client)
    assert client.post('/api/v1/auth/login', json={'account': 'admin', 'password': 'correct-password'}).status_code == 200
    payload = {'material_ids': [str(material)], 'model_config_id': str(model)}
    assert client.post('/api/v1/assistance/topics', json=payload).status_code == 403
    headers = {'X-CSRF-Token': client.cookies['wetchat_csrf']}
    response = client.post('/api/v1/assistance/topics', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    run_id = response.json()['id']
    assert client.get(f'/api/v1/assistance/runs/{run_id}').status_code == 200
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE name='admin') AND permission_id=(SELECT id FROM permissions WHERE code='article:read')"))
    assert client.get(f'/api/v1/assistance/runs/{run_id}').status_code == 403


def test_relation_ignore_and_expanded_search_preserve_revisions(db_engine, monkeypatch):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        source, source_rev = make_material(conn, '动力电池')
        target, target_rev = make_material(conn, '历史回收资料')
        conn.execute(text("UPDATE materials SET usage_status='used' WHERE id=:id"), {'id': target})
        conn.execute(text("INSERT INTO material_relations(source_material_id,target_material_id,relation_type) VALUES (:source,:target,'related_to')"), {'source': source, 'target': target})
        def item(mid, rid, title, status='pending_review'):
            return {'material_id': mid, 'matched_revision_id': rid, 'title': title, 'snippet': title, 'source': {'type': 'manual', 'title': None, 'url': None, 'attachment_id': None}, 'published_at': None, 'keyword_score': 1.0, 'semantic_score': None, 'relevance_score': 0.8, 'score_explanation': 'fixture', 'usage_status': status}
        def result(items):
            return {'items': items, 'mode': 'keyword_only', 'degraded': True, 'degradation_reason': 'fixture'}
        monkeypatch.setattr(assistance_service.material_search_service, 'search', lambda *_args, **_kwargs: result([item(source, source_rev, '动力电池'), item(target, target_rev, '历史回收资料', 'used')]))
        created = assistance_service.suggest_relations(conn, user, source)
        suggestion, = created['items']
        assert suggestion['target_revision_id'] == target_rev and suggestion['is_current']
        monkeypatch.setattr(assistance_service.material_search_service, 'search', lambda *_args, **_kwargs: result([item(source, source_rev, '动力电池')]))
        expanded = assistance_service.enhanced_search(conn, user, EnhancedSearchRequest(query='电池', scope='all', keyword_mode='keyword_only', expand_relations=True))
        assert {str(row['material_id']) for row in expanded['items']} == {str(source), str(target)}
        assert assistance_service.run_detail(conn, expanded['run_id'], user)['input']['query'] == '电池'
        current = assistance_service.enhanced_search(conn, user, EnhancedSearchRequest(query='电池', scope='current', keyword_mode='keyword_only', expand_relations=True))
        assert [row['material_id'] for row in current['items']] == [source]
        newer = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:material,2,'新版本') RETURNING id"), {'material': target}).scalar_one()
        conn.execute(text('UPDATE materials SET current_revision_id=:revision WHERE id=:material'), {'revision': newer, 'material': target})
        stale = assistance_service.enhanced_search(conn, user, EnhancedSearchRequest(query='电池', scope='all', keyword_mode='keyword_only', expand_relations=True))
        assert [row['material_id'] for row in stale['items']] == [source]
        assert not assistance_service.list_relations(conn, source)[0]['is_current']
        conn.execute(text('UPDATE materials SET current_revision_id=:revision WHERE id=:material'), {'revision': target_rev, 'material': target})
        assistance_service.ignore_relation(conn, suggestion['id'], user)
        ignored = assistance_service.enhanced_search(conn, user, EnhancedSearchRequest(query='电池', scope='all', keyword_mode='keyword_only', expand_relations=True))
        assert [row['material_id'] for row in ignored['items']] == [source]
        monkeypatch.setattr(assistance_service.material_search_service, 'search', lambda *_args, **_kwargs: result([item(target, target_rev, '历史回收资料', 'used')]))
        regenerated = assistance_service.suggest_relations(conn, user, source)
        assert len(regenerated['items']) == 1 and regenerated['items'][0]['ignored_at'] is not None
        assert conn.execute(text('SELECT count(*) FROM material_relations')).scalar_one() == 1


def test_quality_advice_cannot_change_review_and_rejects_invented_quotes(db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        material, revision = make_material(conn, '来源称产量达到100吨')
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
        article = conn.execute(text("INSERT INTO articles(origin_type,status) VALUES ('manual','pending_review') RETURNING id")).scalar_one()
        article_rev = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:article,1,'标题','报道产量为100吨') RETURNING id"), {'article': article}).scalar_one()
        conn.execute(text('UPDATE articles SET current_revision_id=:revision WHERE id=:article'), {'article': article, 'revision': article_rev})
        conn.execute(text('INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:a,:m,:r,1)'), {'a': article_rev, 'm': material, 'r': revision})
    class Client:
        def __init__(self, quote): self.quote = quote
        def complete_json(self, *_):
            return {'content': {'suggestions': [{'category': 'facts', 'advice': '核对数字', 'limitation': '未外部核实', 'evidence': {'article_quote': '100吨', 'material_id': str(material), 'source_quote': self.quote}}]}, 'usage': {'total_tokens': 10}}
    good = assistance_service.assess_quality(db_engine, user, article, article_rev, model, Client('产量达到100吨'))
    bad = assistance_service.assess_quality(db_engine, user, article, article_rev, model, Client('虚构证据'))
    assert good['status'] == 'succeeded'
    assert good['result']['suggestions'][0]['evidence']['revision_id'] == str(revision)
    assert bad['status'] == 'failed' and bad['result'] == {}
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM articles WHERE id=:id'), {'id': article}).scalar_one() == 'pending_review'
        assert conn.execute(text('SELECT count(*) FROM reviews')).scalar_one() == 0
        assert conn.execute(text('SELECT count(*) FROM publish_orders')).scalar_one() == 0


def test_quality_model_failure_does_not_block_editing(client, db_engine, monkeypatch):
    from app.adapters.model_client import ModelError
    class BrokenClient:
        def __init__(self, **_): pass
        def complete_json(self, *_): raise ModelError('model_unreachable', '模型不可用')
    monkeypatch.setattr(assistance_service, 'ModelClient', BrokenClient)
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
    assert client.post('/api/v1/auth/login', json={'account': 'admin', 'password': 'correct-password'}).status_code == 200
    headers = {'X-CSRF-Token': client.cookies['wetchat_csrf']}
    article = client.post('/api/v1/articles', headers=headers, json={'title': '测试', 'body_markdown': '原始正文'}).json()
    aid, rid = article['article_id'], article['current_revision_id']
    result = client.post(f'/api/v1/assistance/articles/{aid}/quality', headers=headers, json={'revision_id': rid, 'model_config_id': str(model)})
    assert result.status_code == 200 and result.json()['status'] == 'failed'
    saved = client.post(f'/api/v1/articles/{aid}/revisions', headers=headers, json={'base_revision_id': rid, 'title': '修改标题', 'body_markdown': '修改正文'})
    assert saved.status_code == 201


def test_reuse_report_separates_articles_revisions_orders_attempts_and_unknown_metrics(db_engine):
    with db_engine.begin() as conn:
        material, material_rev = make_material(conn, '可复用素材')
        accounts = [conn.execute(text("INSERT INTO wechat_accounts(name,app_id,account_type,secret_encrypted,status) VALUES (:name,:app,'service','fixture','active') RETURNING id"), {'name': name, 'app': app}).scalar_one() for name, app in [('账号一','wx-fixture-1'),('账号二','wx-fixture-2')]]
        articles, revisions = [], []
        for n, versions in [(1, 2), (2, 1)]:
            article = conn.execute(text("INSERT INTO articles(origin_type,status) VALUES ('manual','pending_review') RETURNING id")).scalar_one()
            articles.append(article)
            for version in range(1, versions+1):
                revision = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:a,:v,'文章','正文') RETURNING id"), {'a': article, 'v': version}).scalar_one()
                revisions.append(revision)
                conn.execute(text('INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:a,:m,:r,1)'), {'a': revision, 'm': material, 'r': material_rev})
            conn.execute(text('UPDATE articles SET current_revision_id=:r WHERE id=:a'), {'r': revision, 'a': article})
        for index, account in enumerate(accounts):
            order = conn.execute(text("INSERT INTO publish_orders(article_id,article_revision_id,account_id,mode) VALUES (:article,:revision,:account,'immediate') RETURNING id"), {'article': articles[0], 'revision': revisions[1], 'account': account}).scalar_one()
            for number in range(1, 3 if index == 0 else 2):
                conn.execute(text("INSERT INTO publish_attempts(order_id,attempt_no,status) VALUES (:order,:n,'failed')"), {'order': order, 'n': number})
        conn.execute(text("INSERT INTO account_article_metrics(account_id,article_id,external_article_id,metric_date,availability,reads) VALUES (:account,:article,'external',current_date,'partial',42)"), {'account': accounts[0], 'article': articles[0]})
        report = assistance_analytics_service.reuse_report(conn)
        item, = report['items']
        assert (item['articles'], item['article_revisions']) == (2, 3)
        by_id = {account['id']: account for account in item['accounts']}
        first, second = (by_id[account] for account in accounts)
        assert (first['publish_orders'], first['publish_attempts']) == (1, 2)
        assert (second['publish_orders'], second['publish_attempts']) == (1, 1)
        assert first['metrics_status'] == 'partial' and first['metric_snapshots'][0]['reads'] == 42
        assert second['metrics_status'] == 'unavailable' and second['metric_snapshots'] == []


def test_reuse_report_requires_account_permission(client, db_engine):
    assert client.post('/api/v1/auth/login', json={'account': 'admin', 'password': 'correct-password'}).status_code == 200
    assert client.get('/api/v1/assistance/analytics/reuse').status_code == 200
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM role_permissions WHERE role_id=(SELECT id FROM roles WHERE name='admin') AND permission_id=(SELECT id FROM permissions WHERE code='account:read')"))
    assert client.get('/api/v1/assistance/analytics/reuse').status_code == 403


def test_search_degrades_when_embedding_config_version_changes(db_engine, monkeypatch):
    from app.schemas.materials import MaterialSearchIn
    from app.services import material_search_service
    monkeypatch.setattr(material_search_service, '_active_config', lambda _conn: ({'id': 'config', 'config_version': 2}, 'model', 'endpoint', 1024))
    def unexpected_embed(*_args, **_kwargs):
        raise AssertionError('stale embedding must not be used')
    with db_engine.begin() as conn:
        result = material_search_service.search(conn, MaterialSearchIn(query='测试', keyword_mode='hybrid'), embed=unexpected_embed, expected_config={'id': 'config', 'config_version': 1})
    assert result['mode'] == 'keyword_only'
    assert result['degradation_reason'] == 'embedding_configuration_changed'


def test_blank_model_advice_is_rejected_without_business_side_effects(db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        material, _ = make_material(conn, '素材内容')
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('fixture','test','analysis','https://example.invalid','fixture') RETURNING id")).scalar_one()
        article = conn.execute(text("INSERT INTO articles(origin_type,status) VALUES ('manual','pending_review') RETURNING id")).scalar_one()
        revision = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:article,1,'标题','文章内容') RETURNING id"), {'article': article}).scalar_one()
        conn.execute(text('UPDATE articles SET current_revision_id=:revision WHERE id=:article'), {'revision': revision, 'article': article})
    class TopicClient:
        def complete_json(self, *_):
            return {'content': {'candidates': [{'title': '主题', 'rationale': '  ', 'evidence': [{'material_id': str(material), 'quote': '素材内容'}]}]}, 'usage': {'total_tokens': 12}}
    class QualityClient:
        def complete_json(self, *_):
            return {'content': {'suggestions': [{'category': 'structure', 'advice': ' ', 'limitation': '仅供参考', 'evidence': {'article_quote': '文章内容'}}]}, 'usage': {'total_tokens': 9}}
    topic = assistance_service.recommend_topics(db_engine, user, [material], model, TopicClient())
    quality = assistance_service.assess_quality(db_engine, user, article, revision, model, QualityClient())
    assert topic['status'] == quality['status'] == 'failed'
    assert topic['error_code'] == quality['error_code'] == 'invalid_output'
    assert topic['usage']['total_tokens'] == 12 and quality['usage']['total_tokens'] == 9
    with db_engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM articles WHERE id=:id'), {'id': article}).scalar_one() == 'pending_review'
        assert conn.execute(text('SELECT count(*) FROM publish_orders')).scalar_one() == 0
