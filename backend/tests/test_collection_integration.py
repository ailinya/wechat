"""Cross-component integration verification for phase 3 (task 3.11).

Verifies the run -> result -> material -> revision chain, dedup/concurrent
materialization, new progress, parse-failure retry, cross-user favorites and
constrained delete. Requires TEST_DATABASE_URL (PostgreSQL); skips otherwise
per the conftest convention so the default suite never touches real services.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.errors import ApiError
from app.repositories import collection_repository as collection_repo
from app.repositories import material_repository as material_repo
from app.services import materialization_service as materialization
from app.services import material_service

HTML_A = "<html><body><h1>固件 2.1</h1><p>修复中文输入问题</p></body></html>"
HTML_B = "<html><body><h1>固件 2.2</h1><p>新增夜间模式</p></body></html>"


def _seed_source_task_run(session: Session, body: str = HTML_A) -> tuple[str, str, str]:
    conn = session.connection()
    source_id = collection_repo.create_source(
        conn, name="integration-source", source_type="rss",
        base_url="https://example.com/feed", description="", enabled=True, created_by=None,
    )["id"]
    task = collection_repo.create_task(
        conn, name="integration-task", keywords=[], time_range_days=7,
        schedule_frequency="manual", schedule_cron_expr=None, timezone="Asia/Shanghai",
        auto_materialize=False, auto_create=False, source_ids=[str(source_id)], created_by=None,
    )
    run = collection_repo.create_run(conn, task_id=task["id"], trigger="manual")
    result = collection_repo.insert_result(
        conn, run_id=run["id"], source_id=source_id, title="固件更新",
        url="https://example.com/1", raw_content=body, dedup_key="feed-1", parse_status="parsed",
    )
    session.commit()
    return str(task["id"]), str(run["id"]), str(result["id"])


def test_run_result_material_revision_chain(db_engine) -> None:
    with Session(db_engine) as session:
        _, run_id, result_id = _seed_source_task_run(session)
        outcome = materialization.materialize(session.connection(), result_id, None)
        session.commit()

    with Session(db_engine) as session:
        conn = session.connection()
        result = session.connection().execute(
            text("SELECT * FROM collection_results WHERE id = :id"), {"id": result_id}
        ).mappings().one()
        assert str(result["run_id"]) == run_id
        assert str(result["material_id"]) == outcome["material_id"]
        assert result["materialize_status"] == "materialized"
        revision = session.connection().execute(
            text("SELECT * FROM material_revisions WHERE material_id = :id"),
            {"id": outcome["material_id"]},
        ).mappings().all()
        assert len(revision) == 1
        assert "修复中文输入问题" in revision[0]["content_markdown"]
        # Run counters reflect the single materialized result.
        run = session.connection().execute(text("SELECT * FROM collection_runs WHERE id = :id"), {"id": run_id}).mappings().one()
        assert run["status"] == "pending"  # not executed; materialized separately


def test_duplicate_materialize_does_not_create_second_material(db_engine) -> None:
    with Session(db_engine) as session:
        _, _, first_id = _seed_source_task_run(session)
        first = materialization.materialize(session.connection(), first_id, None)
        session.commit()
        # Second result with same dedup key and identical content.
        conn = session.connection()
        run_id = session.connection().execute(text("SELECT run_id FROM collection_results WHERE id = :id"), {"id": first_id}).scalar_one()
        second_id = collection_repo.insert_result(
            session.connection(), run_id=run_id, source_id=None, title="固件更新", url="https://example.com/1",
            raw_content=HTML_A, dedup_key="feed-1", parse_status="parsed",
        )["id"]
        session.commit()
        second = materialization.materialize(session.connection(), second_id, None)
        session.commit()
    assert second["status"] == "duplicate"
    assert second["material_id"] == first["material_id"]
    with Session(db_engine) as session:
        count = session.execute(text("SELECT count(*) FROM materials")).scalar_one()
        assert count == 1


def test_concurrent_materialize_creates_single_material(db_engine) -> None:
    # Two threads materialize two different results that share a dedup key.
    with Session(db_engine) as session:
        task_id, run_id, first_id = _seed_source_task_run(session)
        second_id = collection_repo.insert_result(
            session.connection(), run_id=run_id, source_id=None, title="固件更新",
            url="https://example.com/1", raw_content=HTML_A,
            dedup_key="feed-1", parse_status="parsed",
        )["id"]
        session.commit()

    def materialize(result_id: str) -> str:
        with Session(db_engine) as session:
            try:
                outcome = materialization.materialize(session.connection(), result_id, None)
                session.commit()
                return outcome["status"]
            except Exception:
                session.rollback()
                return "failed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(materialize, [first_id, second_id]))
    assert all(status in ("materialized", "duplicate") for status in statuses)
    with Session(db_engine) as session:
        materials = session.execute(text("SELECT count(*) FROM materials")).scalar_one()
        assert materials == 1
        revisions = session.execute(text("SELECT count(*) FROM material_revisions")).scalar_one()
        assert revisions == 1


def test_changed_content_preserves_old_revision_without_unproven_relation(db_engine) -> None:
    with Session(db_engine) as session:
        conn = session.connection()
        _, _, first_id = _seed_source_task_run(session, HTML_A)
        first = materialization.materialize(session.connection(), first_id, None)
        run_id = session.connection().execute(text("SELECT run_id FROM collection_results WHERE id = :id"), {"id": first_id}).scalar_one()
        new_id = collection_repo.insert_result(
            session.connection(), run_id=run_id, source_id=None, title="固件 2.2", url="https://example.com/1",
            raw_content=HTML_B, dedup_key="feed-1", parse_status="parsed",
        )["id"]
        session.commit()
        progressed = materialization.materialize(session.connection(), new_id, None)
        session.commit()
    assert progressed["status"] == "materialized"
    with Session(db_engine) as session:
        conn = session.connection()
        old = session.connection().execute(
            text("SELECT content_markdown FROM material_revisions WHERE material_id = :id"),
            {"id": first["material_id"]},
        ).scalar_one()
        assert "修复中文输入问题" in old
        relation = session.connection().execute(
            text("SELECT relation_type FROM material_relations WHERE source_material_id = :id"),
            {"id": progressed["material_id"]},
        ).scalar_one_or_none()
        assert relation is None


def test_parse_failure_retry_records_reason_then_recovers(db_engine) -> None:
    with Session(db_engine) as session:
        conn = session.connection()
        _, _, result_id = _seed_source_task_run(session)
        # Corrupt the raw content so parsing fails, then record the failure.
        session.connection().execute(
            text("UPDATE collection_results SET raw_content = :raw, parse_status = 'failed' WHERE id = :id"),
            {"raw": "<html><body></body></html>", "id": result_id},
        )
        session.commit()
        materialization.retry_parse(session.connection(), result_id)
        session.commit()
        status = session.connection().execute(
            text("SELECT parse_status FROM collection_results WHERE id = :id"), {"id": result_id}
        ).scalar_one()
        assert status == "failed"
        # Restore parseable content and retry again.
        session.connection().execute(
            text("UPDATE collection_results SET raw_content = :raw WHERE id = :id"),
            {"raw": HTML_A, "id": result_id},
        )
        session.commit()
        materialization.retry_parse(session.connection(), result_id)
        session.commit()
        status = session.connection().execute(
            text("SELECT parse_status FROM collection_results WHERE id = :id"), {"id": result_id}
        ).scalar_one()
        assert status == "parsed"


def test_cross_user_favorites_are_isolated(db_engine) -> None:
    with Session(db_engine) as session:
        conn = session.connection()
        admin_id = conn.execute(text("SELECT id FROM users WHERE account='admin'")).scalar_one()
        editor_id = conn.execute(text("SELECT id FROM users WHERE account='editor'")).scalar_one()
        material = material_service.create_material(
            conn, title="跨用户素材", content_markdown="中文正文", origin="manual", user_id=admin_id,
        )
        material_service.favorite(conn, material["id"], admin_id)
        session.commit()
    with Session(db_engine) as session:
        conn = session.connection()
        count_all = session.connection().execute(
            text("SELECT count(*) FROM material_favorites WHERE material_id = :id"),
            {"id": material["id"]},
        ).scalar_one()
        count_other = session.connection().execute(
            text("SELECT count(*) FROM material_favorites WHERE material_id = :id AND user_id = :editor"),
            {"id": material["id"], "editor": editor_id},
        ).scalar_one()
    assert count_all == 1
    assert count_other == 0


def test_constrained_delete_rejects_hard_delete_when_referenced(db_engine) -> None:
    with Session(db_engine) as session:
        conn = session.connection()
        _, _, result_id = _seed_source_task_run(session)
        outcome = materialization.materialize(session.connection(), result_id, None)
        session.commit()
    with Session(db_engine) as session:
        conn = session.connection()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.connection().execute(
                    text("DELETE FROM materials WHERE id = :id"), {"id": outcome["material_id"]}
                )
        # Soft delete preserves the revision chain and the result link.
        session.connection().execute(
            text("UPDATE materials SET deleted_at = now(), usage_status = 'archived' WHERE id = :id"),
            {"id": outcome["material_id"]},
        )
        session.commit()
        rev = session.connection().execute(
            text("SELECT count(*) FROM material_revisions WHERE material_id = :id"),
            {"id": outcome["material_id"]},
        ).scalar_one()
        assert rev == 1
