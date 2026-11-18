"""Persist fixed search queries, evidence and durable call budgets.

Revision ID: 0006_collection_search
Revises: 0005_collection_enhancement
"""
from alembic import op

revision = "0006_collection_search"
down_revision = "0005_collection_enhancement"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE collection_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES collection_runs(id) ON DELETE CASCADE,
    search_config_id UUID NOT NULL REFERENCES search_configs(id),
    config_snapshot JSONB NOT NULL,
    query TEXT NOT NULL,
    allowed_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    max_results INTEGER NOT NULL CHECK (max_results BETWEEN 1 AND 20),
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    evidence JSONB,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (window_start <= window_end)
)
""")


def downgrade():
    op.execute("DROP TABLE collection_searches")
