"""Transactional creation requests and rule management."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import text

from app.errors import ApiError
from app.repositories import model_config_repository
from app.services import async_job_service, outbox_service

JOB_TASK = "app.modules.async_execution.tasks.run_async_job"
RULE_COLUMNS = ("name", "description", "topic", "trigger_type", "material_strategy", "min_new_material_count", "min_material_count", "min_relevance", "reference_count", "batch_count", "article_type", "writing_style", "min_words", "max_words", "model_config_id", "prompt", "require_analysis", "target_account_id", "enabled")


def generation_config(conn, config_id):
    config = model_config_repository.get_config(conn, config_id)
    if not config or not config["enabled"] or config["purpose"] != "generation":
        raise ApiError(409, "model_unavailable", "生成模型不可用或用途不正确")
    return config


def get_rule(conn, rule_id):
    row = conn.execute(text("SELECT * FROM creation_rules WHERE id=:id"), {"id": str(rule_id)}).mappings().first()
    if not row:
        raise ApiError(404, "not_found", "创作规则不存在")
    result = dict(row)
    result["collection_task_ids"] = conn.execute(text("SELECT collection_task_id FROM creation_rule_collection_tasks WHERE rule_id=:id ORDER BY collection_task_id"), {"id": str(rule_id)}).scalars().all()
    return result


def save_rule(conn, payload, user_id, rule_id=None):
    generation_config(conn, payload.model_config_id)
    if payload.target_account_id:
        from app.services.wechat_account_service import account, require_available
        target = account(conn, payload.target_account_id)
        if payload.enabled:
            require_available(target, 'drafts')
    data = payload.model_dump(mode="json")
    for task_id in data["collection_task_ids"]:
        if not conn.execute(text("SELECT 1 FROM collection_tasks WHERE id=:id AND status <> 'archived'"), {"id": task_id}).first():
            raise ApiError(422, "collection_task_unavailable", "关联采集任务不存在或已删除")
    params = {key: data[key] for key in RULE_COLUMNS}
    params.update({"trigger_config": json.dumps(data["trigger_config"], ensure_ascii=False), "filters": json.dumps(data["filters"], ensure_ascii=False)})
    if rule_id:
        get_rule(conn, rule_id)
        params["id"] = str(rule_id)
        assignments = ",".join(f"{key}=:{key}" for key in RULE_COLUMNS)
        conn.execute(text(f"UPDATE creation_rules SET {assignments}, trigger_config=CAST(:trigger_config AS jsonb), filters=CAST(:filters AS jsonb), updated_at=now() WHERE id=:id"), params)
        conn.execute(text("DELETE FROM creation_rule_collection_tasks WHERE rule_id=:id"), {"id": str(rule_id)})
    else:
        columns = ",".join(RULE_COLUMNS)
        values = ",".join(f":{key}" for key in RULE_COLUMNS)
        params["created_by"] = str(user_id) if user_id else None
        rule_id = conn.execute(text(f"INSERT INTO creation_rules ({columns},trigger_config,filters,created_by) VALUES ({values},CAST(:trigger_config AS jsonb),CAST(:filters AS jsonb),:created_by) RETURNING id"), params).scalar_one()
    for task_id in data["collection_task_ids"]:
        conn.execute(text("INSERT INTO creation_rule_collection_tasks(rule_id,collection_task_id) VALUES (:rule,:task)"), {"rule": str(rule_id), "task": task_id})
    return get_rule(conn, rule_id)


def list_rules(conn, page, page_size):
    total = conn.execute(text("SELECT count(*) FROM creation_rules")).scalar_one()
    ids = conn.execute(text("SELECT id FROM creation_rules ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"), {"limit": page_size, "offset": (page - 1) * page_size}).scalars().all()
    return {"items": [get_rule(conn, row) for row in ids], "total": total, "page": page, "page_size": page_size}


def get_task(conn, task_id):
    row = conn.execute(text("SELECT * FROM creation_tasks WHERE id=:id"), {"id": str(task_id)}).mappings().first()
    if not row:
        raise ApiError(404, "not_found", "创作任务不存在")
    result = dict(row)
    result["materials"] = [dict(item) for item in conn.execute(text("SELECT material_id,material_revision_id AS revision_id FROM creation_task_materials WHERE creation_task_id=:id AND selected ORDER BY material_id"), {"id": str(task_id)}).mappings().all()]
    result["candidates"] = [dict(item) for item in conn.execute(text("SELECT material_id,material_revision_id AS revision_id,selected,relevance_score,selection_reason FROM creation_task_materials WHERE creation_task_id=:id ORDER BY selected DESC,material_id"), {"id": str(task_id)}).mappings().all()]
    return result


def list_tasks(conn, page, page_size):
    total = conn.execute(text("SELECT count(*) FROM creation_tasks")).scalar_one()
    rows = conn.execute(text("SELECT * FROM creation_tasks ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"), {"limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    return {"items": [get_task(conn, row["id"]) for row in rows], "total": total, "page": page, "page_size": page_size}


def create_manual(conn, payload, user_id, request_key=None, *, allow_duplicate=False):
    from app.services.material_search_service import terms
    data = payload.model_dump(mode="json")
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    if request_key:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": f"creation:{user_id}:{request_key}"})
        existing = conn.execute(text("SELECT * FROM creation_tasks WHERE created_by=:user AND request_key=:key"), {"user": str(user_id), "key": request_key}).mappings().first()
        if existing:
            if existing["request_fingerprint"] != fingerprint:
                raise ApiError(409, "idempotency_conflict", "同一幂等键不能用于不同请求")
            return {"async_job_id": existing["async_job_id"], "resource_id": existing["id"], "status": existing["status"], "decision": existing["decision"], "reused": True}
    generation_config(conn, payload.model_config_id)
    revisions = []
    for item in sorted(payload.materials, key=lambda value: str(value.material_id)):
        row = conn.execute(text("SELECT m.id,m.current_revision_id,m.deleted_at,m.usage_status,r.content_markdown FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id WHERE m.id=:id FOR UPDATE OF m"), {"id": str(item.material_id)}).mappings().first()
        if not row or row["deleted_at"] or row["usage_status"] == "archived":
            raise ApiError(409, "material_unavailable", "选择的素材不可用")
        if str(row["current_revision_id"]) != str(item.revision_id):
            raise ApiError(409, "material_revision_changed", "素材正文已更新，请重新选择")
        revisions.append(row)
    reasons = []
    if len(revisions) < payload.min_material_count:
        reasons.append("material_count_insufficient")
    if any(not row["content_markdown"].strip() for row in revisions):
        reasons.append("body_unavailable")
    query_terms = terms(payload.topic)
    relevant_count = sum(not query_terms or len(query_terms & terms(row["content_markdown"])) / len(query_terms) >= payload.min_relevance for row in revisions)
    if relevant_count < payload.min_material_count and len(revisions) >= payload.min_material_count:
        reasons.append("relevance_insufficient")
    if payload.topic.strip():
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:topic,0))"), {"topic": "creation-topic:" + payload.topic.strip().casefold()})
        if not allow_duplicate and conn.execute(text("SELECT 1 FROM creation_tasks WHERE lower(btrim(topic))=lower(btrim(:topic)) AND status='succeeded' LIMIT 1"), {"topic": payload.topic}).first():
            reasons.append("duplicate_topic")
        if conn.execute(text("SELECT 1 FROM creation_tasks WHERE lower(btrim(topic))=lower(btrim(:topic)) AND status IN ('pending','running') LIMIT 1"), {"topic": payload.topic}).first():
            reasons.append("active_task")
    decision = {"status": "insufficient" if reasons else "satisfied", "reasons": reasons, "details": {"selected_count": len(revisions), "relevant_count": relevant_count}}
    status = "insufficient" if reasons else "pending"
    task_id = conn.execute(text("INSERT INTO creation_tasks(mode,topic,status,trigger_type,trigger_window,request_key,request_fingerprint,config_snapshot,decision,created_by) VALUES (:mode,:topic,:status,'manual',:window,:key,:fingerprint,CAST(:config AS jsonb),CAST(:decision AS jsonb),:user) RETURNING id"), {"mode": payload.mode, "topic": payload.topic, "status": status, "window": str(uuid4()), "key": request_key, "fingerprint": fingerprint, "config": canonical, "decision": json.dumps(decision), "user": str(user_id)}).scalar_one()
    for row in revisions:
        conn.execute(text("INSERT INTO creation_task_materials(creation_task_id,material_id,material_revision_id,selected,selection_reason) VALUES (:task,:material,:revision,true,'manual')"), {"task": task_id, "material": row["id"], "revision": row["current_revision_id"]})
    job_id = None
    if not reasons:
        job = async_job_service.create_job(conn, "creation.generate", "creation_task", task_id, payload={"creation_task_id": str(task_id)}, created_by=user_id)
        job_id = job["id"]
        conn.execute(text("UPDATE creation_tasks SET async_job_id=:job WHERE id=:id"), {"job": job_id, "id": task_id})
        outbox_service.publish_event(conn, "creation.generate.requested", "creation_task", task_id, payload={"task": JOB_TASK, "kwargs": {"job_id": job_id}})
    return {"async_job_id": job_id, "resource_id": task_id, "status": status, "decision": decision, "reused": False}


def cancel_task(conn, task_id):
    task = get_task(conn, task_id)
    if task["status"] not in ("pending", "running") or not task["async_job_id"]:
        raise ApiError(409, "invalid_task_state", "当前状态不能取消")
    if not async_job_service.finish_job(conn, str(task["async_job_id"]), "cancelled", "cancelled by user"):
        raise ApiError(409, "invalid_task_state", "任务状态已变化")
    conn.execute(text("UPDATE creation_tasks SET status='cancelled',finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job"), {"id": str(task_id), "job": task["async_job_id"]})
    return get_task(conn, task_id)


def retry_task(conn, task_id, user_id):
    task = conn.execute(text("SELECT * FROM creation_tasks WHERE id=:id FOR UPDATE"), {"id": str(task_id)}).mappings().first()
    if not task:
        raise ApiError(404, "not_found", "创作任务不存在")
    if task["status"] not in ("failed", "cancelled"):
        raise ApiError(409, "invalid_task_state", "只有失败或取消的任务可以重试")
    generation_config(conn, task["config_snapshot"]["model_config_id"])
    job = async_job_service.create_job(conn, "creation.generate", "creation_task", task_id, payload={"creation_task_id": str(task_id)}, created_by=user_id)
    conn.execute(text("UPDATE creation_tasks SET async_job_id=:job,status='pending',error_code=NULL,finished_at=NULL,updated_at=now() WHERE id=:id"), {"id": str(task_id), "job": job["id"]})
    outbox_service.publish_event(conn, "creation.generate.requested", "creation_task", task_id, payload={"task": JOB_TASK, "kwargs": {"job_id": job["id"]}})
    return {"async_job_id": job["id"], "resource_id": task_id, "status": "pending", "reused": False, "decision": task["decision"]}


def regenerate_task(conn, task_id, user_id):
    from app.schemas.creation import CreationTaskIn

    task = get_task(conn, task_id)
    if task["status"] in ("pending", "running"):
        raise ApiError(409, "active_task", "原任务仍在执行")
    settings = dict(task["config_snapshot"])
    request = CreationTaskIn(
        mode="topic" if task["topic"].strip() else "material",
        topic=task["topic"],
        materials=task["materials"],
        model_config_id=settings["model_config_id"],
        article_type=settings.get("article_type", "news"),
        writing_style=settings.get("writing_style", "客观"),
        min_words=settings.get("min_words", 300),
        max_words=settings.get("max_words", 1200),
        batch_count=settings.get("batch_count", 1),
        prompt=settings.get("prompt", ""),
        min_material_count=settings.get("min_material_count", 1),
        min_relevance=settings.get("min_relevance", 0),
    )
    result = create_manual(conn, request, user_id, allow_duplicate=True)
    conn.execute(text("UPDATE creation_tasks SET source_task_id=:source WHERE id=:id"), {"source": str(task_id), "id": result["resource_id"]})
    return result


def prepare_rule_retrieval(conn, rule):
    """Retrieve semantic scores before taking creation rule or event locks."""
    if rule['material_strategy'] != 'all' or not rule['topic'].strip():
        return None
    from app.schemas.materials import MaterialSearchIn
    from app.services.material_search_service import search

    response = search(conn, MaterialSearchIn(query=rule['topic'], scope='all', top_k=100))
    return {'topic': rule['topic'], 'mode': response['mode'], 'degraded': response['degraded'],
            'degradation_reason': response['degradation_reason'],
            'scores': {(str(item['material_id']), str(item['matched_revision_id'])): item['relevance_score'] for item in response['items']}}


def run_rule(conn, rule_id, trigger_type, window, *, trigger_source=None, user_id=None, retrieval=None, retrieval_prepared=False):
    """Reserve one rule/window and record its candidates and decisions atomically."""
    from app.services.material_search_service import terms

    if not retrieval_prepared:
        retrieval = prepare_rule_retrieval(conn, get_rule(conn, rule_id))
    locked = conn.execute(text("SELECT id,enabled FROM creation_rules WHERE id=:id FOR UPDATE"), {"id": str(rule_id)}).mappings().first()
    if not locked:
        raise ApiError(404, "not_found", "创作规则不存在")
    rule = get_rule(conn, rule_id)
    if retrieval and (rule['material_strategy'] != 'all' or retrieval['topic'] != rule['topic']):
        retrieval = None
    if not locked["enabled"]:
        raise ApiError(409, "rule_disabled", "创作规则已停用")
    if trigger_type != 'manual' and rule['trigger_type'] != trigger_type:
        raise ApiError(409, 'rule_trigger_changed', '规则触发方式已变更')
    existing = conn.execute(text("SELECT * FROM creation_tasks WHERE rule_id=:rule AND trigger_type=:trigger AND trigger_window=:window AND source_task_id IS NULL"), {"rule": str(rule_id), "trigger": trigger_type, "window": window}).mappings().first()
    if existing:
        return {"async_job_id": existing["async_job_id"], "resource_id": existing["id"], "status": existing["status"], "decision": existing["decision"], "reused": True}
    generation_config(conn, rule["model_config_id"])
    last_run = conn.execute(text("SELECT max(created_at) FROM creation_tasks WHERE rule_id=:id AND decision->>'status'='satisfied'"), {"id": str(rule_id)}).scalar_one()
    rows = conn.execute(text(
        "SELECT m.id,m.title,m.origin,m.usage_status,m.category_id,m.current_revision_id,r.content_markdown,m.created_at, "
        "EXISTS(SELECT 1 FROM material_ready_events e WHERE e.material_id=m.id AND e.material_revision_id=r.id AND e.created_at>=:since "
        "AND (NOT EXISTS(SELECT 1 FROM creation_rule_collection_tasks rc WHERE rc.rule_id=:rule) OR "
        "EXISTS(SELECT 1 FROM collection_results cr JOIN collection_runs rr ON rr.id=cr.run_id "
        "JOIN creation_rule_collection_tasks rc ON rc.collection_task_id=rr.task_id "
        "WHERE cr.material_id=m.id AND rc.rule_id=:rule))) AS is_new, "
        "EXISTS(SELECT 1 FROM collection_analyses a WHERE a.material_id=m.id) AS has_analysis, "
        "COALESCE((SELECT a.status='succeeded' AND NOT a.stale AND COALESCE(a.suggestions->>'relevance','not_applicable') IN ('relevant','not_applicable') FROM collection_analyses a WHERE a.material_id=m.id AND a.material_revision_id=r.id ORDER BY a.created_at DESC,a.id DESC LIMIT 1),false) AS analysis_ready "
        "FROM materials m JOIN material_revisions r ON r.id=m.current_revision_id "
        "WHERE m.deleted_at IS NULL AND m.usage_status <> 'archived' ORDER BY m.created_at DESC,m.id"
    ), {"since": last_run or rule["created_at"], "rule": str(rule_id)}).mappings().all()
    words = terms(rule["topic"])
    candidates = []
    for row in rows:
        if row["usage_status"] in ("pending_review", "duplicate"):
            continue
        if (rule["require_analysis"] or row["has_analysis"]) and not row["analysis_ready"]:
            continue
        filters = rule["filters"] or {}
        if filters.get("origins") and row["origin"] not in filters["origins"]:
            continue
        if filters.get("category_id") and str(row["category_id"]) != filters["category_id"]:
            continue
        if rule["material_strategy"] == "new_only" and not row["is_new"]:
            continue
        if rule["material_strategy"] == "new_and_unused" and not row["is_new"] and row["usage_status"] != "ready_to_use":
            continue
        lexical = len(words & terms(row["title"] + " " + row["content_markdown"])) / len(words) if words else 1.0
        score = retrieval['scores'].get((str(row['id']), str(row['current_revision_id'])), lexical) if retrieval else lexical
        candidates.append({**dict(row), "score": score})
    candidates.sort(key=lambda row: ((not row["is_new"]) if rule["material_strategy"] != 'all' else False, -row["score"], str(row["id"])))
    with_body = [row for row in candidates if row["content_markdown"].strip()]
    relevant = [row for row in with_body if row["score"] >= rule["min_relevance"]]
    new_count = sum(bool(row["is_new"]) for row in candidates)
    required_new = rule["min_new_material_count"]
    if trigger_type == "new_material_count":
        required_new = max(required_new, int(rule["trigger_config"].get("new_material_threshold", 1)))
    reasons = []
    if new_count < required_new:
        reasons.append("new_materials_insufficient")
    if len(candidates) < rule["min_material_count"]:
        reasons.append("material_count_insufficient")
    if len(with_body) < rule["min_material_count"] and len(candidates) >= rule["min_material_count"]:
        reasons.append("body_unavailable")
    if len(relevant) < rule["min_material_count"] and len(with_body) >= rule["min_material_count"]:
        reasons.append("relevance_insufficient")
    if rule["topic"].strip():
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:topic,0))"), {"topic": "creation-topic:" + rule["topic"].strip().casefold()})
        if conn.execute(text("SELECT 1 FROM creation_tasks WHERE lower(btrim(topic))=lower(btrim(:topic)) AND status='succeeded' LIMIT 1"), {"topic": rule["topic"]}).first():
            reasons.append("duplicate_topic")
        if conn.execute(text("SELECT 1 FROM creation_tasks WHERE (rule_id=:rule OR lower(btrim(topic))=lower(btrim(:topic))) AND status IN ('pending','running') LIMIT 1"), {"rule": str(rule_id), "topic": rule["topic"]}).first():
            reasons.append("active_task")
    elif conn.execute(text("SELECT 1 FROM creation_tasks WHERE rule_id=:rule AND status IN ('pending','running') LIMIT 1"), {"rule": str(rule_id)}).first():
        reasons.append("active_task")
    chosen = relevant[:rule["reference_count"]] if not reasons else []
    for selected in sorted(chosen, key=lambda item: str(item['id'])):
        current = conn.execute(text("SELECT current_revision_id,usage_status,deleted_at FROM materials WHERE id=:id FOR SHARE"), {'id': selected['id']}).mappings().first()
        if not current or current['deleted_at'] is not None or current['usage_status'] in ('archived', 'pending_review', 'duplicate') or current['current_revision_id'] != selected['current_revision_id']:
            raise ApiError(409, 'material_revision_changed', '素材已更新，请重新执行规则')
    decision = {"status": "insufficient" if reasons else "satisfied", "reasons": reasons,
                "details": {"new_count": new_count, "candidate_count": len(candidates), "eligible_count": len(relevant),
                            "retrieval_mode": retrieval['mode'] if retrieval else 'keyword_only',
                            "retrieval_degraded": retrieval['degraded'] if retrieval else False,
                            "retrieval_degradation_reason": retrieval['degradation_reason'] if retrieval else None}}
    status = "insufficient" if reasons else "pending"
    snapshot = {key: rule[key] for key in RULE_COLUMNS}
    snapshot.update({"trigger_config": rule["trigger_config"], "filters": rule["filters"], "collection_task_ids": rule["collection_task_ids"]})
    task_id = conn.execute(text("INSERT INTO creation_tasks(rule_id,mode,topic,status,trigger_type,trigger_source,trigger_window,config_snapshot,decision,created_by) VALUES (:rule,'automatic',:topic,:status,:trigger,:source,:window,CAST(:config AS jsonb),CAST(:decision AS jsonb),:user) RETURNING id"), {"rule": str(rule_id), "topic": rule["topic"], "status": status, "trigger": trigger_type, "source": trigger_source, "window": window, "config": json.dumps(snapshot, ensure_ascii=False, default=str), "decision": json.dumps(decision), "user": str(user_id) if user_id else None}).scalar_one()
    selected_ids = {row["id"] for row in chosen}
    for row in candidates:
        conn.execute(text("INSERT INTO creation_task_materials(creation_task_id,material_id,material_revision_id,selected,relevance_score,selection_reason) VALUES (:task,:material,:revision,:selected,:score,:reason)"), {"task": task_id, "material": row["id"], "revision": row["current_revision_id"], "selected": row["id"] in selected_ids, "score": row["score"], "reason": "new" if row["is_new"] else "historical"})
    job_id = None
    if not reasons:
        job = async_job_service.create_job(conn, "creation.generate", "creation_task", task_id, payload={"creation_task_id": str(task_id)}, created_by=user_id)
        job_id = job["id"]
        conn.execute(text("UPDATE creation_tasks SET async_job_id=:job WHERE id=:id"), {"id": task_id, "job": job_id})
        outbox_service.publish_event(conn, "creation.generate.requested", "creation_task", task_id, payload={"task": JOB_TASK, "kwargs": {"job_id": job_id}})
    return {"resource_id": task_id, "async_job_id": job_id, "status": status, "decision": decision, "reused": False}
