"""PostgreSQL integration tests for persisted discovery provenance."""
from sqlalchemy import text

from app.adapters.source_fetch import FetchResult
from app.repositories import collection_repository
from app.services.article_discovery_service import discover_run


def _seed(db_engine):
    with db_engine.begin() as conn:
        source_ids = [collection_repository.create_source(
            conn, name=f"feed-{n}", source_type="rss", base_url=f"https://example.com/feed-{n}",
            description="", enabled=True, created_by=None, page_kind="article")['id'] for n in (1, 2)]
        task_id = conn.execute(text("INSERT INTO collection_tasks (name) VALUES ('discovery') RETURNING id")).scalar_one()
        run_id = conn.execute(text("INSERT INTO collection_runs (task_id,trigger,status,started_at) "
                                   "VALUES (:task,'manual','running',now()) RETURNING id"), {"task": task_id}).scalar_one()
    return run_id, [{"id": source_id, "name": f"feed-{n}", "source_type": "rss", "base_url": f"https://example.com/feed-{n}"}
                    for n, source_id in enumerate(source_ids, 1)]


def test_discovery_deduplicates_candidate_but_preserves_each_source(db_engine):
    run_id, sources = _seed(db_engine)
    feeds = {
        sources[0]["base_url"]: "<rss><channel><item><title>A</title><link>/a#one</link><guid>one</guid></item></channel></rss>",
        sources[1]["base_url"]: "<rss><channel><item><title>A copy</title><link>https://example.com/a#two</link><guid>two</guid></item></channel></rss>",
    }
    result = discover_run(db_engine, run_id, sources,
        fetcher=lambda url: FetchResult(url, 200, feeds[url], "application/rss+xml", 1),
        resolver=lambda *_: ["93.184.216.34"])
    assert len(result.candidates) == 1
    assert len(result.candidates[0]["discoveries"]) == 2
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM collection_candidates WHERE run_id=:id"),
                            {"id": run_id}).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM collection_candidate_discoveries" )).scalar_one() == 2
        assert conn.execute(text("SELECT count(DISTINCT source_id) FROM collection_candidate_discoveries")).scalar_one() == 2


def test_discovery_persists_failure_without_losing_successful_source(db_engine):
    run_id, sources = _seed(db_engine)
    def fetcher(url):
        if url == sources[0]["base_url"]:
            return FetchResult(url, 403, "", "text/html", 1)
        return FetchResult(url, 200, "<rss><channel><item><title>B</title><link>/b</link></item></channel></rss>",
                           "application/rss+xml", 1)
    result = discover_run(db_engine, run_id, sources, fetcher=fetcher, resolver=lambda *_: ["93.184.216.34"])
    assert len(result.source_failures) == 1 and result.source_failures[0]["code"] == "source_http_error"
    assert len(result.candidates) == 1
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM collection_candidate_discoveries")).scalar_one() == 1
