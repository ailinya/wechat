import hashlib
import json
import pytest

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.model_client import ModelClient
from app.repositories import collection_repository as repo
from app.services import materialization_service
from app.services.material_comparison_service import compare_result_history, _history


OLD_BODY = "AI 固件版本 2.1 修复输入法问题。"
NEW_BODY = "AI 固件版本 2.2 新增夜间模式，发布于本周。"


def _seed_result(session, title, url, body, key):
    conn = session.connection()
    source = repo.create_source(
        conn, name=f"source-{key}", source_type="web_page", base_url=f"https://example.com/{key}",
        description="", enabled=True, created_by=None,
    )
    task = repo.create_task(
        conn, name=f"task-{key}", keywords=[], time_range_days=7, schedule_frequency="manual",
        schedule_cron_expr=None, timezone="UTC", auto_materialize=False, auto_create=False,
        source_ids=[str(source["id"])], created_by=None,
    )
    run = repo.create_run(conn, task_id=task["id"], trigger="manual")
    result = repo.insert_result(
        conn, run_id=run["id"], source_id=source["id"], title=title, url=url,
        raw_content=f"<html><body><article><h1>{title}</h1><p>{body}</p></article></body></html>",
        dedup_key=key, parse_status="parsed",
    )
    return result["id"]


@pytest.mark.parametrize("verdict", ["new_progress", "duplicate", "uncertain"])
def test_comparison_persists_new_fact_and_target_revision_evidence(db_engine, verdict):
    with Session(db_engine) as session:
        old_result = _seed_result(session, "AI 固件发布", "https://example.com/old", OLD_BODY, "old")
        old_material = materialization_service.materialize(session.connection(), old_result, None)
        session.commit()
        new_result = _seed_result(session, "AI 固件发布", "https://example.com/new", NEW_BODY, "new")
        revision_id = session.execute(text(
            "SELECT current_revision_id FROM materials WHERE id=:id"
        ), {"id": old_material["material_id"]}).scalar_one()
        markdown = materialization_service.parsed_markdown(repo.get_result(session.connection(), new_result))
        digest = hashlib.sha256(markdown.encode()).hexdigest()
        session.execute(text(
            "INSERT INTO collection_snapshots (result_id, markdown, content_hash, extractor_version) "
            "VALUES (:id, :markdown, :hash, 'test/1')"
        ), {"id": new_result, "markdown": markdown, "hash": digest})
        config_id = session.execute(text(
            "INSERT INTO model_configs (name, provider, purpose, endpoint, model_name) "
            "VALUES ('compare fixture', 'test', 'analysis', 'https://example.com', 'fixture') RETURNING id"
        )).scalar_one()
        session.commit()

    config = {"id": str(config_id), "purpose": "analysis", "enabled": True,
        "endpoint": "https://example.com", "model_name": "fixture", "max_input_tokens": 8000,
        "max_output_tokens": 2000, "timeout_seconds": 10, "config_version": 1}
    output = {
        "summary": "新增夜间模式", "relevance": "not_applicable", "facts": [
            {"statement": "新增夜间模式", "quote": "新增夜间模式，发布于本周。", "ref_index": 0}
        ], "compare_verdict": verdict, "compare_target_revision_id": str(revision_id),
    }
    calls = []

    def transport(*_args):
        calls.append(1)
        return 200, {"choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}], "usage": {"total_tokens": 30}}

    outcome = compare_result_history(
        db_engine, str(new_result), config, keywords=["AI"],
        client=ModelClient(transport, max_attempts=1),
    )
    comparison = outcome["comparisons"][0]
    assert outcome["status"] == ("new_progress" if verdict == "new_progress" else "review_required")
    assert comparison["target_revision_id"] == str(revision_id)
    assert comparison["target_material_id"] == str(old_material["material_id"])
    assert comparison["suggestions"]["facts"][0]["quote"] == "新增夜间模式，发布于本周。"
    assert len(calls) == 1

    repeated = compare_result_history(
        db_engine, str(new_result), config, keywords=["AI"],
        client=ModelClient(transport, max_attempts=1),
    )
    assert repeated["status"] == outcome["status"] and len(calls) == 1
    if verdict != "new_progress":
        with db_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM material_relations")).scalar_one() == 0
        return

    decision = {
        "analysis_id": comparison["analysis_id"],
    }
    with Session(db_engine) as session:
        materialized = materialization_service.materialize(
            session.connection(), new_result, None, progress_decision=decision
        )
        session.commit()
    assert materialized["status"] == "new_progress"
    with db_engine.connect() as conn:
        relation = conn.execute(text(
            "SELECT relation_type FROM material_relations WHERE source_material_id=:id"
        ), {"id": materialized["material_id"]}).scalar_one()
        saved = conn.execute(text(
            "SELECT suggestions->>'compare_verdict' AS verdict FROM collection_analyses WHERE result_id=:id"
        ), {"id": new_result}).scalar_one()
    assert relation == "update_of" and saved == "new_progress"


def test_history_lookup_is_bounded_to_five_revisions(db_engine):
    with Session(db_engine) as session:
        for index in range(7):
            result_id = _seed_result(session, "AI 固件发布", f"https://example.com/{index}",
                                     f"AI 历史正文 {index}", f"history-{index}")
            materialization_service.materialize(session.connection(), result_id, None)
        session.commit()
    history = _history(db_engine, {"id": result_id, "url": "https://example.com/new", "title": "AI 固件发布"}, ["AI"])
    assert len(history) == 5
    assert len({row["revision_id"] for row in history}) == 5


def test_exact_duplicate_skips_model_even_without_model_configuration(db_engine):
    with Session(db_engine) as session:
        first = _seed_result(session, "AI 固件发布", "https://example.com/first", OLD_BODY, "first")
        material = materialization_service.materialize(session.connection(), first, None)
        second = _seed_result(session, "AI 固件发布", "https://other.example.com/copy", OLD_BODY, "copy")
        markdown = materialization_service.parsed_markdown(repo.get_result(session.connection(), second))
        session.execute(text(
            "INSERT INTO collection_snapshots (result_id,markdown,content_hash,extractor_version) "
            "VALUES (:result,:body,:hash,'test/1')"
        ), {"result": second, "body": markdown, "hash": hashlib.sha256(markdown.encode()).hexdigest()})
        session.commit()
    outcome = compare_result_history(db_engine, str(second), {})
    assert outcome["status"] == "duplicate"
    assert outcome["comparisons"][0]["material_id"] == str(material["material_id"])
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM collection_analyses")).scalar_one() == 0
