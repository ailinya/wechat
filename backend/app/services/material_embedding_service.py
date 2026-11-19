"""Revision-scoped chunking, embedding jobs and idempotent rebuilds."""

from __future__ import annotations

import hashlib
import json
import time
from uuid import uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError

from app.adapters import embedding_client
from app.errors import ApiError
from app.modules.async_execution.registry import JobCancelled
from app.services import async_job_service, outbox_service

JOB_TASK = "app.modules.async_execution.tasks.run_async_job"
MODEL_CONFIG_NAME = "Environment embedding"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 100


def _persist_embedding_batch(engine, job_id, batch, vectors, done, total):
    """Retry the whole transaction if shared-vector registration deadlocks."""
    for attempt in range(3):
        try:
            with engine.begin() as conn:
                status = conn.execute(
                    text("SELECT status FROM async_jobs WHERE id=:id FOR UPDATE"),
                    {"id": job_id},
                ).scalar_one_or_none()
                if status != "running":
                    raise JobCancelled()
                for row, vector in zip(batch, vectors, strict=True):
                    encoded = "[" + ",".join(format(value, ".9g") for value in vector) + "]"
                    conn.execute(
                        text("UPDATE material_chunks SET embedding=CAST(:vector AS vector) WHERE id=:id AND embedding IS NULL"),
                        {"vector": encoded, "id": row["id"]},
                    )
                async_job_service.update_progress(conn, job_id, "embedding", int(done * 95 / max(1, total)))
            return
        except OperationalError as exc:
            if getattr(exc.orig, "sqlstate", None) != "40P01" or attempt == 2:
                raise
            time.sleep((attempt + 1) * 0.1)


