from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text

from app.api.deps import CurrentUserDep, DbSession, get_settings, require_permission, require_audited_permission, verify_csrf
from app.api.responses import error_responses
from app.api.routes.wechat_accounts import paginate
from app.config import Settings
from app.database import get_engine
from app.errors import ApiError
from app.schemas.auth import PermissionCode, PermissionOut
from app.schemas.common import PaginatedResponse
from app.schemas.operations import (ConnectionOut, DashboardOut, IntegrationOut, MetricCollectionIn, MonitoredJobOut, NotificationChannels, NotificationOut, OperationLogOut, PlatformIn, PlatformOut, PlatformPublic, PreferenceIn, PreferenceOut, ReportFilters, ReportKind, ReportOut)
from app.services import analytics_service as analytics, notification_service as notifications, operations_service as service
from app.services.audit_service import record_operation
from app.schemas.operations import RuntimeOut, RuntimeRecoveryOut, OutboxOut, OutboxRetryOut

router = APIRouter(tags=['operations'])
READ = Depends(require_permission(PermissionCode.SETTINGS_READ))
WRITE = Depends(require_audited_permission(PermissionCode.SETTINGS_WRITE))
ANALYTICS = Depends(require_permission(PermissionCode.ANALYTICS_READ))
EXPORT = Depends(require_permission(PermissionCode.ANALYTICS_EXPORT))
LOGS = Depends(require_permission(PermissionCode.OPERATION_LOG_READ))
CSRF = Depends(verify_csrf)
ERRORS = error_responses(401, 403, 404, 409, 422, 503)


@router.get('/settings/runtime', response_model=RuntimeOut, responses=ERRORS)
def runtime(db:DbSession,settings:Settings=Depends(get_settings),user=LOGS):
    from app.services.runtime_service import status
    return status(db.connection(),settings.job_stale_timeout_minutes)


@router.post('/settings/runtime/recover-stale',response_model=RuntimeRecoveryOut,responses=ERRORS)
def recover_runtime(db:DbSession,settings:Settings=Depends(get_settings),user=WRITE,csrf=CSRF):
    from app.services.runtime_service import recover_once
    db.commit()
    return recover_once(get_engine(settings),settings,user.id)


