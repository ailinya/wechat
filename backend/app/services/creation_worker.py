"""Tool-free LangGraph draft pipeline with transactional, idempotent slots."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from app.adapters.model_client import ModelClient, effective_text_config
from app.modules.async_execution.registry import JobCancelled
from app.services import async_job_service
from app.services.creation_service import generation_config
from app.schemas.creation import GeneratedDraft


class DraftState(TypedDict, total=False):
    task: dict
    materials: list[dict]
    model: dict
    client: Any
    draft: dict
    usage: dict
    evidence: list[dict]


def validate_inputs(state: DraftState):
    if not state["materials"] or any(not row["content"].strip() for row in state["materials"]):
        raise ValueError("body_unavailable")
    return {}


def generate_draft(state: DraftState):
    options = {**state["task"]["config_snapshot"], "existing_evidence": state.get("evidence", [])}
    result = state["client"].generate(state["model"], topic=state["task"]["topic"], materials=state["materials"], options=options)
    return {"draft": result["draft"].model_dump(mode="json"), "usage": result.get("usage") or {}}


def validate_output(state: DraftState):
    draft = GeneratedDraft.model_validate(state["draft"])
    allowed = {(str(item["material_id"]), str(item["revision_id"])) for item in state["materials"]}
    if any((str(item.material_id), str(item.revision_id)) not in allowed for item in draft.citations):
        raise ValueError("invalid_citation")
    return {}


def analyze_inputs(state: DraftState):
    """Reuse only current-revision analysis facts with quotes in the input."""
    evidence = []
    for material in state["materials"]:
        analysis = material.get("analysis") or {}
        for fact in analysis.get("facts", []):
            quote = fact.get("quote", "") if isinstance(fact, dict) else ""
            if quote and " ".join(quote.split()) in " ".join(material["content"].split()):
                evidence.append({"material_id": str(material["material_id"]), "revision_id": str(material["revision_id"]), "statement": fact.get("statement", ""), "quote": quote})
    return {"evidence": evidence}


def build_graph():
    graph = StateGraph(DraftState)
    graph.add_node("input", validate_inputs)
    graph.add_node("analysis", analyze_inputs)
    graph.add_node("generate", generate_draft)
    graph.add_node("validate", validate_output)
    graph.add_edge(START, "input")
    graph.add_edge("input", "analysis")
    graph.add_edge("analysis", "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


def creation_job(engine, job: dict, client=None):
    task_id = job["payload"]["creation_task_id"]
    try:
        with engine.begin() as conn:
            task = conn.execute(text("SELECT * FROM creation_tasks WHERE id=:id FOR UPDATE"), {"id": task_id}).mappings().one()
            if str(task["async_job_id"]) != str(job["id"]) or not async_job_service.is_active(conn, job["id"]):
                raise JobCancelled()
            if task["status"] == "succeeded":
                return
            task = dict(task)
            config = effective_text_config(generation_config(conn, task["config_snapshot"]["model_config_id"]))
            materials = [dict(row) for row in conn.execute(text(
                "SELECT c.material_id,c.material_revision_id AS revision_id,m.title,r.content_markdown AS content, "
                "(SELECT a.suggestions FROM collection_analyses a WHERE a.material_revision_id=r.id AND a.material_id=m.id AND a.status='succeeded' AND NOT a.stale ORDER BY a.created_at DESC LIMIT 1) AS analysis "
                "FROM creation_task_materials c JOIN materials m ON m.id=c.material_id "
                "JOIN material_revisions r ON r.id=c.material_revision_id WHERE c.creation_task_id=:id AND c.selected "
                "ORDER BY c.material_id"
            ), {"id": task_id}).mappings().all()]
            conn.execute(text("UPDATE creation_tasks SET status='running',error_code=NULL,started_at=COALESCE(started_at,now()),updated_at=now() WHERE id=:id"), {"id": task_id})
            completed = set(conn.execute(text("SELECT slot FROM creation_outputs WHERE creation_task_id=:id"), {"id": task_id}).scalars().all())
        graph = build_graph()
        count = int(task["config_snapshot"].get("batch_count", 1))
        for slot in range(1, count + 1):
            if slot in completed:
                continue
            with engine.connect() as conn:
                if not async_job_service.is_active(conn, job["id"]):
                    raise JobCancelled()
            output = graph.invoke({"task": task, "materials": materials, "model": config, "client": client or ModelClient(max_attempts=1)})
            draft = output["draft"]
            with engine.begin() as conn:
                status = conn.execute(text("SELECT status FROM async_jobs WHERE id=:id FOR UPDATE"), {"id": job["id"]}).scalar_one_or_none()
                current = conn.execute(text("SELECT async_job_id,status FROM creation_tasks WHERE id=:id FOR UPDATE"), {"id": task_id}).mappings().one()
                if status != "running" or str(current["async_job_id"]) != str(job["id"]) or current["status"] == "cancelled":
                    raise JobCancelled()
                if conn.execute(text("SELECT 1 FROM creation_outputs WHERE creation_task_id=:id AND slot=:slot"), {"id": task_id, "slot": slot}).first():
                    continue
                article = conn.execute(text("INSERT INTO articles(creation_task_id,slot,origin_type,status,created_by) VALUES (:task,:slot,'generated','pending_review',:user) RETURNING id"), {"task": task_id, "slot": slot, "user": task["created_by"]}).scalar_one()
                revision = conn.execute(text("INSERT INTO article_revisions(article_id,version,title,summary,body_markdown,keywords,created_by) VALUES (:article,1,:title,:summary,:body,CAST(:keywords AS jsonb),:user) RETURNING id"), {"article": article, "title": draft["title"], "summary": draft["summary"], "body": draft["body_markdown"], "keywords": json.dumps(draft["keywords"], ensure_ascii=False), "user": task["created_by"]}).scalar_one()
                conn.execute(text("UPDATE articles SET current_revision_id=:revision WHERE id=:id"), {"id": article, "revision": revision})
                for index, citation in enumerate(draft["citations"], 1):
                    conn.execute(text("INSERT INTO article_materials(article_revision_id,material_id,material_revision_id,reference_order) VALUES (:article_revision,:material,:revision,:position)"), {"article_revision": revision, "material": citation["material_id"], "revision": citation["revision_id"], "position": index})
                snapshot = {"model_name": config["model_name"], "config_version": config["config_version"], "endpoint_hash": hashlib.sha256(config["endpoint"].encode()).hexdigest()}
                conn.execute(text("INSERT INTO creation_outputs(creation_task_id,slot,article_id,article_revision_id,title,candidate_titles,summary,outline,body_markdown,keywords,cover_suggestion,citations,model_config_id,model_snapshot) VALUES (:task,:slot,:article,:revision,:title,CAST(:titles AS jsonb),:summary,CAST(:outline AS jsonb),:body,CAST(:keywords AS jsonb),:cover,CAST(:citations AS jsonb),:model,CAST(:snapshot AS jsonb))"), {"task": task_id, "slot": slot, "article": article, "revision": revision, "title": draft["title"], "titles": json.dumps(draft["candidate_titles"], ensure_ascii=False), "summary": draft["summary"], "outline": json.dumps(draft["outline"], ensure_ascii=False), "body": draft["body_markdown"], "keywords": json.dumps(draft["keywords"], ensure_ascii=False), "cover": draft["cover_suggestion"], "citations": json.dumps(draft["citations"]), "model": config["id"], "snapshot": json.dumps(snapshot)})
                stage = json.dumps({"status": "succeeded", "article_id": str(article), "usage": output.get("usage") or {}})
                conn.execute(text("UPDATE creation_tasks SET stages=jsonb_set(stages,ARRAY[CAST(:slot AS text)],CAST(:stage AS jsonb),true),updated_at=now() WHERE id=:id"), {"slot": slot, "stage": stage, "id": task_id})
                async_job_service.update_progress(conn, job["id"], "generation", int(slot * 95 / count))
        with engine.begin() as conn:
            status = conn.execute(text("SELECT status FROM async_jobs WHERE id=:id FOR UPDATE"), {"id": job["id"]}).scalar_one_or_none()
            if status != "running":
                raise JobCancelled()
            conn.execute(text("UPDATE creation_tasks SET status='succeeded',finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job"), {"id": task_id, "job": job["id"]})
    except JobCancelled:
        with engine.begin() as conn:
            conn.execute(text("UPDATE creation_tasks SET status='cancelled',finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job AND status <> 'succeeded'"), {"id": task_id, "job": job["id"]})
        raise
    except Exception as exc:
        code = getattr(exc, "code", "creation_failed")
        with engine.begin() as conn:
            conn.execute(text("UPDATE creation_tasks SET status='failed',error_code=:code,finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job AND status <> 'cancelled'"), {"id": task_id, "job": job["id"], "code": str(code)[:128]})
        raise RuntimeError(str(code)) from None
