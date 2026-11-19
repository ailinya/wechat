from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app.api.deps import current_user, verify_csrf
from app.config import Settings
from app.main import create_app
from app.schemas.articles import ArticleRevisionCreateIn, ReviewCreateIn
from app.schemas.auth import CurrentUser, PermissionCode


def contract_client(permissions):
    app = create_app(Settings.model_validate({'APP_SECRET_KEY': 't' * 40, 'DATABASE_URL': 'postgresql+psycopg://example:example@localhost/test'}))
    user = CurrentUser(id=uuid4(), account='editor', name='编辑', status='active', permissions=permissions)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app)


def test_article_openapi_exposes_conflict_and_review_contract():
    with contract_client([PermissionCode.ARTICLE_READ, PermissionCode.ARTICLE_WRITE]) as client:
        schema = client.get('/openapi.json').json()
        operation = schema['paths']['/api/v1/articles/{article_id}/revisions']['post']
        assert {'201', '409', '422'} <= set(operation['responses'])
        conflict = operation['responses']['409']['content']['application/json']['examples']['revision_conflict']['value']
        assert conflict['error']['code'] == 'revision_conflict'
        assert 'base_revision_id' in schema['components']['schemas']['ArticleRevisionCreateIn']['required']
        review = schema['paths']['/api/v1/article-revisions/{revision_id}/reviews']
        assert {'get', 'post'} <= set(review)
        assert client.get('/api/v1/reviews/queue').status_code == 403


def test_save_and_review_validation():
    with pytest.raises(ValidationError):
        ArticleRevisionCreateIn(title='标题', body_markdown='正文')
    for action in ('return', 'reject'):
        with pytest.raises(ValidationError):
            ReviewCreateIn(action=action, comment='  ')
    with pytest.raises(ValidationError):
        ReviewCreateIn(action='approve', checklist={'title': 'pass'})
    checklist = {'title': 'pass', 'content': 'pass', 'facts': 'pass', 'citations': 'pass', 'image_copyright': 'not_applicable', 'account_compliance': 'pass', 'layout': 'pass'}
    assert ReviewCreateIn(action='approve', checklist=checklist).action == 'approve'
    with pytest.raises(ValidationError):
        ReviewCreateIn(action='approve', checklist={**checklist, 'facts': 'not_applicable'})


def test_stale_revision_returns_409_without_writing(client, db_engine):
    with db_engine.begin() as conn:
        article_id = conn.execute(text("INSERT INTO articles(origin_type,status) VALUES ('manual','draft') RETURNING id")).scalar_one()
        revision_id = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,body_markdown) VALUES (:id,1,'原始标题','原始正文') RETURNING id"), {'id': article_id}).scalar_one()
        conn.execute(text('UPDATE articles SET current_revision_id=:revision WHERE id=:id'), {'id': article_id, 'revision': revision_id})
    assert client.post('/api/v1/auth/login', json={'account': 'admin', 'password': 'correct-password'}).status_code == 200
    headers = {'X-CSRF-Token': client.cookies.get('wetchat_csrf')}
    payload = {'base_revision_id': str(uuid4()), 'title': '新标题', 'body_markdown': '新正文'}
    result = client.post(f'/api/v1/articles/{article_id}/revisions', headers=headers, json=payload)
    assert result.status_code == 409 and result.json()['error']['code'] == 'revision_conflict'
    result = client.post(f'/api/v1/articles/{article_id}/revisions', headers=headers, json={**payload, 'base_revision_id': str(revision_id)})
    assert result.status_code == 201
    with db_engine.begin() as conn:
        assert conn.execute(text('SELECT count(*) FROM article_revisions WHERE article_id=:id'), {'id': article_id}).scalar_one() == 2
