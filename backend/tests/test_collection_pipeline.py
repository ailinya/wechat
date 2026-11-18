from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.adapters.source_fetch import FetchResult
from app.services.collection_pipeline import execute_collection
from app.adapters.model_client import ModelClient
import json
import pytest
from app.modules.async_execution.registry import JobCancelled
from app.adapters.search_client import SearchClient


def seed(engine, *, analysis=False):
    with engine.begin() as conn:
        source = conn.execute(
            text(
                "INSERT INTO collection_sources(name,source_type,base_url) VALUES ('feed','rss','https://example.com/feed') RETURNING id"
            )
        ).scalar_one()
        task = conn.execute(
            text("INSERT INTO collection_tasks(name) VALUES ('pipeline') RETURNING id")
        ).scalar_one()
        config = {
            "mode": "source",
            "sources": [
                {
                    "id": str(source),
                    "name": "feed",
                    "source_type": "rss",
                    "base_url": "https://example.com/feed",
                }
            ],
            "time_range_days": 7,
            "max_candidates": 100,
            "max_fetch": 20,
            "max_pages": 5,
            "auto_materialize": True,
            "analysis_enabled": analysis,
        }
        if analysis:
            model = conn.execute(
                text(
                    "INSERT INTO model_configs(name,provider,purpose,endpoint,model_name) VALUES ('test','test','analysis','https://example.com','test') RETURNING id"
                )
            ).scalar_one()
            config["analysis_model_config_id"] = str(model)
        import json

        return conn.execute(
            text(
                "INSERT INTO collection_runs(task_id,trigger,config_snapshot) VALUES (:task,'manual',CAST(:config AS jsonb)) RETURNING id"
            ),
            {"task": task, "config": json.dumps(config)},
        ).scalar_one()


def test_rss_multiple_articles_resume_without_duplicate_ready_events(db_engine):
    run = seed(db_engine)
    calls = []
    today = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    def fetch(url):
        calls.append(url)
        if url.endswith("/feed"):
            body = "<rss><channel><item><link>/one</link></item><item><link>/two</link></item></channel></rss>"
        else:
            body = f'<html><head><title>{url}</title><meta property="article:published_time" content="{today}"></head><body><article><h1>{url}</h1><p>这是新闻的完整正文，包含事实和背景说明，足够用于素材分析和后续处理。</p></article></body></html>'
        return FetchResult(url, 200, body, "text/html", 1)

    first = execute_collection(
        db_engine, run, fetcher=fetch, resolver=lambda *_: ["93.184.216.34"]
    )
    assert first["status"] == "succeeded"
    assert execute_collection(db_engine, run, fetcher=fetch)["reused"]
    assert len(calls) == 3
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 2, (
            conn.execute(text("SELECT status,error FROM collection_candidates"))
            .mappings()
            .all()
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM material_ready_events")
            ).scalar_one()
            == 2
        )
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM outbox_events WHERE event_type='material.ready'"
                )
            ).scalar_one()
            == 2
        )


