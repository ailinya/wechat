"""Real PostgreSQL checks; never substitute a fixture for database evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.adapters.search_client import SearchClient, SearchError
from app.services.search_discovery_service import discover


def login(client, account="admin", password="correct-password"):
    assert client.post("/api/v1/auth/login", json={"account": account, "password": password}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}


def test_config_crud_and_permissions(client):
    headers = login(client)
    data = {"name": "搜索配置", "provider": "tavily", "credential_ref": "TEST_SEARCH_KEY"}
    response = client.post("/api/v1/search-configs", json=data, headers=headers)
    assert response.status_code == 201, response.text
    config = response.json()
    assert config["credential_configured"] and "TEST_SEARCH_KEY" not in response.text
    url = f"/api/v1/search-configs/{config['id']}"
    assert client.get(url).status_code == 200
    updated = client.patch(url, json={"enabled": False}, headers=headers)
    assert updated.status_code == 200 and updated.json()["config_version"] == 2
    assert updated.json()["credential_configured"]
    assert client.post("/api/v1/search-configs", json=data, headers=headers).status_code == 409
    assert client.get("/api/v1/search-configs").json()["total"] == 1
    headers = login(client, "editor", "editor-password")
    assert client.patch(url, json={"enabled": True}, headers=headers).status_code == 403
    assert client.post(url + "/test", headers=headers).status_code == 403


def test_connection_failure_is_audited_and_safe(client, db_engine, monkeypatch):
    from app.services import search_config_service
    headers = login(client)
    config = client.post("/api/v1/search-configs", json={"name": "test", "provider": "tavily"}, headers=headers).json()
    monkeypatch.setattr(search_config_service, "probe", lambda _: {
        "reachable": False, "error": "搜索凭据无效或无权限", "error_code": "search_auth_failed", "latency_ms": 1})
    response = client.post(f"/api/v1/search-configs/{config['id']}/test", headers=headers)
    assert response.status_code == 200 and response.json()["reachable"] is False
    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT result, detail FROM operation_logs WHERE action='search_config.test'")).mappings().one()
        assert row["result"] == "failed" and row["detail"]["error_code"] == "search_auth_failed"


@pytest.fixture
def search_run(db_engine, monkeypatch):
    monkeypatch.setenv("TEST_SEARCH_KEY", "fixture-only")
    with db_engine.begin() as conn:
        config_id = conn.execute(text("INSERT INTO search_configs (name,provider,credential_ref) "
            "VALUES ('test','tavily','TEST_SEARCH_KEY') RETURNING id")).scalar_one()
        task_id = conn.execute(text("INSERT INTO collection_tasks (name,mode,topic,search_config_id) "
            "VALUES ('topic','topic_search','科技',:config) RETURNING id"), {"config": config_id}).scalar_one()
        run_id = conn.execute(text("INSERT INTO collection_runs (task_id,trigger,status,started_at) "
            "VALUES (:task,'manual','running',now()) RETURNING id"), {"task": task_id}).scalar_one()
    return run_id, {"mode": "topic_search", "topic": "科技", "search_config_id": str(config_id),
                    "allowed_domains": ["example.com"], "time_range_days": 7, "max_candidates": 100}


def test_discovery_persists_provenance_deduplicates_and_reuses(db_engine, search_run):
    run_id, task = search_run
    calls = []
    def transport(payload):
        calls.append(payload)
        # Separate provider ranks survive URL deduplication in evidence.
        return 200, {"results": [{"url": "https://example.com/a#one", "content": "摘要", "published_date": "未知"},
                                  {"url": "https://example.com/a#two"}, {"url": "https://outside.org/a"}]}
    client = SearchClient(transport)
    first = discover(db_engine, run_id, task, client=client)
    second = discover(db_engine, run_id, {**task, "topic": "不能改变已执行查询"}, client=client)
    assert first == second and len(calls) == 1
    assert first["candidates"][0]["candidate_id"] == first["candidates"][1]["candidate_id"]
    assert first["candidates"][0]["provider_published_at"] == "未知"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM collection_candidates")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM collection_results")).scalar_one() == 0
        assert conn.execute(text("SELECT attempts FROM collection_searches")).scalar_one() == 1


def test_zero_results_has_query_record(db_engine, search_run):
    run_id, task = search_run
    result = discover(db_engine, run_id, task, client=SearchClient(lambda _: (200, {"results": []})))
    assert result["reason"] == "no_results"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM collection_searches")).scalar_one() == "succeeded"
        assert conn.execute(text("SELECT count(*) FROM collection_candidates")).scalar_one() == 0


def test_budget_persists_across_failed_retries(db_engine, search_run):
    run_id, task = search_run
    calls = []
    def transport(_):
        calls.append(1)
        return 503, {}
    client = SearchClient(transport, max_attempts=1)
    for _ in range(3):
        with pytest.raises(SearchError):
            discover(db_engine, run_id, task, client=client)
    with pytest.raises(SearchError) as error:
        discover(db_engine, run_id, task, client=client)
    assert error.value.code == "budget_exhausted" and len(calls) == 3
    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT status, attempts FROM collection_searches")).one()
        assert row.status == "failed" and row.attempts == 3


def test_in_flight_discovery_is_not_run_twice(db_engine, search_run):
    run_id, task = search_run
    def transport(_):
        # Re-enter using a separate transaction while the first call is active.
        with pytest.raises(SearchError) as error:
            discover(db_engine, run_id, task)
        assert error.value.code == "search_in_progress"
        return 200, {"results": []}
    assert discover(db_engine, run_id, task, client=SearchClient(transport))["reason"] == "no_results"


def test_expired_run_budget_prevents_network(db_engine, search_run):
    run_id, task = search_run
    calls = []
    with pytest.raises(SearchError) as error:
        discover(db_engine, run_id, task, client=SearchClient(lambda p: calls.append(p)),
                 now=lambda: datetime.now(timezone.utc) + timedelta(minutes=11))
    assert error.value.code == "budget_exhausted" and not calls
