"""Schedule rule windows and consume material-ready events transactionally."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import text

from app.errors import ApiError
from app.services.creation_service import get_rule, prepare_rule_retrieval, run_rule


def schedule_rules(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("schedule time must include timezone")
    created, errors = [], []
    rules = conn.execute(text("SELECT id,trigger_type,trigger_config,created_at FROM creation_rules WHERE enabled ORDER BY id")).mappings().all()
    # Embedding requests happen before the scheduler acquires rule or outbox locks.
    retrievals = {rule['id']: prepare_rule_retrieval(conn, get_rule(conn, rule['id'])) if rule['trigger_type'] != 'manual' else None for rule in rules}
    for rule in rules:
        if rule["trigger_type"] == "schedule":
            local_time = now.astimezone(ZoneInfo(rule["trigger_config"].get("timezone", "Asia/Shanghai")))
            if croniter.match(rule["trigger_config"].get("cron", ""), local_time):
                window = now.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
                try:
                    with conn.begin_nested():
                        result = run_rule(conn, rule["id"], "schedule", window, trigger_source="beat", retrieval=retrievals[rule['id']], retrieval_prepared=True)
                    if not result["reused"]:
                        created.append(str(result["resource_id"]))
                except ApiError as exc:
                    errors.append({"rule_id": str(rule["id"]), "code": exc.code})
        elif rule["trigger_type"] == "collection_completed":
            runs = conn.execute(text(
                "SELECT run.id FROM collection_runs run WHERE run.status IN ('succeeded','partial') "
                "AND run.finished_at>=:since AND (NOT EXISTS(SELECT 1 FROM creation_rule_collection_tasks rc WHERE rc.rule_id=:rule) "
                "OR EXISTS(SELECT 1 FROM creation_rule_collection_tasks rc WHERE rc.rule_id=:rule AND rc.collection_task_id=run.task_id)) "
                "AND NOT EXISTS(SELECT 1 FROM creation_tasks ct WHERE ct.rule_id=:rule AND ct.trigger_type='collection_completed' "
                "AND ct.trigger_window=CAST(run.id AS text) AND ct.source_task_id IS NULL) ORDER BY run.finished_at,run.id LIMIT 100"
            ), {"since": rule["created_at"], "rule": rule["id"]}).scalars().all()
            for run_id in runs:
                try:
                    with conn.begin_nested():
                        result = run_rule(conn, rule["id"], "collection_completed", str(run_id), trigger_source=str(run_id), retrieval=retrievals[rule['id']], retrieval_prepared=True)
                    if not result["reused"]:
                        created.append(str(result["resource_id"]))
                except ApiError as exc:
                    errors.append({"rule_id": str(rule["id"]), "code": exc.code})

    events = conn.execute(text("SELECT id,aggregate_id,payload,created_at FROM outbox_events WHERE event_type='material.ready' AND status='pending' AND NOT (payload ? 'task') ORDER BY created_at,id LIMIT 100 FOR UPDATE SKIP LOCKED")).mappings().all()
    for event in events:
        current = conn.execute(text("SELECT 1 FROM materials m JOIN material_ready_events e ON e.material_id=m.id AND e.material_revision_id=m.current_revision_id WHERE m.id=:material AND CAST(m.current_revision_id AS text)=:revision AND m.deleted_at IS NULL AND m.usage_status NOT IN ('archived','pending_review','duplicate')"), {'material': event['aggregate_id'], 'revision': event['payload'].get('revision_id')}).first()
        if not current:
            conn.execute(text("UPDATE outbox_events SET status='dispatched',dispatched_at=now() WHERE id=:id"), {'id': event['id']})
            continue
        failed = False
        for rule in rules:
            if rule["trigger_type"] != "new_material_count" or event["created_at"] < rule["created_at"]:
                continue
            matches = conn.execute(text(
                "SELECT NOT EXISTS(SELECT 1 FROM creation_rule_collection_tasks rc WHERE rc.rule_id=:rule) OR "
                "EXISTS(SELECT 1 FROM collection_results cr JOIN collection_runs rr ON rr.id=cr.run_id "
                "JOIN creation_rule_collection_tasks rc ON rc.collection_task_id=rr.task_id "
                "WHERE rc.rule_id=:rule AND cr.material_id=:material)"
            ), {"rule": rule["id"], "material": event["aggregate_id"]}).scalar_one()
            if not matches:
                continue
            try:
                with conn.begin_nested():
                    result = run_rule(conn, rule["id"], "new_material_count", str(event["id"]), trigger_source=str(event["id"]), retrieval=retrievals[rule['id']], retrieval_prepared=True)
                    conn.execute(text("INSERT INTO creation_consumed_events(event_id,rule_id,creation_task_id) VALUES (:event,:rule,:task) ON CONFLICT DO NOTHING"), {"event": event["id"], "rule": rule["id"], "task": result["resource_id"]})
                if not result["reused"]:
                    created.append(str(result["resource_id"]))
            except ApiError as exc:
                errors.append({"rule_id": str(rule["id"]), "code": exc.code})
                failed = True
        if not failed:
            conn.execute(text("UPDATE outbox_events SET status='dispatched',dispatched_at=now() WHERE id=:id"), {"id": event["id"]})
    return {"created": created, "errors": errors}