@pytest.mark.parametrize("failure", ["invalid_json", "timeout", "illegal_schema"])
def test_analysis_failure_recovers_from_snapshot_without_refetch(db_engine, failure):
    run = seed(db_engine, analysis=True)
    calls = []
    date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    def fetch(url):
        calls.append(url)
        raw = (
            "<rss><channel><item><link>/one</link></item></channel></rss>"
            if url.endswith("/feed")
            else f'<html><head><title>行业新闻</title><meta property="article:published_time" content="{date}"></head><body><article><p>这是一篇足够详细的新闻正文，包含实际事件和相关事实及背景说明。</p></article></body></html>'
        )
        return FetchResult(url, 200, raw, "text/html", 1)

    def broken_model(*args):
        if failure == "timeout":
            raise TimeoutError("fixture timeout")
        return 200, {
            "choices": [
                {
                    "message": {
                        "content": "not JSON"
                        if failure == "invalid_json"
                        else '{"unexpected":true}'
                    }
                }
            ]
        }

    bad = ModelClient(broken_model, max_attempts=1)
    first = execute_collection(
        db_engine,
        run,
        fetcher=fetch,
        resolver=lambda *_: ["93.184.216.34"],
        model_client=bad,
    )
    assert first["status"] == "partial"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 0
    output = {"summary": "新闻摘要", "relevance": "not_applicable", "facts": []}
    good = ModelClient(
        lambda *args: (
            200,
            {
                "choices": [
                    {"message": {"content": json.dumps(output, ensure_ascii=False)}}
                ]
            },
        ),
        max_attempts=1,
    )
    second = execute_collection(
        db_engine,
        run,
        fetcher=fetch,
        resolver=lambda *_: ["93.184.216.34"],
        model_client=good,
    )
    assert second["status"] == "succeeded", second
    assert len(calls) == 2
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 1
        assert (
            conn.execute(
                text("SELECT count(*) FROM material_ready_events")
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    "case", ["unknown_date", "keyword_mismatch", "http_error", "cancelled", "budget"]
)
def test_pipeline_boundaries_do_not_emit_ready_events(db_engine, case):
    run = seed(db_engine)
    with db_engine.begin() as conn:
        config = conn.execute(
            text("SELECT config_snapshot FROM collection_runs WHERE id=:id"),
            {"id": run},
        ).scalar_one()
        config["sources"][0]["source_type"] = "web_page"
        if case == "keyword_mismatch":
            config["keywords"] = ["必须出现的关键词"]
        conn.execute(
            text(
                "UPDATE collection_runs SET config_snapshot=CAST(:config AS jsonb) WHERE id=:id"
            ),
            {"id": run, "config": json.dumps(config)},
        )
        if case == "cancelled":
            conn.execute(
                text("UPDATE collection_runs SET end_reason='cancelled' WHERE id=:id"),
                {"id": run},
            )
        if case == "budget":
            conn.execute(
                text(
                    "UPDATE collection_runs SET started_at=now()-interval '11 minutes' WHERE id=:id"
                ),
                {"id": run},
            )
    date = (
        ""
        if case == "unknown_date"
        else f'<meta property="article:published_time" content="{(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}">'
    )

    def fetch(url):
        return FetchResult(
            url,
            403 if case == "http_error" else 200,
            f"<html><head><title>行业文章</title>{date}</head><body><article><p>行业文章包含足够详细的资料正文、实际事件与相关背景说明，供采集解析测试使用。</p></article></body></html>",
            "text/html",
            1,
        )

    if case == "cancelled":
        with pytest.raises(JobCancelled):
            execute_collection(
                db_engine, run, fetcher=fetch, resolver=lambda *_: ["93.184.216.34"]
            )
    else:
        result = execute_collection(
            db_engine, run, fetcher=fetch, resolver=lambda *_: ["93.184.216.34"]
        )
        if case == "budget":
            assert result["end_reason"] == "budget_exhausted"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM materials")).scalar_one() == 0
        assert (
            conn.execute(
                text("SELECT count(*) FROM material_ready_events")
            ).scalar_one()
            == 0
        )


def test_theme_search_empty_result_is_success_and_reuses_query(db_engine, monkeypatch):
    run = seed(db_engine)
    monkeypatch.setenv("FIXTURE_SEARCH_KEY", "fixture")
    with db_engine.begin() as conn:
        search = conn.execute(
            text(
                "INSERT INTO search_configs(name,provider,credential_ref) VALUES ('search','tavily','FIXTURE_SEARCH_KEY') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "UPDATE collection_runs SET config_snapshot=CAST(:config AS jsonb) WHERE id=:id"
            ),
            {
                "id": run,
                "config": json.dumps(
                    {
                        "mode": "topic_search",
                        "topic": "主题",
                        "source_ids": [],
                        "search_config_id": str(search),
                        "auto_materialize": True,
                        "allowed_domains": [],
                    }
                ),
            },
        )
    calls = []
    search = SearchClient(
        transport=lambda payload: calls.append(payload) or (200, {"results": []})
    )
    result = execute_collection(db_engine, run, search_client=search)
    assert result["status"] == "succeeded"
    assert execute_collection(db_engine, run, search_client=search)["reused"]
    assert len(calls) == 1
