"""Shared fact queries for reports, charts, exports and permission-aware dashboard."""
import csv
import io
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.errors import ApiError
from app.schemas.operations import ReportFilters

PERMISSIONS = {'collection': 'collection:read', 'materials': 'material:read', 'creation': 'creation:read', 'reviews': 'article:read', 'publishing': 'publish:read', 'accounts': 'account:read'}
DEFINITIONS = {
    'collection': '一行一个采集执行，按创建时间。数量为采集结果数；成功率=成功/(成功+失败)，部分成功单列。来源分布按结果来源计数。',
    'materials': '一行一个未删除素材，按创建时间。引用按不同文章去重，复用为引用文章数>1；不计算素材成功率。',
    'creation': '一行一个逻辑创作任务，按创建时间。重试不新增任务；数量为实际产出文章数，attempts为作业尝试；成功率排除条件不足/取消/未结束。',
    'reviews': '一行一条人工审核记录，按审核时间。通过率=通过/全部审核记录；同一文章复审保留多条记录。',
    'publishing': '接口发布单和草稿交付分别计数；人工登记另列一行，按登记时间。成功率仅计算接口发布单成功/(成功+失败)，草稿不计入发布成功率。',
    'accounts': '账号下每篇外部图文在区间内的最新采集快照，无快照仍显示账号。阅读/分享为微信返回的累计量，不能跨快照相加；点赞缺失显示不可用。人工文章未强行关联微信msgid。',
}


def require_domain(user, kind):
    if PERMISSIONS[kind] not in user.permissions:
        raise ApiError(403, 'forbidden', '缺少该报表对应的业务读取权限')


def bounds(filters):
    zone = ZoneInfo(filters.timezone)
    today = datetime.now(zone).date()
    end = filters.end_date or today + timedelta(days=1)
    start = filters.start_date or end - timedelta(days=30)
    if not 0 < (end-start).days <= 366:
        raise ApiError(422, 'invalid_interval', '日期区间须大于0且不超过366天')
    resolved = filters.model_copy(update={'start_date': start, 'end_date': end})
    return resolved, datetime.combine(start, time.min, zone).astimezone(timezone.utc), datetime.combine(end, time.min, zone).astimezone(timezone.utc)


def select_fact(from_sql, **columns):
    defaults = {'id': "''::text", 'title': "''::text", 'status': "''::text", 'occurred_at': 'now()', 'source': "''::text", 'url': "''::text", 'account_id': 'NULL::text', 'collection_task_id': 'NULL::text', 'creation_task_id': 'NULL::text', 'attempts': '0', 'quantity': '1', 'reference_count': '0', 'group_name': "''::text", 'reason': "''::text", 'collected_at': 'NULL::timestamptz', 'metrics': "'{}'::jsonb"}
    defaults.update(columns)
    return 'SELECT ' + ','.join(f'{value} AS {name}' for name, value in defaults.items()) + ' FROM ' + from_sql


