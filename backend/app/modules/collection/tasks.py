"""Collection job registrations and transactional Beat scheduling."""
from __future__ import annotations

from app.config import Settings
from app.database import session_for
from app.modules.async_execution.celery_app import celery_app
from app.modules.async_execution.registry import register_handler, register_engine_handler
from app.modules.collection.analysis_tasks import analyze_result_once, analysis_job_handler
from app.services import collection_service, materialization_service
from app.services.collection_pipeline import collection_job_handler
from app.services.material_revision_analysis import material_analysis_job
from app.services.material_comparison_service import comparison_job_handler

register_engine_handler("collection.run", collection_job_handler)
register_engine_handler("collection.analysis", analysis_job_handler)
register_engine_handler("material.analysis", material_analysis_job)
register_engine_handler("collection.comparison", comparison_job_handler)


def _materialize_result(ctx) -> None:
    ctx.checkpoint()
    materialization_service.materialize(
        ctx.conn, ctx.payload["result_id"], ctx.payload.get("user_id")
    )


def _retry_parse(ctx) -> None:
    ctx.checkpoint()
    materialization_service.retry_parse(ctx.conn, ctx.payload["result_id"])


register_handler("collection.materialize", _materialize_result)
register_handler("collection.retry_parse", _retry_parse)


@celery_app.task(name="app.modules.collection.tasks.analyze_result")
def analyze_result_task(result_id, model_config_id, topic=None, keywords=None):
    return analyze_result_once(result_id, model_config_id, topic=topic, keywords=keywords)


def schedule_collection_runs_once(settings: Settings | None = None) -> dict:
    settings = settings or Settings.model_validate({})
    with session_for(settings) as conn:
        with conn.begin():
            result = collection_service.schedule_due_runs(conn)
    return {"created": result["created"], "count": len(result["created"])}


@celery_app.task(name="app.modules.async_execution.tasks.schedule_collection_runs")
def schedule_collection_runs() -> dict:
    return schedule_collection_runs_once()
