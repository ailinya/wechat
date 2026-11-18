"""Retain per-source discovery progress across partial run recovery."""

from alembic import op

revision = "0012_discovery_recovery"
down_revision = "0011_collection_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE collection_runs ADD COLUMN discovery_state JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade():
    op.execute("ALTER TABLE collection_runs DROP COLUMN discovery_state")