def facts(kind):
    if kind == 'collection':
        return select_fact('collection_runs r JOIN collection_tasks t ON t.id=r.task_id LEFT JOIN async_jobs j ON j.id=r.async_job_id', id='r.id::text', title='t.name', status='r.status', occurred_at='r.created_at', source="'collection'", collection_task_id='r.task_id::text', url="'/collection?view=results&run_id='||r.id", attempts='COALESCE((SELECT sum(jj.attempts) FROM async_jobs jj WHERE jj.resource_id=r.id),0)', quantity='(SELECT count(*) FROM collection_results c WHERE c.run_id=r.id)', group_name='t.name', reason="CASE WHEN r.status='failed' THEN '采集执行失败，请查看执行详情' ELSE '' END")
    if kind == 'materials':
        return select_fact('materials m', id='m.id::text', title='m.title', status='m.usage_status', occurred_at='m.created_at', source='m.origin', url="'/materials?material_id='||m.id", reference_count='(SELECT count(DISTINCT v.article_id) FROM article_materials am JOIN article_revisions v ON v.id=am.article_revision_id WHERE am.material_id=m.id)', group_name='m.material_type') + ' WHERE m.deleted_at IS NULL'
    if kind == 'creation':
        return select_fact('creation_tasks t LEFT JOIN creation_rules r ON r.id=t.rule_id LEFT JOIN async_jobs j ON j.id=t.async_job_id', id='t.id::text', title='t.topic', status='t.status', occurred_at='t.created_at', source='t.mode', creation_task_id='t.id::text', url="'/creation?view=tasks&task_id='||t.id", attempts='COALESCE((SELECT sum(jj.attempts) FROM async_jobs jj WHERE jj.resource_id=t.id),0)', quantity='(SELECT count(*) FROM articles a WHERE a.creation_task_id=t.id)', group_name="COALESCE(r.name,'人工创作')", reason="COALESCE(t.error_code,'')")
    if kind == 'reviews':
        return select_fact('reviews r JOIN articles a ON a.id=r.article_id JOIN article_revisions v ON v.id=r.article_revision_id', id='r.id::text', title='v.title', status='r.action', occurred_at='r.created_at', source="'human_review'", creation_task_id='a.creation_task_id::text', url="'/content/articles/'||a.id", group_name="'人工审核'")
    if kind == 'publishing':
        common = ' JOIN articles a ON a.id=d.article_id JOIN article_revisions v ON v.id=d.article_revision_id JOIN wechat_accounts w ON w.id=d.account_id'
        values = dict(title='v.title', status='d.status', occurred_at='d.created_at', account_id='d.account_id::text', creation_task_id='a.creation_task_id::text', group_name='w.name', reason="COALESCE(d.error_code,'')")
        api = select_fact('publish_orders d'+common, **values, id="'api:'||d.id", source="'api_publish'", url="'/content/articles/'||a.id||'?order_id='||d.id", attempts='(SELECT count(*) FROM publish_attempts p WHERE p.order_id=d.id)')
        draft = select_fact('wechat_draft_deliveries d'+common, **{**values, 'status': "CASE WHEN d.status IN ('awaiting_manual_publish','manual_published') THEN 'synced' ELSE d.status END"}, id="'draft:'||d.id", source="'draft_sync'", url="'/content/articles/'||a.id", attempts='(SELECT count(*) FROM wechat_draft_attempts p WHERE p.delivery_id=d.id)')
        manual = select_fact('wechat_draft_deliveries d'+common, **{**values, 'status': "'manual_published'", 'occurred_at': 'd.manual_published_at'}, id="'manual:'||d.id", source="'operator'", url="'/content/articles/'||a.id") + " WHERE d.status='manual_published'"
        return api+' UNION ALL '+draft+' UNION ALL '+manual
    if kind == 'accounts':
        return select_fact("wechat_accounts a LEFT JOIN LATERAL (SELECT DISTINCT ON (external_article_id) * FROM account_article_metrics m WHERE m.account_id=a.id AND m.collected_at>=:start AND m.collected_at<:end ORDER BY external_article_id,collected_at DESC,id DESC) m ON true", id="COALESCE(m.id::text,a.id::text)", title="a.name||CASE WHEN m.external_article_id IS NOT NULL AND m.external_article_id<>'' THEN ' · '||m.external_article_id ELSE '' END", status="COALESCE(m.availability,'unavailable')", occurred_at='COALESCE(m.collected_at,a.created_at)', source="'wechat_metrics'", account_id='a.id::text', url="'/accounts?account_id='||a.id", collected_at='m.collected_at', group_name='a.name', reason="COALESCE(m.reason,'尚未采集或接口不可用')", metrics="jsonb_build_object('reads',jsonb_build_object('value',m.reads,'available',m.reads IS NOT NULL,'reason',CASE WHEN m.reads IS NULL THEN COALESCE(NULLIF(m.reason,''),CASE WHEN m.id IS NULL THEN '尚未采集或接口不可用' ELSE '微信未返回阅读指标' END) ELSE '' END),'likes',jsonb_build_object('value',m.likes,'available',m.likes IS NOT NULL,'reason',CASE WHEN m.likes IS NULL THEN COALESCE(NULLIF(m.reason,''),CASE WHEN m.id IS NULL THEN '尚未采集或接口不可用' ELSE '微信未返回点赞指标' END) ELSE '' END),'shares',jsonb_build_object('value',m.shares,'available',m.shares IS NOT NULL,'reason',CASE WHEN m.shares IS NULL THEN COALESCE(NULLIF(m.reason,''),CASE WHEN m.id IS NULL THEN '尚未采集或接口不可用' ELSE '微信未返回分享指标' END) ELSE '' END))")


