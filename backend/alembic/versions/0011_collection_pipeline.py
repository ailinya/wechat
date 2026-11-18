"""Persist collection pipeline leases, stage recovery and candidate results."""

from alembic import op

revision = "0011_collection_pipeline"
down_revision = "0010_analysis_inputs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE collection_runs ADD COLUMN lease_token UUID, ADD COLUMN lease_until TIMESTAMPTZ, ADD COLUMN discovery_completed BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE collection_candidates ADD COLUMN result_id UUID UNIQUE REFERENCES collection_results(id), ADD COLUMN content_type VARCHAR(128), ADD COLUMN http_status INTEGER"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_candidate_stage_attempt ON collection_stage_attempts(candidate_id,stage,attempt)"
    )


def downgrade():
    op.execute("DROP INDEX uq_candidate_stage_attempt")
    op.execute(
        "ALTER TABLE collection_candidates DROP COLUMN http_status, DROP COLUMN content_type, DROP COLUMN result_id"
    )
    op.execute(
        "ALTER TABLE collection_runs DROP COLUMN discovery_completed, DROP COLUMN lease_until, DROP COLUMN lease_token"
    )
