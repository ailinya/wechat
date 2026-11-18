"""Create collection-enhancement schema (task 3.15).

Adds search/model configs, candidate discovery, stage attempts, content
snapshots, analyses and a material-ready event log. Extends existing
collection_sources / collection_tasks / collection_runs / materials with
nullable-backfilled columns so no history is re-run and migrations 0003/0004
are untouched (additive ALTER only).

Old rows are backfilled by NOT NULL DEFAULT: mode='source',
analysis_enabled=false, page_kind='article'.

Revision ID: 0005_collection_enhancement
Revises: 0004_materials
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0005_collection_enhancement"
down_revision = "0004_materials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- public model configs (shared; analysis/generation/embedding) ---
    op.execute(
        """
CREATE TABLE model_configs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(128) NOT NULL UNIQUE,
    provider          VARCHAR(64) NOT NULL,
    purpose           VARCHAR(16) NOT NULL
                      CHECK (purpose IN ('analysis', 'generation', 'embedding')),
    endpoint          VARCHAR(512) NOT NULL,
    model_name        VARCHAR(128) NOT NULL,
    credential_ref    VARCHAR(255),
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    config_version    INTEGER NOT NULL DEFAULT 1 CHECK (config_version >= 1),
    max_input_tokens  INTEGER NOT NULL DEFAULT 8000 CHECK (max_input_tokens > 0),
    max_output_tokens INTEGER NOT NULL DEFAULT 2000 CHECK (max_output_tokens > 0),
    timeout_seconds   INTEGER NOT NULL DEFAULT 60 CHECK (timeout_seconds BETWEEN 1 AND 600),
    params            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- search service configs (independent of sources/embedding) ---
    op.execute(
        """
CREATE TABLE search_configs (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                   VARCHAR(128) NOT NULL UNIQUE,
    provider               VARCHAR(16) NOT NULL CHECK (provider IN ('tavily')),
    credential_ref         VARCHAR(255),
    enabled                BOOLEAN NOT NULL DEFAULT TRUE,
    config_version         INTEGER NOT NULL DEFAULT 1 CHECK (config_version >= 1),
    max_results            INTEGER NOT NULL DEFAULT 5 CHECK (max_results BETWEEN 1 AND 20),
    supports_domain_filter BOOLEAN NOT NULL DEFAULT TRUE,
    supports_date_filter   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- extend sources with page kind + list-page selectors ---
    op.execute("ALTER TABLE collection_sources ADD COLUMN page_kind VARCHAR(16) NOT NULL DEFAULT 'article'")
    op.execute(
        "ALTER TABLE collection_sources ADD CONSTRAINT ck_collection_sources_page_kind "
        "CHECK (page_kind IN ('article', 'list'))"
    )
    op.execute("ALTER TABLE collection_sources ADD COLUMN article_link_selector VARCHAR(256)")
    op.execute("ALTER TABLE collection_sources ADD COLUMN next_page_selector VARCHAR(256)")

    # --- extend tasks with mode / topic / domains / limits / analysis ---
    op.execute("ALTER TABLE collection_tasks ADD COLUMN mode VARCHAR(16) NOT NULL DEFAULT 'source'")
    op.execute(
        "ALTER TABLE collection_tasks ADD CONSTRAINT ck_collection_tasks_mode "
        "CHECK (mode IN ('source', 'topic_search'))"
    )
    op.execute("ALTER TABLE collection_tasks ADD COLUMN topic VARCHAR(256)")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN allowed_domains JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN max_candidates INTEGER NOT NULL DEFAULT 100")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN max_fetch INTEGER NOT NULL DEFAULT 20")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN max_pages INTEGER NOT NULL DEFAULT 5")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN analysis_enabled BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN analysis_model_config_id UUID REFERENCES model_configs(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE collection_tasks ADD COLUMN analysis_apply_policy VARCHAR(16) NOT NULL DEFAULT 'suggest_only'")
    op.execute(
        "ALTER TABLE collection_tasks ADD CONSTRAINT ck_collection_tasks_apply_policy "
        "CHECK (analysis_apply_policy IN ('suggest_only', 'fill_empty'))"
    )
    op.execute("ALTER TABLE collection_tasks ADD COLUMN search_config_id UUID REFERENCES search_configs(id) ON DELETE SET NULL")

    # --- extend runs with end reason, stage counts and config snapshot ---
    op.execute("ALTER TABLE collection_runs ADD COLUMN end_reason VARCHAR(16)")
    op.execute(
        "ALTER TABLE collection_runs ADD CONSTRAINT ck_collection_runs_end_reason "
        "CHECK (end_reason IN ('completed', 'cancelled', 'budget_exhausted', 'error'))"
    )
    op.execute("ALTER TABLE collection_runs ADD COLUMN discovered_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE collection_runs ADD COLUMN analyzed_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE collection_runs ADD COLUMN filtered_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE collection_runs ADD COLUMN review_required_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE collection_runs ADD COLUMN config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb")

    # --- extend materials with metadata version + manual-field tracking ---
    op.execute("ALTER TABLE materials ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE materials ADD COLUMN manual_fields JSONB NOT NULL DEFAULT '[]'::jsonb")

    # --- discovered candidates (search / rss / list / article) ---
    op.execute(
        """
CREATE TABLE collection_candidates (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                 UUID NOT NULL REFERENCES collection_runs(id) ON DELETE CASCADE,
    source                 VARCHAR(16) NOT NULL
                           CHECK (source IN ('search', 'rss', 'list', 'article')),
    url                    VARCHAR(2048) NOT NULL,
    normalized_url         VARCHAR(2048),
    title                  VARCHAR(512),
    summary                TEXT NOT NULL DEFAULT '',
    provider_rank          INTEGER,
    provider_published_at  TIMESTAMPTZ,
    dedup_key              VARCHAR(64),
    status                 VARCHAR(16) NOT NULL DEFAULT 'discovered'
                           CHECK (status IN ('discovered', 'fetched', 'parsed', 'filtered',
                                             'materialized', 'review_required', 'failed', 'duplicate')),
    error                  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, normalized_url)
)
        """
    )

    # --- per-candidate stage attempts ---
    op.execute(
        """
