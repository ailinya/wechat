"""Create collection schema (task 3.2).

Creates collection_sources, collection_tasks, collection_task_sources,
collection_runs and collection_results. Tasks and runs are separate records:
a task is a reusable definition (with schedule/timezone), a run is one
execution of it. Status vocabularies are enforced by CHECK constraints, a
partial unique index prevents duplicate scheduling in the same window, and
a trigger blocks scheduling a paused/archived task (manual runs stay allowed).

Deletion preserves traceability: task/source deletion is a soft delete
(status='archived' / deleted_at) and child FKs use RESTRICT / SET NULL so
existing runs and results keep resolving to their origin.

Revision ID: 0003_collection
Revises: 0002_async_execution
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0003_collection"
down_revision = "0002_async_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- sources ---
    op.execute(
        """
CREATE TABLE collection_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL,
    source_type     VARCHAR(16) NOT NULL
                    CHECK (source_type IN ('rss', 'web_page')),
    base_url        VARCHAR(512) NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    status          VARCHAR(16) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive', 'unavailable')),
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_checked_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- tasks (definition only; runs are separate rows) ---
    op.execute(
        """
CREATE TABLE collection_tasks (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(128) NOT NULL,
    keywords          JSONB NOT NULL DEFAULT '[]'::jsonb
                      CHECK (jsonb_typeof(keywords) = 'array'),
    time_range_days   INTEGER NOT NULL DEFAULT 7
                      CHECK (time_range_days BETWEEN 1 AND 365),
    schedule_frequency VARCHAR(16) NOT NULL DEFAULT 'manual'
                      CHECK (schedule_frequency IN ('manual', 'hourly', 'daily', 'weekly', 'cron')),
    schedule_cron_expr VARCHAR(64),
    timezone          VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    auto_materialize  BOOLEAN NOT NULL DEFAULT FALSE,
    auto_create       BOOLEAN NOT NULL DEFAULT FALSE,
    status            VARCHAR(16) NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'paused', 'archived')),
    last_run_at       TIMESTAMPTZ,
    next_run_at       TIMESTAMPTZ,
    last_window_key   VARCHAR(64),
    lease_until       TIMESTAMPTZ,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (schedule_frequency <> 'cron' OR schedule_cron_expr IS NOT NULL)
)
        """
    )

    # --- task <-> source links ---
    op.execute(
        """
CREATE TABLE collection_task_sources (
    task_id    UUID NOT NULL REFERENCES collection_tasks(id) ON DELETE CASCADE,
    source_id  UUID NOT NULL REFERENCES collection_sources(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, source_id)
)
        """
    )

    # --- runs (one execution of a task) ---
    op.execute(
        """
CREATE TABLE collection_runs (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id            UUID NOT NULL REFERENCES collection_tasks(id) ON DELETE RESTRICT,
    trigger            VARCHAR(16) NOT NULL
                       CHECK (trigger IN ('manual', 'scheduled')),
    status             VARCHAR(16) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'running', 'succeeded', 'partial', 'failed')),
    window_key         VARCHAR(64),
    async_job_id       UUID REFERENCES async_jobs(id) ON DELETE SET NULL,
    fetched_count      INTEGER NOT NULL DEFAULT 0 CHECK (fetched_count >= 0),
    parsed_count       INTEGER NOT NULL DEFAULT 0 CHECK (parsed_count >= 0),
    materialized_count INTEGER NOT NULL DEFAULT 0 CHECK (materialized_count >= 0),
    failed_count       INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    error              TEXT,
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- results (deduplicated candidates produced by a run) ---
    op.execute(
        """
CREATE TABLE collection_results (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID NOT NULL REFERENCES collection_runs(id) ON DELETE RESTRICT,
    source_id         UUID REFERENCES collection_sources(id) ON DELETE SET NULL,
    title             VARCHAR(512) NOT NULL,
    url               VARCHAR(2048) NOT NULL,
    summary           TEXT NOT NULL DEFAULT '',
    published_at      TIMESTAMPTZ,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_content       TEXT,
    raw_object_id     UUID REFERENCES stored_objects(id) ON DELETE SET NULL,
    dedup_key         VARCHAR(64),
    parse_status      VARCHAR(16) NOT NULL DEFAULT 'pending'
                      CHECK (parse_status IN ('pending', 'parsed', 'failed')),
    materialize_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                      CHECK (materialize_status IN
                             ('pending', 'materialized', 'duplicate', 'new_progress',
                              'ignored', 'failed')),
    material_id       UUID,
    claimed_at        TIMESTAMPTZ,
    claimed_by        VARCHAR(64),
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- indexes ---
    op.execute("CREATE INDEX ix_collection_sources_status ON collection_sources (status, created_at)")
    op.execute("CREATE INDEX ix_collection_sources_type ON collection_sources (source_type, status)")
    op.execute("CREATE INDEX ix_collection_tasks_status ON collection_tasks (status, next_run_at)")
    op.execute("CREATE INDEX ix_collection_task_sources_source ON collection_task_sources (source_id)")
    op.execute("CREATE INDEX ix_collection_runs_task ON collection_runs (task_id, created_at)")
    op.execute("CREATE INDEX ix_collection_runs_status ON collection_runs (status, created_at)")
    op.execute("CREATE INDEX ix_collection_results_run ON collection_results (run_id, collected_at)")
    op.execute("CREATE INDEX ix_collection_results_status ON collection_results (parse_status, materialize_status)")
    op.execute("CREATE INDEX ix_collection_results_dedup ON collection_results (dedup_key)")

    # One scheduled run per task per scheduling window (manual runs have NULL
    # window_key and are unrestricted).
    op.execute(
        "CREATE UNIQUE INDEX uq_collection_runs_task_window "
        "ON collection_runs (task_id, window_key) WHERE window_key IS NOT NULL"
    )

    # --- paused/archived tasks cannot be SCHEDULED (manual runs stay allowed) ---
    op.execute(
        """
CREATE FUNCTION assert_collection_task_schedulable() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.trigger = 'scheduled' AND EXISTS (
        SELECT 1 FROM collection_tasks t
        WHERE t.id = NEW.task_id AND t.status <> 'active'
    ) THEN
        RAISE EXCEPTION 'collection task % is not active; cannot schedule a run', NEW.task_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
CREATE TRIGGER trg_collection_runs_schedulable
BEFORE INSERT OR UPDATE OF task_id, trigger ON collection_runs
FOR EACH ROW EXECUTE FUNCTION assert_collection_task_schedulable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_collection_runs_schedulable ON collection_runs")
    op.execute("DROP FUNCTION IF EXISTS assert_collection_task_schedulable()")
    op.execute("DROP TABLE IF EXISTS collection_results")
    op.execute("DROP TABLE IF EXISTS collection_runs")
    op.execute("DROP TABLE IF EXISTS collection_task_sources")
    op.execute("DROP TABLE IF EXISTS collection_tasks")
    op.execute("DROP TABLE IF EXISTS collection_sources")
