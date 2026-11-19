"""Real PostgreSQL checks for immutable revisions and review races."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.schemas.articles import ArticleRevisionCreateIn
from app.services.article_service import save


CHECKS = {key: 'pass' for key in ('title', 'content', 'facts', 'citations', 'image_copyright', 'account_compliance', 'layout')}


def login(client, account='admin', password='correct-password'):
    assert client.post('/api/v1/auth/login', json={'account': account, 'password': password}).status_code == 200
    return {'X-CSRF-Token': client.cookies.get('wetchat_csrf')}


def draft(client, headers):
    response = client.post('/api/v1/articles', headers=headers, json={'title': '中文标题', 'body_markdown': '原始正文'})
    assert response.status_code == 201, response.text
    return response.json()


def test_review_migration_and_cross_article_constraint(db_engine, monkeypatch):
    from conftest import TEST_URL
    monkeypatch.setenv('DATABASE_URL', TEST_URL)
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    command.downgrade(cfg, '0016_articles')
    command.upgrade(cfg, 'head')
    with db_engine.begin() as conn:
        first = conn.execute(text("INSERT INTO articles(origin_type) VALUES ('manual') RETURNING id")).scalar_one()
        second = conn.execute(text("INSERT INTO articles(origin_type) VALUES ('manual') RETURNING id")).scalar_one()
        revision = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:id,1,'标题','正文') RETURNING id"), {'id': first}).scalar_one()
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            conn.execute(text('UPDATE articles SET current_revision_id=:revision WHERE id=:id'), {'revision': revision, 'id': second})
    with pytest.raises(IntegrityError):
        with db_engine.begin() as conn:
            reviewer = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
            conn.execute(text("INSERT INTO reviews(article_id,article_revision_id,action,checklist,reviewer_id) VALUES (:article,:revision,'approve','{}',:reviewer)"), {'article': second, 'revision': revision, 'reviewer': reviewer})


def test_return_edit_resubmit_approve_and_old_approval(client, db_engine):
    headers = login(client)
    item = draft(client, headers)
    aid, rid = item['article_id'], item['current_revision_id']
    submit = f'/api/v1/articles/{aid}/submit-review'
    assert client.post(submit, headers=headers, json={'base_revision_id': rid}).status_code == 200
    assert client.get('/api/v1/reviews/queue').json()['items'][0]['article_revision_id'] == rid
    review_url = f'/api/v1/article-revisions/{rid}/reviews'
    assert client.post(review_url, headers=headers, json={'action': 'return'}).status_code == 422
    returned = client.post(review_url, headers=headers, json={'action': 'return', 'comment': '补全事实来源'})
    assert returned.status_code == 201, returned.text
    new = client.post(f'/api/v1/articles/{aid}/revisions', headers=headers, json={'base_revision_id': rid, 'title': '修改标题', 'body_markdown': '修改正文'})
    assert new.status_code == 201, new.text
    nrid = new.json()['current_revision_id']
    assert client.post(review_url, headers=headers, json={'action': 'approve', 'checklist': CHECKS}).status_code == 409
    assert client.post(submit, headers=headers, json={'base_revision_id': nrid}).status_code == 200
    assert client.post(f'/api/v1/article-revisions/{nrid}/reviews', headers=headers, json={'action': 'approve', 'checklist': CHECKS}).status_code == 201
    assert client.post(f'/api/v1/article-revisions/{nrid}/reviews', headers=headers, json={'action': 'approve', 'checklist': CHECKS}).status_code == 409
    assert client.get(f'/api/v1/articles/{aid}').json()['status'] == 'approved'
    saved = client.post(f'/api/v1/articles/{aid}/revisions', headers=headers, json={'base_revision_id': nrid, 'title': '再次编辑', 'body_markdown': '新正文'})
    assert saved.status_code == 201 and saved.json()['status'] == 'draft'
    assert client.get(review_url).json()['items'][0]['comment'] == '补全事实来源'
    assert client.get(f'/api/v1/articles/{aid}/revisions/{rid}').json()['body_markdown'] == '原始正文'
    assert client.get(f'/api/v1/articles/{aid}/revisions').json()['total'] == 3
    assert client.get('/api/v1/articles?status=draft').json()['total'] == 1


def test_concurrent_saves_and_reference_rollback(client, db_engine):
    headers = login(client)
    item = draft(client, headers)
    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
    payload = ArticleRevisionCreateIn(base_revision_id=item['current_revision_id'], title='并发标题', body_markdown='并发正文')
    def run():
        from app.errors import ApiError
        try:
            with db_engine.begin() as conn:
                save(conn, payload, user, item['article_id'])
            return 201
        except ApiError as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == [201, 409]
    current = client.get(f"/api/v1/articles/{item['article_id']}").json()
    response = client.post(f"/api/v1/articles/{item['article_id']}/revisions", headers=headers, json={'base_revision_id': current['revision_id'], 'title': '无效引用', 'body_markdown': '正文', 'materials': [{'material_id': str(uuid4()), 'material_revision_id': str(uuid4())}]})
    assert response.status_code == 422
    assert client.get(f"/api/v1/articles/{item['article_id']}/revisions").json()['total'] == 2


def test_editor_cannot_review_or_skip_checklist(client, db_engine):
    headers = login(client, 'editor', 'editor-password')
    item = draft(client, headers)
    assert client.post(f"/api/v1/articles/{item['article_id']}/submit-review", headers=headers, json={'base_revision_id': item['current_revision_id']}).status_code == 200
    assert client.post(f"/api/v1/article-revisions/{item['current_revision_id']}/reviews", headers=headers, json={'action': 'approve', 'checklist': CHECKS}).status_code == 403
    assert client.get('/api/v1/reviews/queue').status_code == 403


def test_ai_suggestion_does_not_save_and_rechecks_revision(client, db_engine, monkeypatch):
    import json
    from app.adapters.model_client import ModelClient, ModelError
    headers = login(client)
    item = draft(client, headers)
    with db_engine.begin() as conn:
        model = conn.execute(text("INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('edit-fixture','fixture','generation','https://example.test','fixture') RETURNING id")).scalar_one()
    monkeypatch.setattr(ModelClient, 'complete_json', lambda *args: {'content': json.dumps({'suggestion': '建议正文'})})
    payload = {'base_revision_id': item['current_revision_id'], 'action': 'polish', 'model_config_id': str(model)}
    url = f"/api/v1/articles/{item['article_id']}/ai-actions"
    assert client.post(url, headers=headers, json=payload).json()['suggestion'] == '建议正文'
    assert client.get(f"/api/v1/articles/{item['article_id']}/revisions").json()['total'] == 1
    monkeypatch.setattr(ModelClient, 'complete_json', lambda *args: {'content': '{}'})
    assert client.post(url, headers=headers, json=payload).json()['error']['code'] == 'invalid_model_output'
    def timeout(*args):
        raise ModelError('model_unreachable', '模型超时')
    monkeypatch.setattr(ModelClient, 'complete_json', timeout)
    assert client.post(url, headers=headers, json=payload).status_code == 503
    def change_during_call(*args):
        with db_engine.begin() as conn:
            user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
            save(conn, ArticleRevisionCreateIn(base_revision_id=item['current_revision_id'], title='新版本', body_markdown='新正文'), user, item['article_id'])
        return {'content': json.dumps({'suggestion': '已过时建议'})}
    monkeypatch.setattr(ModelClient, 'complete_json', change_during_call)
    assert client.post(url, headers=headers, json=payload).status_code == 409


def test_preview_blocks_scripts_and_layout_injection(client, db_engine):
    from bs4 import BeautifulSoup
    headers = login(client)
    body = '# 中文标题\n\n<script>alert(1)</script>\n\n![x](javascript:alert(1))\n\n[恶意](data:text/html,boom)\n\n![图片](https://example.test/image.png)'
    result = client.post('/api/v1/articles/preview', headers=headers, json={'body_markdown': body, 'layout_config': {'font_size': 18, 'image_style': 'rounded'}})
    assert result.status_code == 200
    soup = BeautifulSoup(result.json()['html'], 'html.parser')
    assert not soup.find('script') and not soup.find('iframe')
    assert len(soup.find_all('img')) == 1
    assert 'border-radius:8px' in soup.img['style']
    assert not soup.find('a') and 'font-size:18px' in soup.section['style']
    bad = client.post('/api/v1/articles/preview', headers=headers, json={'body_markdown': '正文', 'layout_config': {'font_family': 'url(javascript:bad)'}})
    assert bad.status_code == 422


def test_review_racing_edit_never_approves_new_version(client, db_engine):
    from app.errors import ApiError
    from app.schemas.articles import ReviewCreateIn
    from app.services.article_service import review
    headers = login(client)
    item = draft(client, headers)
    aid, rid = item['article_id'], item['current_revision_id']
    client.post(f'/api/v1/articles/{aid}/submit-review', headers=headers, json={'base_revision_id': rid})
    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
    def run(action):
        try:
            with db_engine.begin() as conn:
                if action == 'save':
                    save(conn, ArticleRevisionCreateIn(base_revision_id=rid, title='新版', body_markdown='新事实'), user, aid)
                else:
                    review(conn, rid, ReviewCreateIn(action='approve', checklist=CHECKS), user)
            return 201
        except ApiError as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ('save', 'review')))
    assert results[0] == 201 and results[1] in (201, 409)
    current = client.get(f'/api/v1/articles/{aid}').json()
    assert current['status'] == 'draft' and current['version'] == 2


def test_historical_material_reference_and_image_access(client, db_engine, monkeypatch):
    from app.adapters import object_storage
    headers = login(client)
    with db_engine.begin() as conn:
        admin = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        editor = conn.execute(text("SELECT id FROM users WHERE account='editor'")).scalar_one()
        material = conn.execute(text("INSERT INTO materials(title) VALUES ('溯源素材') RETURNING id")).scalar_one()
        original = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'不可变的历史事实') RETURNING id"), {'id': material}).scalar_one()
        image = conn.execute(text("INSERT INTO stored_objects(bucket,object_key,size_bytes,content_type,sha256,uploader_id) VALUES ('test','phase06.png',100,'image/png',:hash,:user) RETURNING id"), {'hash': 'a'*64, 'user': admin}).scalar_one()
    content = {'title': '引用原文', 'body_markdown': f'![图片](/api/v1/files/{image}/image)', 'cover_object_id': str(image), 'materials': [{'material_id': str(material), 'material_revision_id': str(original)}]}
    result = client.post('/api/v1/articles', headers=headers, json=content)
    assert result.status_code == 201, result.text
    with db_engine.begin() as conn:
        newer = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,2,'更新后的不同事实') RETURNING id"), {'id': material}).scalar_one()
        conn.execute(text('UPDATE materials SET current_revision_id=:revision WHERE id=:id'), {'revision': newer, 'id': material})
        private_image = conn.execute(text("INSERT INTO stored_objects(bucket,object_key,size_bytes,content_type,sha256,uploader_id) VALUES ('test','private.png',100,'image/png',:hash,:user) RETURNING id"), {'hash': 'b'*64, 'user': editor}).scalar_one()
    detail = client.get(f"/api/v1/articles/{result.json()['article_id']}").json()
    assert detail['materials'][0]['content_markdown'] == '不可变的历史事实'
    assert detail['materials'][0]['material_revision_id'] == str(original)
    monkeypatch.setattr(object_storage, 'presigned_get', lambda *args: 'https://storage.example/image.png')
    assert client.get(f'/api/v1/files/{private_image}/image', follow_redirects=False).status_code == 403
    assert client.post('/api/v1/articles', headers=headers, json={**content, 'cover_object_id': str(private_image)}).status_code == 403
    login(client, 'editor', 'editor-password')
    assert client.get(f'/api/v1/files/{image}/image', follow_redirects=False).status_code == 307
