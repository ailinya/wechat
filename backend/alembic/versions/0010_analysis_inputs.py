"""Bind analysis attempts to immutable input and bounded execution leases."""
from alembic import op

revision = "0010_analysis_inputs"
down_revision = "0009_analysis_scope_length"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE collection_analyses ADD COLUMN snapshot_id UUID REFERENCES collection_snapshots(id)")
    op.execute("ALTER TABLE collection_analyses ADD COLUMN input_hash VARCHAR(64)")
    op.execute("ALTER TABLE collection_analyses ADD COLUMN input_context JSONB")
    op.execute("ALTER TABLE collection_analyses ADD COLUMN config_snapshot JSONB")
    op.execute("ALTER TABLE collection_analyses ADD COLUMN lease_until TIMESTAMPTZ")
    op.execute("ALTER TABLE collection_analyses ADD COLUMN target_revision_id UUID REFERENCES material_revisions(id)")
    op.execute("CREATE UNIQUE INDEX uq_analysis_attempt ON collection_analyses(logical_key, attempt) WHERE snapshot_id IS NOT NULL")


def downgrade():
    op.execute("DROP INDEX uq_analysis_attempt")
    for column in ("target_revision_id", "lease_until", "config_snapshot", "input_context", "input_hash", "snapshot_id"):
        op.execute(f"ALTER TABLE collection_analyses DROP COLUMN {column}")
