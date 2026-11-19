"""Permission-aware in-app adapter over durable business facts; repeatable delivery."""
from sqlalchemy import text

from app.errors import ApiError
from app.services.analytics_service import facts

CATEGORIES = ['collection', 'creation', 'review', 'publishing', 'exception']


def events_sql():
    parts = []
    for kind, category, permission in [('collection','collection','collection:read'), ('creation','creation','creation:read'), ('publishing','publishing','publish:read')]:
        # Attempts retain completed sync/publish events even after delivery state changes.
        when = 'occurred_at'
        if kind in ('collection','creation'):
            table = 'collection_runs' if kind == 'collection' else 'creation_tasks'
            when = f'(SELECT COALESCE(t.finished_at,t.updated_at) FROM {table} t WHERE t.id::text=f.id)'
        elif kind == 'publishing':
            when = "CASE WHEN source='api_publish' THEN (SELECT d.updated_at FROM publish_orders d WHERE d.id::text=split_part(f.id,':',2)) WHEN source='draft_sync' THEN (SELECT d.updated_at FROM wechat_draft_deliveries d WHERE d.id::text=split_part(f.id,':',2)) ELSE occurred_at END"
        parts.append("SELECT source||':'||id||':'||status AS event_key,CASE WHEN status IN ('failed','unknown') THEN 'exception' ELSE '"+category+"' END AS category,title,status,url,"+when+" AS occurred_at,'"+permission+"' AS required_permission FROM ("+facts(kind)+") f WHERE status IN ('succeeded','failed','unknown','awaiting_manual_publish','manual_published','synced')")
    parts.append("SELECT 'review-pending:'||a.current_revision_id AS event_key,'review' AS category,r.title,a.status,'/content/articles/'||a.id AS url,a.submitted_at AS occurred_at,'article:read' AS required_permission FROM articles a JOIN article_revisions r ON r.id=a.current_revision_id WHERE a.status='pending_review'")
    parts.append("SELECT 'review:'||r.id AS event_key,'review' AS category,v.title,r.action AS status,'/content/articles/'||r.article_id AS url,r.created_at AS occurred_at,'article:read' AS required_permission FROM reviews r JOIN article_revisions v ON v.id=r.article_revision_id")
    parts.append("SELECT 'account:'||id||':'||credential_version AS event_key,'exception' AS category,name AS title,status,'/accounts?account_id='||id AS url,updated_at AS occurred_at,'account:read' AS required_permission FROM wechat_accounts WHERE status<>'active'")
    return ' UNION ALL '.join(parts)


def deliver(conn, recipient_id=None, limit=500):
    recipient = ' AND u.id=:recipient' if recipient_id else ''
    result = conn.execute(text("""
INSERT INTO notifications(recipient_id,event_key,category,title,body,url,required_permission,occurred_at)
SELECT recipient_id,event_key,category,left(title,255),status,url,required_permission,occurred_at FROM (
 SELECT u.id AS recipient_id,e.* FROM ("""+events_sql()+""") e
 CROSS JOIN users u
 LEFT JOIN notification_preferences pref ON pref.user_id=u.id AND pref.category=e.category AND pref.channel='in_app'
 WHERE u.status='active' AND e.occurred_at>=u.created_at
 AND COALESCE(pref.enabled,true) AND (pref.updated_at IS NULL OR e.occurred_at>=pref.updated_at)
 AND EXISTS(SELECT 1 FROM user_roles ur JOIN role_permissions rp ON rp.role_id=ur.role_id JOIN permissions p ON p.id=rp.permission_id WHERE ur.user_id=u.id AND p.code=e.required_permission)
 AND NOT EXISTS(SELECT 1 FROM notifications n WHERE n.recipient_id=u.id AND n.event_key=e.event_key AND n.channel='in_app')
 """+recipient+""" ORDER BY e.occurred_at,u.id,e.event_key LIMIT :limit
) batch ON CONFLICT(recipient_id,event_key,channel) DO NOTHING RETURNING id
"""), {'recipient': str(recipient_id) if recipient_id else None, 'limit': limit}).scalars().all()
    return len(result)


def visible(user):
    return {'user': str(user.id), 'permissions': [str(p) for p in user.permissions]}


def read_one(conn, user, notification_id):
    row = conn.execute(text('UPDATE notifications SET read_at=COALESCE(read_at,now()) WHERE id=:id AND recipient_id=:user AND required_permission=ANY(CAST(:permissions AS text[])) RETURNING *'), {'id': str(notification_id), **visible(user)}).mappings().first()
    if not row:
        raise ApiError(404, 'not_found', '通知不存在或无权读取')
    return dict(row)


def preferences(conn, user_id):
    saved = {r['category']: dict(r) for r in conn.execute(text('SELECT category,channel,enabled,updated_at FROM notification_preferences WHERE user_id=:user'), {'user': str(user_id)}).mappings()}
    return [saved.get(category, {'category': category, 'enabled': True, 'channel': 'in_app', 'updated_at': None}) for category in CATEGORIES]
