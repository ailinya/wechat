import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from sqlalchemy import text

from app.adapters.model_client import ModelClient
from app.services.material_analysis_service import analyze_result
from app.errors import ApiError
from app.modules.collection.analysis_tasks import analyze_result_once


def _seed(engine, body="AI 正文中提到事实证据。"):
    digest = hashlib.sha256(body.encode()).hexdigest()
    with engine.begin() as conn:
        task_id = conn.execute(text("INSERT INTO collection_tasks (name) VALUES ('analysis') RETURNING id")).scalar_one()
        run_id = conn.execute(text(
            "INSERT INTO collection_runs (task_id, trigger, status, started_at) "
            "VALUES (:task, 'manual', 'running', now()) RETURNING id"
        ), {"task": task_id}).scalar_one()
        result_id = conn.execute(text(
            "INSERT INTO collection_results (run_id, title, url, parse_status) "
            "VALUES (:run, 'AI 标题', 'https://example.com/a', 'parsed') RETURNING id"
        ), {"run": run_id}).scalar_one()
        conn.execute(text(
            "INSERT INTO collection_snapshots (result_id, markdown, content_hash, extractor_version) "
            "VALUES (:result, :body, :hash, 'fixture/1')"
        ), {"result": result_id, "body": body, "hash": digest})
        config_id = conn.execute(text(
            "INSERT INTO model_configs (name, provider, purpose, endpoint, model_name) "
            "VALUES ('analysis fixture', 'test', 'analysis', 'https://example.com', 'fixture') RETURNING id"
        )).scalar_one()
    return str(result_id), {"id": str(config_id), "provider": "test", "purpose": "analysis",
        "endpoint": "https://example.com", "model_name": "fixture", "credential_ref": None,
        "enabled": True, "config_version": 1, "max_input_tokens": 8000,
        "max_output_tokens": 2000, "timeout_seconds": 10}


def _transport(content, calls):
    encoded = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content

    def send(*_args):
        calls.append(1)
        return 200, {"choices": [{"message": {"content": encoded}}], "usage": {"total_tokens": 25}}

    return send


def test_analysis_reuses_same_input_but_scopes_key_by_topic(db_engine):
    result_id, config = _seed(db_engine)
    calls = []
    output = {"summary": "简要总结", "relevance": "relevant", "facts": [
        {"statement": "正文事实", "quote": "AI 正文中提到事实证据。", "ref_index": 0}
    ]}
    client = ModelClient(transport=_transport(output, calls), max_attempts=1)

    first = analyze_result(db_engine, result_id, config, topic="人工智能", client=client)
    repeated = analyze_result(db_engine, result_id, config, topic="人工智能", client=client)
    different_topic = analyze_result(db_engine, result_id, config, topic="机器人", client=client)

    assert first["status"] == "succeeded" and first["attempt"] == 1
    assert repeated["reused"] is True
    assert different_topic["status"] == "succeeded"
    assert first["logical_key"] != different_topic["logical_key"]
    assert len(calls) == 2

    with db_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, stale, attempt, usage FROM collection_analyses ORDER BY created_at, id"
        )).mappings().all()
    assert len(rows) == 2
    assert all(row["status"] == "succeeded" and not row["stale"] and row["attempt"] == 1 for row in rows)
    assert rows[0]["usage"]["total_tokens"] == 25


def test_body_change_during_call_marks_analysis_stale(db_engine):
    result_id, config = _seed(db_engine)
    calls = []
    output = {"summary": "总结", "relevance": "relevant", "facts": []}

    def send(*_args):
        calls.append(1)
        body = "更新后的正文"
        with db_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO collection_snapshots (result_id, markdown, content_hash, extractor_version) "
                "VALUES (:result, :body, :hash, 'fixture/2')"
            ), {"result": result_id, "body": body, "hash": hashlib.sha256(body.encode()).hexdigest()})
        return 200, {"choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}], "usage": {}}

    result = analyze_result(db_engine, result_id, config, topic="AI", client=ModelClient(send, max_attempts=1))
    assert result["status"] == "succeeded" and result["stale"] is True


def test_invalid_model_citation_is_saved_as_failed_attempt(db_engine):
    result_id, config = _seed(db_engine)
    calls = []
    invalid = {"summary": "总结", "relevance": "relevant", "facts": [
        {"statement": "虚构事实", "quote": "原文不存在", "ref_index": 0}
    ]}
    result = analyze_result(
        db_engine, result_id, config, topic="AI",
        client=ModelClient(transport=_transport(invalid, calls), max_attempts=1),
    )
    assert result["status"] == "failed" and result["error"] == "invalid_citation"
    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT status, error, attempt FROM collection_analyses")).mappings().one()
    assert row["status"] == "failed" and row["attempt"] == 1
    assert "invalid_citation" in row["error"]

    valid = {"summary": "总结", "relevance": "relevant", "facts": [
        {"statement": "正文事实", "quote": "AI 正文中提到事实证据。", "ref_index": 0}
    ]}
    retry = analyze_result(
        db_engine, result_id, config, topic="AI",
        client=ModelClient(transport=_transport(valid, calls), max_attempts=1),
    )
    assert retry["status"] == "succeeded" and retry["attempt"] == 2


def test_concurrent_analysis_reuses_running_claim_without_second_call(db_engine):
    result_id, config = _seed(db_engine)
    entered, release = Event(), Event()
    calls = []

    def send(*args):
        entered.set()
        assert release.wait(10)
        return _transport({"summary": "摘要", "relevance": "relevant", "facts": []}, calls)(*args)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(analyze_result, db_engine, result_id, config, topic="AI",
                              client=ModelClient(send, max_attempts=1))
        try:
            assert entered.wait(10)
            repeated = analyze_result(db_engine, result_id, config, topic="AI",
                                      client=ModelClient(send, max_attempts=1))
            assert repeated["status"] == "running" and repeated["reused"]
        finally:
            release.set()
        assert pending.result(timeout=10)["status"] == "succeeded"
    assert len(calls) == 1


def test_failed_attempts_stop_at_budget_and_handler_uses_saved_body(db_engine):
    result_id, config = _seed(db_engine)
    calls = []
    client = ModelClient(_transport("not JSON", calls), max_attempts=1)
    for attempt in range(1, 4):
        result = analyze_result_once(result_id, config["id"], topic="AI", engine=db_engine, client=client)
        assert result["status"] == "failed" and result["attempt"] == attempt
    with pytest.raises(ApiError) as exc:
        analyze_result_once(result_id, config["id"], topic="AI", engine=db_engine, client=client)
    assert exc.value.code == "analysis_budget_exhausted" and len(calls) == 3
    with db_engine.connect() as conn:
        records = conn.execute(text(
            "SELECT input_context, input_hash, snapshot_id, config_snapshot FROM collection_analyses"
        )).mappings().all()
    assert len(records) == 3
    assert all(row["snapshot_id"] and row["input_hash"] and row["config_snapshot"]["config_version"] == 1 for row in records)
    assert all(row["input_context"]["topic"] == "AI" for row in records)
