import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.adapters.wechat_client import WechatClient, WechatError
from app.errors import ApiError
from app.services.audit_service import record_operation
from app.services.wechat_account_service import account, require_available, cache_token


def platform(conn):
    row = conn.execute(text("SELECT * FROM system_settings WHERE key='platform'")).mappings().one()
    return {**row['value'], 'version': row['version'], 'updated_at': row['updated_at']}


def save_platform(conn, payload, user_id):
    result = conn.execute(text("UPDATE system_settings SET value=CAST(:value AS jsonb),version=version+1,updated_by=:user,updated_at=now() WHERE key='platform' AND version=:version RETURNING version"), {'value': json.dumps(payload.model_dump(exclude={'version'}), ensure_ascii=False), 'user': user_id, 'version': payload.version}).scalar()
    if not result:
        raise ApiError(409, 'settings_conflict', '设置已被其他人修改，请刷新后重新保存')
    record_operation(conn, user_id=user_id, action='settings.platform.update', object_type='system_settings', detail={'version': result})
    return platform(conn)


def safe_log_detail(detail):
    # Old audit rows may predate strict write masking. Never expose arbitrary old strings.
    from app.services.audit_service import mask
    masked = mask(detail or {})
    allowed = {'version', 'config_version', 'reason', 'state', 'outcome', 'source', 'article_url', 'article_revision_id', 'revision_id', 'attempt_id', 'name', 'purpose', 'status', 'enabled', 'publish_permission_confirmed', 'role_ids', 'permission_codes'}
    def safe(value):
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [safe(v) for v in value[:100]]
        if isinstance(value, str) and (value == '***' or re.fullmatch(r'[a-zA-Z0-9_:.,/ -]{1,255}', value)):
            if re.search(r'(?i)(bearer|password|secret|token|api[_-]?key|sk-|://)', value):
                return '***'
            return value
        return '详情已隐藏'
    return {key: safe(value) for key, value in masked.items() if key in allowed or value == '***'}


def collect_metrics(engine, settings, account_id, metric_date, user_id, client_factory=WechatClient):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if metric_date >= today or metric_date < today-timedelta(days=7):
        raise ApiError(422, 'invalid_metric_date', '请选择北京时间昨日或此前7天内的日期')
    with engine.connect() as conn:
        acct = account(conn, account_id)
        require_available(acct)
    client = client_factory(acct, settings)
    rows = []
    reason = ''
    try:
        result = client.call('/datacube/getarticletotal', {'begin_date': metric_date.isoformat(), 'end_date': metric_date.isoformat()})
        if not isinstance(result.get('list'), list):
            raise WechatError('invalid_wechat_response', '微信未返回有效指标列表')
        for item in result['list']:
            details = item.get('details') or []
            if not item.get('msgid') or not details:
                continue
            latest = max(details, key=lambda d: d.get('stat_date', ''))
            values = {name: latest.get(key) for name,key in [('reads','int_page_read_count'),('likes','like_count'),('shares','share_count')]}
            values = {key: value if type(value) is int and value >= 0 else None for key,value in values.items()}
            available = sum(v is not None for v in values.values())
            rows.append({'external': str(item['msgid']), 'availability': 'available' if available==3 else 'partial' if available else 'unavailable', 'reason': '' if available==3 else '微信未返回部分或全部指标', **values})
        if not rows:
            reason = '微信未返回该日图文指标，不能认定阅读量为零'
    except WechatError as exc:
        reason = exc.message
    if not rows:
        rows = [{'external': '', 'availability': 'unavailable', 'reason': reason, 'reads': None, 'likes': None, 'shares': None}]
    with engine.begin() as conn:
        current = account(conn, account_id, lock=True)
        if current['credential_version'] != acct['credential_version'] or current['status'] != 'active':
            raise ApiError(409, 'account_changed', '账号已变化，未保存旧凭据的采集结果')
        cache_token(conn, acct, client, settings)
        for row in rows:
            conn.execute(text("INSERT INTO account_article_metrics(account_id,external_article_id,metric_date,availability,reads,likes,shares,reason) VALUES (:account,:external,:day,:availability,:reads,:likes,:shares,:reason) ON CONFLICT(account_id,external_article_id,metric_date) DO UPDATE SET availability=EXCLUDED.availability,reads=EXCLUDED.reads,likes=EXCLUDED.likes,shares=EXCLUDED.shares,reason=EXCLUDED.reason,collected_at=now()"), {'account': str(account_id), 'day': metric_date, **row})
        # A later successful retry supersedes the unavailable sentinel for that day.
        if any(row['external'] for row in rows):
            conn.execute(text("DELETE FROM account_article_metrics WHERE account_id=:account AND metric_date=:day AND external_article_id=''"), {'account': str(account_id), 'day': metric_date})
        record_operation(conn, user_id=user_id, action='analytics.metrics.collect', object_type='wechat_account', object_id=account_id, result='success' if not reason else 'failed', detail={'status': rows[0]['availability']})
    return {'reachable': not bool(reason), 'reason': reason or '已保存微信返回的实际字段及采集时间；缺失字段显示不可用'}
