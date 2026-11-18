from datetime import datetime, timezone

from sqlalchemy import text

from app.services.article_extraction_service import extract_article, persist_candidate_extraction


def test_extraction_snapshot_persists_raw_markdown_hash_version_and_decision(db_engine):
    html = """<html><head><title>AI update</title>
    <meta property="article:published_time" content="2026-11-17T08:00:00Z"></head>
    <body><article><h1>AI update</h1><p>完整的 AI 行业文章正文，描述实际发布与产品情况。</p>
    <p>这里补充背景、数字与事件说明，确保正文内容足够。</p></article></body></html>"""
    with db_engine.begin() as conn:
        task_id = conn.execute(text("INSERT INTO collection_tasks (name) VALUES ('extract') RETURNING id")).scalar_one()
        run_id = conn.execute(text(
            "INSERT INTO collection_runs (task_id, trigger, status, started_at) "
            "VALUES (:task, 'manual', 'running', now()) RETURNING id"
        ), {"task": task_id}).scalar_one()
        candidate_id = conn.execute(text(
            "INSERT INTO collection_candidates (run_id, source, url, normalized_url) "
            "VALUES (:run, 'search', 'https://example.com/a', 'https://example.com/a') RETURNING id"
        ), {"run": run_id}).scalar_one()
        extraction = extract_article(
            html, url="https://example.com/a", run_started_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
            time_range_days=7, keywords=["AI"],
        )
        persist_candidate_extraction(conn, candidate_id, html, extraction)

        snapshot = conn.execute(text(
            "SELECT raw_content, markdown, content_hash, extractor_version, title, date_evidence "
            "FROM collection_snapshots WHERE candidate_id=:id"
        ), {"id": candidate_id}).mappings().one()
        candidate = conn.execute(text(
            "SELECT status, title, provider_published_at, error FROM collection_candidates WHERE id=:id"
        ), {"id": candidate_id}).mappings().one()

    assert snapshot["raw_content"] == html
    assert snapshot["markdown"] == extraction.markdown
    assert snapshot["content_hash"] == extraction.content_hash
    assert snapshot["extractor_version"].startswith("trafilatura/")
    assert snapshot["title"] == "AI update"
    assert '"metadata"' in snapshot["date_evidence"]
    assert candidate["status"] == "parsed"
    assert candidate["provider_published_at"].date().isoformat() == "2026-11-17"
    assert candidate["error"] is None
