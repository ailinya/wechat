"""Track idempotent embedding builds per material revision and config version."""

from alembic import op

revision = "0014_material_embedding_runs"
down_revision = "0013_material_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE material_embedding_runs (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_revision_id       UUID NOT NULL REFERENCES material_revisions(id) ON DELETE CASCADE,
    embedding_model_config_id  UUID NOT NULL REFERENCES model_configs(id) ON DELETE RESTRICT,
    embedding_config_version   INTEGER NOT NULL CHECK (embedding_config_version >= 1),
    async_job_id               UUID UNIQUE REFERENCES async_jobs(id) ON DELETE SET NULL,
    status                     VARCHAR(16) NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    attempts                   SMALLINT NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    error_code                 VARCHAR(128),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                TIMESTAMPTZ,
    UNIQUE (material_revision_id, embedding_model_config_id, embedding_config_version)
)
        """
    )
    op.execute(
        "CREATE INDEX ix_material_embedding_runs_status ON material_embedding_runs(status, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_embedding_runs_status")
    op.execute("DROP TABLE IF EXISTS material_embedding_runs")