def chunk_text(content: str) -> list[dict[str, str | int]]:
    """Split immutable Markdown into deterministic overlapping character windows."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_SIZE, len(normalized))
        body = normalized[start:end].strip()
        if body:
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "content": body,
                    "content_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                }
            )
        if end == len(normalized):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def ensure_environment_embedding_config(conn: Connection) -> dict:
    from app.credentials import resolve_setting

    model = resolve_setting("EMBEDDING_MODEL") or "qwen3.7-text-embedding-flash"
    base_url = (
        resolve_setting("EMBEDDING_BASE_URL")
        or "https://cn-beijing.maas.qianwenaiapi.com/api/v1"
    ).rstrip("/")
    try:
        dimension = int(resolve_setting("EMBEDDING_DIMENSION") or "1024")
    except ValueError:
        # Preserve the material and let its asynchronous build report the error.
        dimension = -1
    params = json.dumps({"dimension": dimension}, ensure_ascii=False)
    fingerprint = hashlib.sha256(
        json.dumps([model, base_url, dimension], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    config_name = f"{MODEL_CONFIG_NAME} {fingerprint}"
    row = conn.execute(
        text(
            "INSERT INTO model_configs "
            "(name,provider,purpose,endpoint,model_name,credential_ref,enabled,params) "
            "VALUES (:name,'qwen-maas','embedding',:endpoint,:model,'OPENAI_API_KEY',true,CAST(:params AS jsonb)) "
            "ON CONFLICT (name) DO UPDATE SET name=model_configs.name "
            "RETURNING id,config_version,model_name,endpoint,params,provider,purpose,credential_ref,enabled"
        ),
        {
            "name": config_name,
            "endpoint": base_url,
            "model": model,
            "params": params,
        },
    ).mappings().one()
    result = dict(row)
    if (result["provider"] != "qwen-maas" or result["purpose"] != "embedding"
        or result["model_name"] != model or result["endpoint"] != base_url
        or result["credential_ref"] != "OPENAI_API_KEY"
        or result["params"] != {"dimension": dimension}):
        raise ApiError(409, "embedding_configuration_conflict", "向量模型配置发生冲突")
    return result


def enqueue_rebuild(
    conn: Connection,
    material_id,
    *,
    revision_id=None,
    user_id=None,
) -> dict:
    material = (
        conn.execute(
            text(
                "SELECT id,current_revision_id,deleted_at,usage_status FROM materials "
                "WHERE id=:id FOR UPDATE"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .first()
    )
    if not material:
        raise ApiError(404, "not_found", "素材不存在")
    if material["deleted_at"] or material["usage_status"] == "archived":
        raise ApiError(409, "material_unavailable", "归档素材不可重建向量")
    selected_revision_id = revision_id or material["current_revision_id"]
    revision = (
        conn.execute(
            text(
                "SELECT id,content_markdown FROM material_revisions "
                "WHERE id=:revision AND material_id=:material FOR UPDATE"
            ),
            {"revision": str(selected_revision_id), "material": str(material_id)},
        )
        .mappings()
        .first()
    )
    if not revision:
        raise ApiError(404, "revision_not_found", "素材修订不存在")
    config = ensure_environment_embedding_config(conn)
    run = (
        conn.execute(
            text(
                "SELECT * FROM material_embedding_runs WHERE material_revision_id=:revision "
                "AND embedding_model_config_id=:config AND embedding_config_version=:version FOR UPDATE"
            ),
            {
                "revision": str(selected_revision_id),
                "config": config["id"],
                "version": config["config_version"],
            },
        )
        .mappings()
        .first()
    )
    if run:
        job = async_job_service.get_job(conn, str(run["async_job_id"])) if run["async_job_id"] else None
        if run["status"] == "succeeded" and job:
            return {
                "async_job_id": str(job["id"]), "resource_id": str(selected_revision_id), "revision_id": str(selected_revision_id),
                "status": job["status"], "reused": True,
            }
        if job and job["status"] in ("pending", "running"):
            return {
                "async_job_id": str(job["id"]), "resource_id": str(selected_revision_id), "revision_id": str(selected_revision_id),
                "status": job["status"], "reused": True,
            }

    run_id = str(run["id"]) if run else str(uuid4())
    job = async_job_service.create_job(
        conn,
        "material.embedding",
        "material_revision",
        selected_revision_id,
        payload={
            "run_id": run_id,
            "material_id": str(material_id),
            "revision_id": str(selected_revision_id),
            "model_config_id": str(config["id"]),
            "config_version": config["config_version"],
            "model_name": config["model_name"],
            "base_url": config["endpoint"],
            "dimension": int((config.get("params") or {}).get("dimension", 1024)),
        },
        created_by=user_id,
    )
    if run:
        conn.execute(
            text(
                "UPDATE material_embedding_runs SET async_job_id=:job,status='pending', "
                "attempts=attempts+1,error_code=NULL,finished_at=NULL,updated_at=now() WHERE id=:id"
            ),
            {"job": job["id"], "id": run_id},
        )
    else:
        conn.execute(
            text(
                "INSERT INTO material_embedding_runs "
                "(id,material_revision_id,embedding_model_config_id,embedding_config_version,async_job_id) "
                "VALUES (:id,:revision,:config,:version,:job)"
            ),
            {
                "id": run_id, "revision": str(selected_revision_id), "config": config["id"],
                "version": config["config_version"], "job": job["id"],
            },
        )
    outbox_service.publish_event(
        conn,
        "material.embedding.requested",
        "material_revision",
        selected_revision_id,
        payload={"task": JOB_TASK, "kwargs": {"job_id": job["id"]}},
    )
    return {
        "async_job_id": str(job["id"]),
        "resource_id": str(selected_revision_id),
        "revision_id": str(selected_revision_id),
        "status": "pending",
        "reused": False,
    }


def material_embedding_job(engine, job: dict) -> None:
    payload = job["payload"]
    run_id = payload["run_id"]
    config_id = payload["model_config_id"]
    revision_id = payload["revision_id"]
    try:
        with engine.begin() as conn:
            if not async_job_service.is_active(conn, job["id"]):
                raise JobCancelled()
            run = conn.execute(
                text("SELECT * FROM material_embedding_runs WHERE id=:id FOR UPDATE"),
                {"id": run_id},
            ).mappings().one()
            if str(run["async_job_id"]) != str(job["id"]):
                raise JobCancelled()
            enabled = conn.execute(
                text("SELECT enabled FROM model_configs WHERE id=:id AND config_version=:version"),
                {"id": config_id, "version": payload["config_version"]},
            ).scalar_one_or_none()
            if not enabled:
                raise embedding_client.EmbeddingError("embedding_model_disabled", "向量模型不可用或配置已变化")
            if run["status"] == "succeeded":
                return
            revision = conn.execute(
                text("SELECT content_markdown FROM material_revisions WHERE id=:id"),
                {"id": revision_id},
            ).mappings().one()
            chunks = chunk_text(revision["content_markdown"])
            for chunk in chunks:
                conn.execute(
                    text(
                        "INSERT INTO material_chunks (material_revision_id,chunk_index,content,content_hash, "
                        "embedding_model_config_id,embedding_config_version,embedding_model_name) "
                        "VALUES (:revision,:index,:content,:hash,:config,:version,:model) "
                        "ON CONFLICT (material_revision_id,chunk_index,embedding_model_config_id,embedding_config_version) "
                        "DO NOTHING"
                    ),
                    {
                        "revision": revision_id, "index": chunk["chunk_index"],
                        "content": chunk["content"], "hash": chunk["content_hash"],
                        "config": config_id, "version": payload["config_version"],
                        "model": payload["model_name"],
                    },
                )
            pending = conn.execute(
                text(
                    "SELECT id,content FROM material_chunks WHERE material_revision_id=:revision "
                    "AND embedding_model_config_id=:config AND embedding_config_version=:version "
                    "AND embedding IS NULL ORDER BY chunk_index"
                ),
                {"revision": revision_id, "config": config_id, "version": payload["config_version"]},
            ).mappings().all()
            conn.execute(
                text("UPDATE material_embedding_runs SET status='running',error_code=NULL,updated_at=now() WHERE id=:id"),
                {"id": run_id},
            )

        from app.credentials import resolve_setting

        if not chunks:
            raise embedding_client.EmbeddingError("empty_material", "素材正文为空，无法构建向量")
        try:
            batch_size = int(resolve_setting("EMBEDDING_BATCH_SIZE") or "10")
        except ValueError:
            raise embedding_client.EmbeddingError(
                "embedding_configuration_error", "向量批次大小无效"
            ) from None
        if batch_size < 1 or batch_size > 100:
            raise embedding_client.EmbeddingError(
                "embedding_configuration_error", "向量批次大小无效"
            )
        for offset in range(0, len(pending), batch_size):
            with engine.begin() as conn:
                if not async_job_service.is_active(conn, job["id"]):
                    raise JobCancelled()
            batch = pending[offset : offset + batch_size]
            vectors, _usage = embedding_client.embed_texts(
                [row["content"] for row in batch],
                expected_model=payload["model_name"],
                expected_base_url=payload["base_url"],
                expected_dimension=payload["dimension"],
            )
            done = min(offset + len(batch), len(pending))
            _persist_embedding_batch(engine, job["id"], batch, vectors, done, len(pending))
        with engine.begin() as conn:
            status = conn.execute(
                text("SELECT status FROM async_jobs WHERE id=:id FOR UPDATE"),
                {"id": job["id"]},
            ).scalar_one_or_none()
            if status != "running":
                raise JobCancelled()
            conn.execute(
                text("UPDATE material_embedding_runs SET status='succeeded',error_code=NULL,finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job"),
                {"id": run_id, "job": job["id"]},
            )
    except JobCancelled:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE material_embedding_runs SET status='failed',error_code='cancelled',finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job"),
                {"id": run_id, "job": job["id"]},
            )
        raise
    except Exception as exc:
        error_code = getattr(exc, "code", "embedding_failed")
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE material_embedding_runs SET status='failed',error_code=:error,finished_at=now(),updated_at=now() WHERE id=:id AND async_job_id=:job"),
                {"error": str(error_code)[:128], "id": run_id, "job": job["id"]},
            )
        raise RuntimeError(str(error_code)) from None