def filtered(kind, filters):
    filters, start, end = bounds(filters)
    params = {'start': start, 'end': end, 'zone': filters.timezone}
    allowed = {'collection': {'collection_task_id'}, 'materials': {'collection_task_id', 'creation_task_id'}, 'creation': {'creation_task_id', 'collection_task_id'}, 'reviews': {'creation_task_id'}, 'publishing': {'creation_task_id', 'account_id'}, 'accounts': {'account_id'}}[kind]
    where = [] if kind == 'accounts' else ['f.occurred_at>=:start', 'f.occurred_at<:end']
    for key in ['account_id', 'collection_task_id', 'creation_task_id']:
        value = getattr(filters, key)
        if value is None:
            continue
        if key not in allowed:
            raise ApiError(422, 'unsupported_filter', '该数据类型不支持此筛选，请切换类型或清除筛选')
        params[key] = str(value)
        if kind == 'materials':
            if key == 'collection_task_id':
                where.append('EXISTS (SELECT 1 FROM collection_results cr JOIN collection_runs rr ON rr.id=cr.run_id WHERE cr.material_id::text=f.id AND rr.task_id::text=:collection_task_id)')
            else:
                where.append('EXISTS (SELECT 1 FROM creation_task_materials cm WHERE cm.material_id::text=f.id AND cm.creation_task_id::text=:creation_task_id AND cm.selected)')
        elif kind == 'creation' and key == 'collection_task_id':
            where.append("EXISTS (SELECT 1 FROM creation_tasks ct WHERE ct.id::text=f.id AND ct.config_snapshot->'collection_task_ids' ? :collection_task_id)")
        else:
            where.append(f'f.{key}=:{key}')
    return 'SELECT * FROM ('+facts(kind)+') f'+(' WHERE '+' AND '.join(where) if where else ''), params, filters


def report(conn, user, kind, filters, page=1, page_size=20, *, export=False):
    require_domain(user, kind)
    query, params, resolved = filtered(kind, filters)
    groups = conn.execute(text('SELECT status,source,group_name,reason,count(*) AS n,sum(attempts) AS attempts,sum(quantity) AS quantity,count(*) FILTER(WHERE reference_count>1) AS reused FROM ('+query+') q GROUP BY status,source,group_name,reason'), params).mappings().all()
    status, sources, by_group, reasons = Counter(), Counter(), Counter(), Counter()
    total = attempts = quantity = reused = success = failed = 0
    for row in groups:
        n = row['n']; total += n; attempts += row['attempts']; quantity += row['quantity']; reused += row['reused']
        status[row['status']] += n; sources[row['source']] += n; by_group[row['group_name']] += n
        if row['status'] == 'failed' and row['reason']:
            reasons[row['reason']] += n
        eligible = kind not in ('materials', 'accounts') and (kind != 'publishing' or row['source'] == 'api_publish')
        if eligible:
            success += n if row['status'] in ('succeeded', 'approve') else 0
            failed += n if row['status'] in ('failed', 'return', 'reject') else 0
    if kind == 'collection':
        sources = Counter({r.name: r.n for r in conn.execute(text('SELECT COALESCE(s.name,\'搜索发现\') AS name,count(*) AS n FROM collection_results c LEFT JOIN collection_sources s ON s.id=c.source_id WHERE c.run_id::text IN (SELECT id FROM ('+query+') q) GROUP BY s.name'), params)})
    denominator = success + failed
    summary = {'total': total, 'succeeded': success, 'failed': failed, 'denominator': denominator, 'success_rate': success/denominator if denominator else None, 'attempts': attempts, 'quantity': quantity, 'reused_materials': reused, 'by_status': dict(status), 'by_source': dict(sources), 'by_group': dict(by_group), 'failure_reasons': dict(reasons), 'definition': DEFINITIONS[kind]}
    if export and total > 50000:
        raise ApiError(422, 'export_too_large', '超过50000行，请缩小日期或筛选范围后完整导出')
    items = [dict(row) for row in conn.execute(text(query+' ORDER BY occurred_at DESC,id DESC LIMIT :limit OFFSET :offset'), {**params, 'limit': 50000 if export else page_size, 'offset': 0 if export else (page-1)*page_size}).mappings()]
    trend_rows = conn.execute(text('SELECT (occurred_at AT TIME ZONE :zone)::date AS day,count(*) AS count FROM ('+query+') q GROUP BY day ORDER BY day'), params).mappings().all()
    return {'kind': kind, 'filters': resolved, 'items': items, 'total': total, 'page': page, 'page_size': page_size, 'summary': summary, 'trend': [dict(row) for row in trend_rows]}


def csv_export(result):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['记录ID', '标题', '状态', '归属时间UTC', '来源', '账号ID', '采集任务ID', '创作任务ID', '尝试次数', '数量', '引用文章数', '阅读量', '点赞量', '分享量', '指标采集时间UTC', '原因'])
    def safe(value):
        value = '' if value is None else str(value)
        return "'"+value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) or value.startswith(('\t','\r','\n')) else value
    for row in result['items']:
        metrics = row.get('metrics') or {}
        values = [row[k] for k in ['id', 'title', 'status', 'occurred_at', 'source', 'account_id', 'collection_task_id', 'creation_task_id', 'attempts', 'quantity', 'reference_count']]
        values += [metrics.get(k, {}).get('value') for k in ['reads', 'likes', 'shares']]
        values += [row.get('collected_at'), row['reason']]
        writer.writerow([safe(value) for value in values])
    return '\ufeff'+out.getvalue()


