"""Creation rules, immutable input selections and recoverable output slots."""

from alembic import op

revision = "0015_creation"
down_revision = "0014_material_embedding_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE creation_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL DEFAULT '', topic VARCHAR(500) NOT NULL DEFAULT '',
    trigger_type VARCHAR(32) NOT NULL CHECK (trigger_type IN ('collection_completed','schedule','new_material_count','manual')),
    trigger_config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(trigger_config)='object'),
    material_strategy VARCHAR(32) NOT NULL DEFAULT 'new_and_unused' CHECK (material_strategy IN ('new_only','new_and_unused','all')),
    filters JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters)='object'),
    min_new_material_count INTEGER NOT NULL DEFAULT 1 CHECK (min_new_material_count BETWEEN 0 AND 100),
    min_material_count INTEGER NOT NULL DEFAULT 1 CHECK (min_material_count BETWEEN 1 AND 100),
    min_relevance DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (min_relevance BETWEEN 0 AND 1),
    reference_count INTEGER NOT NULL DEFAULT 3 CHECK (reference_count BETWEEN 1 AND 100),
    batch_count INTEGER NOT NULL DEFAULT 1 CHECK (batch_count BETWEEN 1 AND 20),
    article_type VARCHAR(64) NOT NULL DEFAULT 'news', writing_style VARCHAR(128) NOT NULL DEFAULT '客观',
    min_words INTEGER NOT NULL DEFAULT 300 CHECK (min_words BETWEEN 1 AND 20000),
    max_words INTEGER NOT NULL DEFAULT 1200 CHECK (max_words BETWEEN min_words AND 20000),
    model_config_id UUID NOT NULL REFERENCES model_configs(id) ON DELETE RESTRICT,
    prompt TEXT NOT NULL DEFAULT '', require_analysis BOOLEAN NOT NULL DEFAULT false,
    target_account_id UUID CHECK (target_account_id IS NULL), enabled BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
    """)
    op.execute("""
CREATE TABLE creation_rule_collection_tasks (
    rule_id UUID NOT NULL REFERENCES creation_rules(id) ON DELETE CASCADE,
    collection_task_id UUID NOT NULL REFERENCES collection_tasks(id) ON DELETE RESTRICT,
    PRIMARY KEY (rule_id,collection_task_id)
)
    """)
    op.execute("""
CREATE TABLE creation_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID REFERENCES creation_rules(id) ON DELETE RESTRICT,
    source_task_id UUID REFERENCES creation_tasks(id) ON DELETE RESTRICT,
    mode VARCHAR(16) NOT NULL CHECK (mode IN ('automatic','material','topic')),
    topic VARCHAR(500) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','insufficient','succeeded','failed','cancelled')),
    trigger_type VARCHAR(32) NOT NULL CHECK (trigger_type IN ('collection_completed','schedule','new_material_count','manual')),
    trigger_source VARCHAR(255), trigger_window VARCHAR(255) NOT NULL,
    request_key VARCHAR(128), request_fingerprint VARCHAR(64),
    config_snapshot JSONB NOT NULL CHECK (jsonb_typeof(config_snapshot)='object'),
    decision JSONB CHECK (decision IS NULL OR jsonb_typeof(decision)='object'),
    stages JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(stages)='object'),
    async_job_id UUID REFERENCES async_jobs(id) ON DELETE SET NULL,
    error_code VARCHAR(128), created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((mode='automatic' AND rule_id IS NOT NULL) OR mode <> 'automatic')
)
    """)
    op.execute("CREATE UNIQUE INDEX uq_creation_rule_window ON creation_tasks(rule_id, trigger_type, trigger_window) WHERE rule_id IS NOT NULL AND source_task_id IS NULL")
    op.execute("CREATE UNIQUE INDEX uq_creation_user_request ON creation_tasks(created_by,request_key) WHERE request_key IS NOT NULL AND created_by IS NOT NULL")
    op.execute("CREATE INDEX ix_creation_tasks_status_created ON creation_tasks(status,created_at DESC)")
    op.execute("""
CREATE TABLE creation_task_materials (
    creation_task_id UUID NOT NULL REFERENCES creation_tasks(id) ON DELETE CASCADE,
    material_id UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    material_revision_id UUID NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT false,
    relevance_score DOUBLE PRECISION CHECK (relevance_score BETWEEN 0 AND 1),
    selection_reason VARCHAR(255) NOT NULL DEFAULT '',
    PRIMARY KEY (creation_task_id,material_id),
    FOREIGN KEY (material_revision_id,material_id) REFERENCES material_revisions(id,material_id) ON DELETE RESTRICT
)
    """)
    op.execute("""
CREATE TABLE creation_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    creation_task_id UUID NOT NULL REFERENCES creation_tasks(id) ON DELETE RESTRICT,
    slot INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 20),
    article_id UUID NOT NULL, article_revision_id UUID NOT NULL,
    title VARCHAR(512) NOT NULL, candidate_titles JSONB NOT NULL CHECK (jsonb_typeof(candidate_titles)='array'),
    summary TEXT NOT NULL, outline JSONB NOT NULL CHECK (jsonb_typeof(outline)='array'),
    body_markdown TEXT NOT NULL, keywords JSONB NOT NULL CHECK (jsonb_typeof(keywords)='array'),
    cover_suggestion TEXT NOT NULL, citations JSONB NOT NULL CHECK (jsonb_typeof(citations)='array'),
    model_config_id UUID NOT NULL REFERENCES model_configs(id) ON DELETE RESTRICT,
    model_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(model_snapshot)='object'),
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (creation_task_id,slot), UNIQUE (article_id), UNIQUE (article_revision_id)
)
    """)
    op.execute("""
CREATE TABLE creation_consumed_events (
    event_id UUID NOT NULL REFERENCES outbox_events(id) ON DELETE RESTRICT,
    rule_id UUID NOT NULL REFERENCES creation_rules(id) ON DELETE RESTRICT,
    creation_task_id UUID REFERENCES creation_tasks(id) ON DELETE RESTRICT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id,rule_id)
)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE creation_consumed_events")
    op.execute("DROP TABLE creation_outputs")
    op.execute("DROP TABLE creation_task_materials")
    op.execute("DROP TABLE creation_tasks")
    op.execute("DROP TABLE creation_rule_collection_tasks")
    op.execute("DROP TABLE creation_rules")
