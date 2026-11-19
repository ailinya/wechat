"""All-time material reuse with separate publication facts and metric availability."""
from sqlalchemy import text


def reuse_report(conn, page=1, page_size=20):
    total = conn.execute(text('SELECT count(*) FROM materials WHERE deleted_at IS NULL')).scalar_one()
    materials = conn.execute(text("""
        SELECT m.id,m.title,count(DISTINCT r.article_id) AS articles,
               count(DISTINCT am.article_revision_id) AS article_revisions
        FROM materials m LEFT JOIN article_materials am ON am.material_id=m.id
        LEFT JOIN article_revisions r ON r.id=am.article_revision_id
        WHERE m.deleted_at IS NULL GROUP BY m.id ORDER BY m.created_at DESC,m.id DESC
        LIMIT :limit OFFSET :offset
    """), {'limit': page_size, 'offset': (page-1)*page_size}).mappings().all()
    items = []
    for row in materials:
        material = dict(row)
        params = {'material': row['id']}
        accounts = conn.execute(text("""
            WITH refs AS (SELECT DISTINCT am.article_revision_id,r.article_id
              FROM article_materials am JOIN article_revisions r ON r.id=am.article_revision_id
              WHERE am.material_id=:material),
            involved AS (SELECT o.account_id FROM publish_orders o JOIN refs r ON r.article_revision_id=o.article_revision_id
              UNION SELECT d.account_id FROM wechat_draft_deliveries d JOIN refs r ON r.article_revision_id=d.article_revision_id)
            SELECT a.id,a.name,
              (SELECT count(*) FROM publish_orders o JOIN refs r ON r.article_revision_id=o.article_revision_id WHERE o.account_id=a.id) AS publish_orders,
              (SELECT count(*) FROM publish_attempts p JOIN publish_orders o ON o.id=p.order_id JOIN refs r ON r.article_revision_id=o.article_revision_id WHERE o.account_id=a.id) AS publish_attempts,
              (SELECT count(*) FROM wechat_draft_deliveries d JOIN refs r ON r.article_revision_id=d.article_revision_id WHERE d.account_id=a.id) AS draft_deliveries,
              (SELECT count(*) FROM wechat_draft_attempts p JOIN wechat_draft_deliveries d ON d.id=p.delivery_id JOIN refs r ON r.article_revision_id=d.article_revision_id WHERE d.account_id=a.id) AS draft_attempts,
              (SELECT count(*) FROM wechat_draft_deliveries d JOIN refs r ON r.article_revision_id=d.article_revision_id WHERE d.account_id=a.id AND d.status='manual_published') AS manual_publications
            FROM involved i JOIN wechat_accounts a ON a.id=i.account_id ORDER BY a.name,a.id
        """), params).mappings().all()
        material['accounts'] = []
        for account in accounts:
            entry = dict(account)
            snapshots = conn.execute(text("""
                SELECT DISTINCT ON (m.external_article_id) m.article_id,m.external_article_id,m.collected_at,m.availability,m.reason,m.reads,m.likes,m.shares
                FROM account_article_metrics m WHERE m.account_id=:account
                  AND EXISTS (SELECT 1 FROM article_materials am JOIN article_revisions ar ON ar.id=am.article_revision_id WHERE am.material_id=:material AND ar.article_id=m.article_id)
                ORDER BY m.external_article_id,m.collected_at DESC,m.id DESC
            """), {'material': row['id'], 'account': account['id']}).mappings().all()
            entry['metric_snapshots'] = [dict(snapshot) for snapshot in snapshots]
            values = [snapshot[field] for snapshot in snapshots for field in ('reads', 'likes', 'shares')]
            entry['metrics_status'] = 'unavailable' if not values or all(value is None for value in values) else 'partial' if any(value is None for value in values) else 'available'
            entry['metrics_note'] = '仅显示明确关联本地文章的最新外部快照；空值表示不可获取，快照不求和。' if snapshots else '没有可关联本地文章的微信指标，阅读、点赞和分享量不可用。'
            material['accounts'].append(entry)
        items.append(material)
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'definition': '全历史：文章和文章修订分别去重；发布单、发布尝试、草稿同步、同步尝试和人工登记分别计数。微信快照按外部文章取最新值，不合计重复快照。'}