CREATE TABLE collection_stage_attempts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES collection_candidates(id) ON DELETE CASCADE,
    stage        VARCHAR(16) NOT NULL
                 CHECK (stage IN ('discover', 'fetch', 'parse', 'analyze', 'materialize')),
    status       VARCHAR(16) NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    attempt      INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    error        TEXT,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- immutable content snapshots (raw + markdown + hash + extractor) ---
    op.execute(
        """
CREATE TABLE collection_snapshots (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id     UUID REFERENCES collection_candidates(id) ON DELETE CASCADE,
    result_id        UUID REFERENCES collection_results(id) ON DELETE CASCADE,
    raw_content      TEXT,
    markdown         TEXT,
    content_hash     VARCHAR(64),
    extractor_version VARCHAR(32),
    title            VARCHAR(512),
    date_evidence    TEXT,
    captured_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- LLM analysis results (bound to a body revision + config version) ---
    op.execute(
        """
CREATE TABLE collection_analyses (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope                 VARCHAR(16) NOT NULL DEFAULT 'collection_result'
                          CHECK (scope IN ('collection_result', 'material_revision')),
    result_id             UUID REFERENCES collection_results(id) ON DELETE SET NULL,
    material_id           UUID REFERENCES materials(id) ON DELETE SET NULL,
    material_revision_id  UUID REFERENCES material_revisions(id) ON DELETE SET NULL,
    status                VARCHAR(16) NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    stale                 BOOLEAN NOT NULL DEFAULT FALSE,
    model_config_id       UUID REFERENCES model_configs(id) ON DELETE SET NULL,
    prompt_version        VARCHAR(64) NOT NULL DEFAULT '',
    suggestions           JSONB,
    attempt               INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    usage                 JSONB,
    error                 TEXT,
    logical_key           VARCHAR(64),
    finished_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- idempotent material-ready events ---
    op.execute(
        """
CREATE TABLE material_ready_events (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id           UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    material_revision_id  UUID REFERENCES material_revisions(id) ON DELETE SET NULL,
    event_key             VARCHAR(64) NOT NULL UNIQUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- indexes ---
    op.execute("CREATE INDEX ix_model_configs_purpose ON model_configs (purpose, enabled)")
    op.execute("CREATE INDEX ix_search_configs_enabled ON search_configs (enabled, name)")
    op.execute("CREATE INDEX ix_collection_tasks_mode ON collection_tasks (mode, status)")
    op.execute("CREATE INDEX ix_collection_candidates_run ON collection_candidates (run_id, status)")
    op.execute("CREATE INDEX ix_collection_candidates_dedup ON collection_candidates (dedup_key)")
    op.execute("CREATE INDEX ix_collection_stage_attempts_candidate ON collection_stage_attempts (candidate_id, stage)")
    op.execute("CREATE INDEX ix_collection_snapshots_candidate ON collection_snapshots (candidate_id)")
    op.execute("CREATE INDEX ix_collection_snapshots_result ON collection_snapshots (result_id)")
    op.execute("CREATE INDEX ix_collection_analyses_result ON collection_analyses (result_id, status)")
    op.execute("CREATE INDEX ix_collection_analyses_revision ON collection_analyses (material_revision_id)")
    op.execute("CREATE INDEX ix_collection_analyses_key ON collection_analyses (logical_key)")
    op.execute("CREATE INDEX ix_material_ready_events_material ON material_ready_events (material_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_ready_events")
    op.execute("DROP TABLE IF EXISTS collection_analyses")
    op.execute("DROP TABLE IF EXISTS collection_snapshots")
    op.execute("DROP TABLE IF EXISTS collection_stage_attempts")
    op.execute("DROP TABLE IF EXISTS collection_candidates")
    op.execute("ALTER TABLE materials DROP COLUMN IF EXISTS manual_fields")
    op.execute("ALTER TABLE materials DROP COLUMN IF EXISTS metadata_version")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS config_snapshot")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS review_required_count")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS filtered_count")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS analyzed_count")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS discovered_count")
    op.execute("ALTER TABLE collection_runs DROP CONSTRAINT IF EXISTS ck_collection_runs_end_reason")
    op.execute("ALTER TABLE collection_runs DROP COLUMN IF EXISTS end_reason")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS search_config_id")
    op.execute("ALTER TABLE collection_tasks DROP CONSTRAINT IF EXISTS ck_collection_tasks_apply_policy")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS analysis_apply_policy")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS analysis_model_config_id")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS analysis_enabled")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS max_pages")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS max_fetch")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS max_candidates")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS allowed_domains")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS topic")
    op.execute("ALTER TABLE collection_tasks DROP CONSTRAINT IF EXISTS ck_collection_tasks_mode")
    op.execute("ALTER TABLE collection_tasks DROP COLUMN IF EXISTS mode")
    op.execute("ALTER TABLE collection_sources DROP COLUMN IF EXISTS next_page_selector")
    op.execute("ALTER TABLE collection_sources DROP COLUMN IF EXISTS article_link_selector")
    op.execute("ALTER TABLE collection_sources DROP CONSTRAINT IF EXISTS ck_collection_sources_page_kind")
    op.execute("ALTER TABLE collection_sources DROP COLUMN IF EXISTS page_kind")
    op.execute("DROP TABLE IF EXISTS search_configs")
    op.execute("DROP TABLE IF EXISTS model_configs")
