"""Operational recovery never requeues a job that may have written externally."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import text
from app.errors import ApiError
from app.services import async_job_service
from app.services.audit_service import record_operation
from app.services.wechat_draft_worker import recover_stale as recover_drafts


def status(conn, minutes):
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=minutes)
    return {
        'stale_running_jobs':conn.execute(text("SELECT count(*) FROM async_jobs WHERE status='running' AND updated_at<:cutoff"),{'cutoff':cutoff}).scalar_one(),
        'stale_pending_jobs':conn.execute(text("SELECT count(*) FROM async_jobs j WHERE j.status='pending' AND j.updated_at<:cutoff AND EXISTS (SELECT 1 FROM outbox_events e WHERE e.status='dispatched' AND e.payload->'kwargs'->>'job_id'=j.id::text)"),{'cutoff':cutoff}).scalar_one(),
        'pending_outbox':conn.execute(text("SELECT count(*) FROM outbox_events WHERE status='pending'")).scalar_one(),
        'failed_outbox':conn.execute(text("SELECT count(*) FROM outbox_events WHERE status='failed'")).scalar_one(),
        'unknown_publications':conn.execute(text("SELECT count(*) FROM publish_orders WHERE status='unknown'")).scalar_one(),
        'unknown_drafts':conn.execute(text("SELECT count(*) FROM wechat_draft_deliveries WHERE status='unknown'")).scalar_one(),
    }


def recover_once(engine, settings, user_id=None):
    # Release job locks before business locks; late workers see inactive jobs.
    with engine.begin() as conn:
        reaped=async_job_service.reap_stale_jobs(conn,settings.job_stale_timeout_minutes)
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=settings.job_stale_timeout_minutes)
    with engine.begin() as conn:
        # A broker delivery can be lost before claim when the database is down.
        # Reuse the original event/job; atomic claim still prevents double work.
        recovered_pending = conn.execute(text("""
WITH candidates AS (
 SELECT j.id FROM async_jobs j WHERE j.status='pending' AND j.updated_at<:cutoff
 AND EXISTS (SELECT 1 FROM outbox_events e WHERE e.status='dispatched' AND e.payload->'kwargs'->>'job_id'=j.id::text)
 FOR UPDATE OF j SKIP LOCKED
), touched AS (
 UPDATE async_jobs j SET updated_at=now() FROM candidates c WHERE j.id=c.id RETURNING j.id
)
UPDATE outbox_events e SET status='pending',available_at=now(),last_error=NULL
FROM touched j WHERE e.status='dispatched' AND e.payload->'kwargs'->>'job_id'=j.id::text
RETURNING e.id
"""),{'cutoff':cutoff}).all()
        recover_drafts(conn,settings.job_stale_timeout_minutes)
        conn.execute(text("UPDATE publish_attempts SET status='unknown',error_code='worker_interrupted' WHERE status='submitting' AND order_id IN (SELECT id FROM publish_orders WHERE status='submitting' AND updated_at<:cutoff)"),{'cutoff':cutoff})
        conn.execute(text("UPDATE publish_orders SET status='unknown',error_code='worker_interrupted',updated_at=now() WHERE status='submitting' AND updated_at<:cutoff"),{'cutoff':cutoff})
        conn.execute(text("UPDATE publish_attempts SET status='failed',error_code='preparation_interrupted',finished_at=now() WHERE status='preparing' AND order_id IN (SELECT id FROM publish_orders WHERE status='preparing' AND updated_at<:cutoff)"),{'cutoff':cutoff})
        conn.execute(text("UPDATE publish_orders SET status='failed',error_code='preparation_interrupted',updated_at=now() WHERE status='preparing' AND updated_at<:cutoff"),{'cutoff':cutoff})
        for table in ['creation_tasks','material_embedding_runs']:
            conn.execute(text(f"UPDATE {table} t SET status='failed',error_code='worker_interrupted',finished_at=now(),updated_at=now() FROM async_jobs j WHERE t.async_job_id=j.id AND t.status='running' AND j.status='failed' AND j.last_error='worker interrupted'"))
        conn.execute(text("UPDATE collection_runs r SET status='failed',error='worker_interrupted',lease_token=NULL,lease_until=NULL,finished_at=now(),updated_at=now() FROM async_jobs j WHERE r.async_job_id=j.id AND r.status='running' AND j.status='failed' AND j.last_error='worker interrupted' AND (r.lease_until IS NULL OR r.lease_until<now())"))
        record_operation(conn,user_id=user_id,action='runtime.recover',object_type='async_job',detail={'count':len(reaped),'recovered_pending':len(recovered_pending)})
        result=status(conn,settings.job_stale_timeout_minutes)
    return {'reaped':len(reaped),'recovered_pending':len(recovered_pending),**result}


def retry_outbox(conn,event_id,user_id):
    row=conn.execute(text('SELECT * FROM outbox_events WHERE id=:id FOR UPDATE'),{'id':str(event_id)}).mappings().first()
    if not row:
        raise ApiError(404,'not_found','投递记录不存在')
    try:
        job_id=UUID((row['payload'] or {}).get('kwargs',{}).get('job_id',''))
    except (ValueError,TypeError,AttributeError):
        raise ApiError(409,'outbox_recovery_blocked','该事件须由对应业务页面处理') from None
    job=async_job_service.get_job(conn,str(job_id))
    if row['status']!='failed' or not job or job['status']!='pending':
        raise ApiError(409,'outbox_recovery_blocked','仅未执行任务的明确投递失败可恢复；外部结果未知须在业务页面核对')
    conn.execute(text("UPDATE outbox_events SET status='pending',attempts=0,last_error=NULL,available_at=now() WHERE id=:id"),{'id':str(event_id)})
    record_operation(conn,user_id=user_id,action='outbox.retry',object_type='outbox_event',object_id=event_id)
    return {'id':str(event_id),'status':'pending','async_job_id':str(job_id)}
