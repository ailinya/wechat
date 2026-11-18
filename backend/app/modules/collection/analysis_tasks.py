"""Standalone model analysis handler; service owns its short transactions."""

from app.config import Settings
from app.database import get_engine
from app.services.material_analysis_service import analyze_result


def analyze_result_once(
    result_id, model_config_id, *, topic=None, keywords=None, engine=None, client=None
):
    engine = engine if engine is not None else get_engine(Settings.model_validate({}))
    return analyze_result(
        engine,
        result_id,
        {"id": model_config_id},
        topic=topic,
        keywords=keywords,
        client=client,
    )


def analysis_job_handler(engine, job):
    from app.errors import ApiError

    result = analyze_result_once(engine=engine, **job["payload"])
    if result["status"] == "failed":
        raise ApiError(422, result["error"], "素材分析失败")
    return result
