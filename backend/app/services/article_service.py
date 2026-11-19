"""Immutable article versions and serialized human review transitions."""
import json
import re
from uuid import uuid4

from sqlalchemy import text

from app.errors import ApiError
from app.services.audit_service import record_operation


def article(conn, article_id, *, lock=False):
    row = conn.execute(text('SELECT * FROM articles WHERE id=:id' + (' FOR UPDATE' if lock else '')), {'id': str(article_id)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '文章不存在')
    return dict(row)


def check_revision(row, revision_id):
    if str(row['current_revision_id']) != str(revision_id):
        raise ApiError(409, 'revision_conflict', '文章已被修改，请读取最新版本后重试', [{'field': 'base_revision_id', 'message': '不是当前修订'}])


def revision(conn, article_id, revision_id):
    row = conn.execute(text('SELECT * FROM article_revisions WHERE id=:revision AND article_id=:article'), {'revision': str(revision_id), 'article': str(article_id)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '文章修订不存在')
    result = dict(row)
    result['materials'] = [dict(item) for item in conn.execute(text('SELECT material_id,material_revision_id FROM article_materials WHERE article_revision_id=:id ORDER BY reference_order'), {'id': str(revision_id)}).mappings()]
    return result


def save(conn, payload, user_id, article_id=None):
    if article_id:
        current = article(conn, article_id, lock=True)
        check_revision(current, payload.base_revision_id)
        if current['status'] == 'published':
            raise ApiError(409, 'invalid_article_state', '已发布文章不能直接编辑')
        if conn.execute(text("SELECT 1 FROM wechat_draft_deliveries WHERE article_id=:id AND status IN ('syncing','unknown') LIMIT 1"), {'id': str(article_id)}).scalar():
            raise ApiError(409, 'draft_delivery_in_progress', '文章正在同步微信草稿或等待结果核对，请先处理同步结果再编辑')
        if conn.execute(text("SELECT 1 FROM publish_orders WHERE article_id=:id AND status IN ('submitting','publishing','unknown') LIMIT 1"), {'id': str(article_id)}).scalar():
            raise ApiError(409, 'publication_in_progress', '文章正在提交微信或等待结果核对，请先处理发布结果再编辑')
        version = conn.execute(text('SELECT version FROM article_revisions WHERE id=:id'), {'id': current['current_revision_id']}).scalar_one() + 1
    else:
        article_id = uuid4()
        conn.execute(text("INSERT INTO articles(id,origin_type,status,created_by) VALUES (:id,'manual','draft',:user)"), {'id': article_id, 'user': user_id})
        version = 1
    for ref in payload.materials:
        valid = conn.execute(text('SELECT 1 FROM material_revisions WHERE id=:revision AND material_id=:material'), {'revision': ref.material_revision_id, 'material': ref.material_id}).scalar()
        if not valid:
            raise ApiError(422, 'invalid_reference', '引用修订不属于指定素材')
    image_ids = set(re.findall(r'/api/v1/files/([0-9a-fA-F-]{36})/image', payload.body_markdown))
    if payload.cover_object_id:
        image_ids.add(str(payload.cover_object_id))
    for image_id in image_ids:
        from uuid import UUID
        try:
            image_id = str(UUID(image_id))
        except ValueError:
            raise ApiError(422, 'invalid_image', '图片标识无效') from None
        image = conn.execute(text('SELECT content_type,uploader_id FROM stored_objects WHERE id=:id'), {'id': image_id}).mappings().first()
        if not image or image['content_type'] not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            raise ApiError(422, 'invalid_cover', '封面必须是已登记的图片')
        referenced = conn.execute(text('SELECT 1 FROM article_revisions WHERE cover_object_id=:id OR strpos(body_markdown,:path)>0 LIMIT 1'), {'id': image_id, 'path': f'/api/v1/files/{image_id}/image'}).scalar()
        if str(image['uploader_id']) != str(user_id) and not referenced:
            raise ApiError(403, 'forbidden', '不能使用无访问权限的图片')
    revision_id = uuid4()
    values = payload.model_dump(exclude={'materials', 'base_revision_id'})
    values.update(id=revision_id, article=article_id, version=version, user=user_id,
                  keywords=json.dumps(payload.keywords, ensure_ascii=False), layout_config=json.dumps(payload.layout_config.model_dump(), ensure_ascii=False))
    conn.execute(text('INSERT INTO article_revisions(id,article_id,version,title,author,summary,keywords,body_markdown,cover_object_id,layout_config,created_by) VALUES (:id,:article,:version,:title,:author,:summary,CAST(:keywords AS jsonb),:body_markdown,:cover_object_id,CAST(:layout_config AS jsonb),:user)'), values)
    for index, ref in enumerate(payload.materials, 1):
        conn.execute(text('INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:revision,:material,:input,:position)'), {'revision': revision_id, 'material': ref.material_id, 'input': ref.material_revision_id, 'position': index})
    conn.execute(text("UPDATE articles SET current_revision_id=:revision,status='draft',submitted_at=NULL,updated_at=now() WHERE id=:id"), {'revision': revision_id, 'id': article_id})
    record_operation(conn, user_id=user_id, action='article.save', object_type='article', object_id=article_id, detail={'revision_id': str(revision_id), 'version': version})
    return {'article_id': article_id, 'status': 'draft', 'current_revision_id': revision_id, 'revision': revision(conn, article_id, revision_id)}


def submit(conn, article_id, payload, user_id):
    row = article(conn, article_id, lock=True)
    check_revision(row, payload.base_revision_id)
    if row['status'] not in ('draft', 'returned', 'rejected', 'pending_review'):
        raise ApiError(409, 'invalid_article_state', '当前状态不能提审')
    if row['status'] != 'pending_review':
        conn.execute(text("UPDATE articles SET status='pending_review',submitted_at=now(),updated_at=now() WHERE id=:id"), {'id': str(article_id)})
        record_operation(conn, user_id=user_id, action='article.submit', object_type='article', object_id=article_id)
    return {'article_id': article_id, 'revision_id': payload.base_revision_id, 'status': 'pending_review'}


def review(conn, revision_id, payload, user_id):
    article_id = conn.execute(text('SELECT article_id FROM article_revisions WHERE id=:id'), {'id': str(revision_id)}).scalar()
    if article_id is None:
        raise ApiError(404, 'not_found', '文章修订不存在')
    row = article(conn, article_id, lock=True)
    check_revision(row, revision_id)
    if row['status'] != 'pending_review':
        raise ApiError(409, 'invalid_article_state', '仅可审核当前待审版本')
    result = dict(conn.execute(text('INSERT INTO reviews(article_id,article_revision_id,action,checklist,comment,reviewer_id) VALUES (:article,:revision,:action,CAST(:checklist AS jsonb),:comment,:user) RETURNING *'), {'article': article_id, 'revision': str(revision_id), 'action': payload.action, 'checklist': json.dumps(payload.checklist.model_dump()), 'comment': payload.comment, 'user': user_id}).mappings().one())
    status = {'approve': 'approved', 'return': 'returned', 'reject': 'rejected'}[payload.action]
    conn.execute(text('UPDATE articles SET status=:status,updated_at=now() WHERE id=:id'), {'status': status, 'id': article_id})
    record_operation(conn, user_id=user_id, action='article.review', object_type='article', object_id=article_id, detail={'revision_id': str(revision_id), 'action': payload.action})
    return result
