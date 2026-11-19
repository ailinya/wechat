"""Shared fixtures: isolated test database.

Set TEST_DATABASE_URL to a PostgreSQL URL dedicated to tests (e.g. an empty
schema in a local docker-compose instance). Database-backed tests skip when it
is unset, so the default suite never touches any real or production service.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.main import create_app
from app.modules.auth.security import hash_password
from app.repositories import auth_repository as repo

TEST_URL = os.environ.get("TEST_DATABASE_URL")


def reset_schema() -> None:
    """Drop all app tables and replay migrations on the test database."""
    engine = create_engine(TEST_URL)
    with engine.connect() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS account_article_metrics, notifications, notification_preferences, system_settings, wechat_draft_attempts, wechat_draft_deliveries, publish_attempts, publish_orders, account_synced_materials, account_sync_runs, wechat_accounts, reviews, article_materials, article_revisions, articles, "
                "creation_consumed_events, creation_outputs, creation_task_materials, creation_tasks, "
                "creation_rule_collection_tasks, creation_rules, collection_searches, collection_candidate_discoveries, "
                "material_embedding_runs, material_chunk_search_vectors, material_search_vectors, material_chunks, material_ready_events, collection_analyses, "
                "collection_snapshots, collection_stage_attempts, collection_candidates, "
                "search_configs, model_configs, "
                "collection_results, collection_runs, "
                "collection_task_sources, collection_tasks, collection_sources, "
                "material_favorites, material_relations, material_files, "
                "material_tags, tags, material_revisions, materials, material_categories, "
                "upload_grants, idempotency_keys, "
                "stored_objects, operation_logs, outbox_events, async_jobs, "
                "sessions, role_permissions, user_roles, users, permissions, "
                "roles, alembic_version CASCADE"
            )
        )
        conn.execute(
            text("DROP FUNCTION IF EXISTS assert_collection_task_schedulable()")
        )
        conn.commit()
    engine.dispose()

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_URL
    try:
        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def seed_users(engine) -> tuple[UUID, UUID]:
    """Seed permissions plus an admin and an editor account; returns their ids."""
    with Session(engine) as session:
        with session.begin():
            conn = session.connection()
            repo.ensure_permissions_seeded(conn)
            now = datetime.now(timezone.utc)
            admin_role = repo.role_id_by_name(conn, "admin")
            editor_role = repo.role_id_by_name(conn, "editor")

            admin_id = conn.execute(
                text(
                    "INSERT INTO users (account, name, status, password_hash, created_at, updated_at) "
                    "VALUES ('admin', '管理员', 'active', :pw, :now, :now) RETURNING id"
                ),
                {"pw": hash_password("correct-password"), "now": now},
            ).scalar_one()
            editor_id = conn.execute(
                text(
                    "INSERT INTO users (account, name, status, password_hash, created_at, updated_at) "
                    "VALUES ('editor', '编辑', 'active', :pw, :now, :now) RETURNING id"
                ),
                {"pw": hash_password("editor-password"), "now": now},
            ).scalar_one()
            conn.execute(
                text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
                {"u": admin_id, "r": admin_role},
            )
            conn.execute(
                text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
                {"u": editor_id, "r": editor_role},
            )
            return admin_id, editor_id


@pytest.fixture
def db_engine():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    reset_schema()
    engine = create_engine(TEST_URL)
    seed_users(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine) -> TestClient:
    def override_get_db():
        with Session(db_engine) as s:
            yield s

    settings = Settings.model_validate(
        {"APP_SECRET_KEY": "t" * 40, "DATABASE_URL": TEST_URL}
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