def dashboard(conn, user, zone_name):
    now = datetime.now(timezone.utc)
    zone = ZoneInfo(zone_name)
    start = datetime.combine(now.astimezone(zone).date(), time.min, zone).astimezone(timezone.utc)
    counters, recent, activity, todos, alerts = {}, [], [], [], []
    def count(name, permission, sql, params=None):
        counters[name] = conn.execute(text(sql), params or {}).scalar_one() if permission in user.permissions else None
    count('collected_today', 'collection:read', 'SELECT count(*) FROM collection_results WHERE collected_at>=:start', {'start': start})
    count('materials_total', 'material:read', 'SELECT count(*) FROM materials WHERE deleted_at IS NULL')
    count('materials_today', 'material:read', 'SELECT count(*) FROM materials WHERE deleted_at IS NULL AND created_at>=:start', {'start': start})
    count('ai_articles', 'article:read', "SELECT count(*) FROM articles WHERE origin_type<>'manual'")
    count('pending_review', 'article:read', "SELECT count(*) FROM articles WHERE status='pending_review'")
    count('published_articles', 'article:read', "SELECT count(*) FROM articles WHERE status='published'")
    count('publish_failed', 'publish:read', "SELECT count(*) FROM publish_orders WHERE status='failed'")
    count('drafts_awaiting_manual', 'publish:read', "SELECT count(*) FROM wechat_draft_deliveries WHERE status='awaiting_manual_publish'")
    if 'article:read' in user.permissions:
        recent = [dict(r) for r in conn.execute(text("SELECT a.id::text,r.title,a.status,'/content/articles/'||a.id AS url,a.updated_at AS occurred_at FROM articles a JOIN article_revisions r ON r.id=a.current_revision_id ORDER BY a.updated_at DESC,a.id DESC LIMIT 8")).mappings()]
        if 'account:read' in user.permissions:
            for item in recent:
                item['account_names'] = list(conn.execute(text('SELECT DISTINCT name FROM wechat_accounts WHERE id IN (SELECT account_id FROM publish_orders WHERE article_id=:article UNION SELECT account_id FROM wechat_draft_deliveries WHERE article_id=:article) ORDER BY name'), {'article': item['id']}).scalars())
        todos += [dict(r) for r in conn.execute(text("SELECT a.id::text,r.title,a.status,'/content/articles/'||a.id AS url,a.updated_at AS occurred_at FROM articles a JOIN article_revisions r ON r.id=a.current_revision_id WHERE a.status IN ('pending_review','approved') ORDER BY a.updated_at DESC,a.id DESC LIMIT 12")).mappings()]
    for kind in ['collection', 'creation', 'publishing']:
        if PERMISSIONS[kind] not in user.permissions:
            continue
        query = facts(kind)
        rows = [dict(r) for r in conn.execute(text('SELECT id,title,status,url,occurred_at,reason FROM ('+query+') q ORDER BY occurred_at DESC,id DESC LIMIT 10')).mappings()]
        activity += rows
        alerts += [dict(r) for r in conn.execute(text("SELECT id,title,status,url,occurred_at,reason FROM ("+query+") q WHERE status IN ('failed','unknown') ORDER BY occurred_at DESC,id DESC LIMIT 10")).mappings()]
        if kind == 'publishing':
            todos += [dict(r) for r in conn.execute(text("SELECT id,title,CASE WHEN source='draft_sync' AND status='synced' THEN 'awaiting_manual_publish' ELSE status END AS status,url,occurred_at,reason FROM ("+query+") q WHERE status IN ('awaiting_confirmation','unknown') OR (source='draft_sync' AND EXISTS(SELECT 1 FROM wechat_draft_deliveries d WHERE d.id::text=split_part(q.id,':',2) AND d.status='awaiting_manual_publish')) ORDER BY occurred_at DESC,id DESC LIMIT 10")).mappings()]
    if 'account:read' in user.permissions:
        alerts += [dict(r) for r in conn.execute(text("SELECT id::text,name AS title,status,'/accounts?account_id='||id AS url,updated_at AS occurred_at,'账号连接异常或已解绑' AS reason FROM wechat_accounts WHERE status<>'active' ORDER BY updated_at DESC LIMIT 10")).mappings()]
    return {'timezone': zone_name, 'as_of': now, 'counters': counters, 'recent_articles': recent, 'activity': sorted(activity, key=lambda r:r['occurred_at'], reverse=True)[:15], 'todos': sorted(todos, key=lambda r:r['occurred_at'], reverse=True)[:15], 'alerts': sorted(alerts, key=lambda r:r['occurred_at'], reverse=True)[:15]}
