"""Persist source/article discovery provenance (task 3.18).

Revision ID: 0007_collection_discoveries
Revises: 0006_collection_search
"""
from alembic import op

revision = "0007_collection_discoveries"
down_revision = "0006_collection_search"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE collection_candidate_discoveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID NOT NULL REFERENCES collection_candidates(id) ON DELETE CASCADE,
    source_id UUID REFERENCES collection_sources(id) ON DELETE SET NULL,
    discovery_type VARCHAR(16) NOT NULL CHECK (discovery_type IN ('rss', 'list', 'article')),
    discovery_url VARCHAR(2048) NOT NULL,
    page_number INTEGER NOT NULL DEFAULT 1 CHECK (page_number >= 1),
    provenance_key VARCHAR(64) NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    published_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, source_id, discovery_url, discovery_type, provenance_key)
)
""")
    op.execute("CREATE INDEX ix_candidate_discoveries_source ON collection_candidate_discoveries (source_id, created_at)")


def downgrade():
    op.execute("DROP TABLE collection_candidate_discoveries")