@router.get('/settings/outbox',response_model=PaginatedResponse[OutboxOut],responses=ERRORS)
def outbox(db:DbSession,user=LOGS,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    return paginate(db.connection(),'SELECT id,event_type,aggregate_type,aggregate_id,status,attempts,available_at,created_at FROM outbox_events',{},page,page_size)


@router.post('/settings/outbox/{event_id}/retry',response_model=OutboxRetryOut,responses=ERRORS)
def retry_delivery(event_id:UUID,db:DbSession,user=WRITE,csrf=CSRF):
    from app.services.runtime_service import retry_outbox
    result=retry_outbox(db.connection(),event_id,user.id)
    db.commit()
    return result


@router.get('/settings/permissions', response_model=list[PermissionOut], responses=ERRORS)
def permission_catalog(db: DbSession, user=Depends(require_permission(PermissionCode.ROLE_READ))):
    return [dict(row) for row in db.connection().execute(text('SELECT * FROM permissions ORDER BY code')).mappings()]


@router.get('/platform', response_model=PlatformPublic, responses=ERRORS)
def public_platform(db: DbSession, user: CurrentUserDep):
    return service.platform(db.connection())


@router.get('/settings/platform', response_model=PlatformOut, responses=ERRORS)
def platform(db: DbSession, user=READ):
    return service.platform(db.connection())


@router.put('/settings/platform', response_model=PlatformOut, responses=ERRORS)
def save_platform(payload: PlatformIn, db: DbSession, user=WRITE, _csrf=CSRF):
    result = service.save_platform(db.connection(), payload, user.id)
    db.commit()
    return result


@router.get('/dashboard', response_model=DashboardOut, responses=ERRORS)
def dashboard(db: DbSession, user: CurrentUserDep):
    return analytics.dashboard(db.connection(), user, service.platform(db.connection())['timezone'])


@router.get('/analytics/{kind}', response_model=ReportOut, responses=ERRORS)
def report(kind: ReportKind, filters: Annotated[ReportFilters, Query()], db: DbSession, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=ANALYTICS):
    db.commit()
    return analytics.report(db.connection(execution_options={'isolation_level': 'REPEATABLE READ'}), user, kind, filters, page, page_size)


@router.get('/analytics/{kind}/export', responses={**ERRORS,200:{'description':'当前筛选的完整 CSV 报表','content':{'text/csv':{'schema':{'type':'string'}}}}}, response_class=Response)
def export(kind: ReportKind, filters: Annotated[ReportFilters, Query()], db: DbSession, user=EXPORT, _read=ANALYTICS):
    db.commit()
    result = analytics.report(db.connection(execution_options={'isolation_level': 'REPEATABLE READ'}), user, kind, filters, export=True)
    record_operation(db.connection(), user_id=user.id, action='analytics.export', object_type='report', detail={'name': kind})
    db.commit()
    return Response(analytics.csv_export(result), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{kind}.csv"', 'Cache-Control': 'private, no-store'})


@router.post('/analytics/accounts/{account_id}/collect-metrics', response_model=ConnectionOut, responses=ERRORS)
def collect_metrics(account_id: UUID, payload: MetricCollectionIn, db: DbSession, settings: Settings = Depends(get_settings), user=Depends(require_permission(PermissionCode.ACCOUNT_WRITE)), _read=ANALYTICS, _csrf=CSRF):
    db.commit()
    return service.collect_metrics(get_engine(settings), settings, account_id, payload.metric_date, user.id)


@router.get('/notifications/channels', response_model=NotificationChannels, responses=ERRORS)
def channels(user: CurrentUserDep):
    return NotificationChannels()


@router.get('/notifications/preferences', response_model=list[PreferenceOut], responses=ERRORS)
def preferences(db: DbSession, user: CurrentUserDep):
    return notifications.preferences(db.connection(), user.id)


@router.put('/notifications/preferences', response_model=list[PreferenceOut], responses=ERRORS)
def update_preference(payload: PreferenceIn, db: DbSession, user: CurrentUserDep, _csrf=CSRF):
    db.connection().execute(text('INSERT INTO notification_preferences(user_id,category,channel,enabled) VALUES (:user,:category,:channel,:enabled) ON CONFLICT(user_id,category,channel) DO UPDATE SET enabled=EXCLUDED.enabled,updated_at=now()'), {'user': user.id, **payload.model_dump()})
    record_operation(db.connection(), user_id=user.id, action='notification.preference.update', object_type='user', object_id=user.id, detail={'name': payload.category, 'enabled': payload.enabled})
    result = notifications.preferences(db.connection(), user.id)
    db.commit()
    return result


@router.get('/notifications', response_model=PaginatedResponse[NotificationOut], responses=ERRORS)
def list_notifications(db: DbSession, user: CurrentUserDep, unread_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    sql = 'SELECT * FROM notifications WHERE recipient_id=:user AND required_permission=ANY(CAST(:permissions AS text[]))'+(' AND read_at IS NULL' if unread_only else '')
    return paginate(db.connection(), sql, notifications.visible(user), page, page_size)


@router.post('/notifications/refresh', response_model=dict[str, int], responses=ERRORS)
def refresh_notifications(db: DbSession, user: CurrentUserDep, _csrf=CSRF):
    count = notifications.deliver(db.connection(), user.id)
    db.commit()
    return {'delivered': count}


@router.post('/notifications/{notification_id}/read', response_model=NotificationOut, responses=ERRORS)
def read_notification(notification_id: UUID, db: DbSession, user: CurrentUserDep, _csrf=CSRF):
    row = notifications.read_one(db.connection(), user, notification_id)
    db.commit()
    return row


@router.get('/settings/operation-logs', response_model=PaginatedResponse[OperationLogOut], responses=ERRORS)
def operation_logs(db: DbSession, user=LOGS, action: str | None = Query(None, max_length=64), object_type: str | None = Query(None, max_length=64), object_id: UUID | None = None, user_id: UUID | None = None, result: Literal['success','failed','denied'] | None = None, start: datetime | None = None, end: datetime | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    clauses, params = [], {}
    for name,value in [('action',action),('object_type',object_type),('object_id',object_id),('user_id',user_id),('result',result)]:
        if value is not None:
            clauses.append(f'l.{name}=:{name}')
            params[name] = str(value)
    for name,value,op in [('start',start,'>='),('end',end,'<')]:
        if value:
            if value.tzinfo is None:
                raise ApiError(422, 'invalid_time', '时间须包含时区')
            clauses.append(f'l.created_at{op}:{name}'); params[name] = value
    if start and end and start>=end:
        raise ApiError(422, 'invalid_time', '结束时间须晚于开始时间')
    sql = 'SELECT l.*,u.name AS user_name FROM operation_logs l LEFT JOIN users u ON u.id=l.user_id'+(' WHERE '+' AND '.join(clauses) if clauses else '')
    rows = paginate(db.connection(), sql, params, page, page_size)
    for row in rows['items']:
        row['detail'] = service.safe_log_detail(row['detail'])
    return rows


@router.get('/settings/jobs', response_model=PaginatedResponse[MonitoredJobOut], responses=ERRORS)
def jobs(db: DbSession, user=LOGS, status: Literal['pending','running','succeeded','failed','cancelled'] | None = None, job_type: str | None = Query(None, max_length=64), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    clauses, params = [], {}
    for name,value in [('status',status),('job_type',job_type)]:
        if value:
            clauses.append(f'{name}=:{name}'); params[name] = value
    return paginate(db.connection(), 'SELECT id,job_type,resource_type,resource_id,status,stage,progress,attempts,created_by,created_at,updated_at,finished_at FROM async_jobs'+(' WHERE '+' AND '.join(clauses) if clauses else ''), params, page, page_size)


@router.get('/settings/integrations', response_model=list[IntegrationOut], responses=ERRORS)
def integrations(db: DbSession, settings: Settings = Depends(get_settings), user=READ):
    from app.credentials import resolve_credential
    conn = db.connection()
    return [
        {'id': 'wechat', 'name': '微信公众号', 'configured': bool(conn.execute(text("SELECT 1 FROM wechat_accounts WHERE status='active' LIMIT 1")).scalar()), 'management_url': '/accounts', 'description': '按账号直连接入和检测；个人号使用草稿同步，发布权限单独判定'},
        {'id': 'model', 'name': 'AI模型', 'configured': bool(conn.execute(text('SELECT 1 FROM model_configs WHERE enabled LIMIT 1')).scalar()), 'management_url': '/settings?tab=models', 'description': '分析/生成/向量配置与凭据引用；连接测试使用实际服务'},
        {'id': 'search', 'name': '外部搜索', 'configured': bool(conn.execute(text('SELECT 1 FROM search_configs WHERE enabled LIMIT 1')).scalar()), 'management_url': '/settings?tab=models', 'description': '支持Tavily；能力限制与测试沿用搜索配置'},
        {'id': 'storage', 'name': 'RustFS文件存储', 'configured': bool(settings.rustfs_access_key and settings.rustfs_secret_key.get_secret_value()), 'management_url': '/settings?tab=integrations', 'description': '端点/桶/凭据由部署环境管理，网页不回显密钥；支持只读连接检查'},
        {'id': 'embedding', 'name': '向量服务', 'configured': bool(resolve_credential('OPENAI_API_KEY')), 'management_url': '/settings?tab=integrations', 'description': '使用部署环境的EMBEDDING_MODEL、EMBEDDING_BASE_URL和1024维配置，不调用文本模型接口测试向量服务'},
    ]


@router.post('/settings/integrations/storage/test', response_model=ConnectionOut, responses=ERRORS)
def test_storage(db: DbSession, settings: Settings = Depends(get_settings), user=WRITE, _csrf=CSRF):
    from app.adapters.object_storage import probe
    db.commit()
    result = probe(settings)
    record_operation(db.connection(), user_id=user.id, action='integration.storage.test', object_type='integration', result='success' if result['reachable'] else 'failed')
    db.commit()
    return result


@router.post('/settings/integrations/embedding/test', response_model=ConnectionOut, responses=ERRORS)
def test_embedding(db: DbSession, user=WRITE, _csrf=CSRF):
    from app.adapters.embedding_client import embed_texts, EmbeddingError
    db.commit()
    try:
        embed_texts(['连接测试'])
        result = {'reachable': True, 'reason': '实际向量服务连接及1024维输出检查通过'}
    except EmbeddingError as exc:
        result = {'reachable': False, 'reason': exc.message}
    record_operation(db.connection(), user_id=user.id, action='integration.embedding.test', object_type='integration', result='success' if result['reachable'] else 'failed')
    db.commit()
    return result
