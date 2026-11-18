"""Create revision-scoped chunks and 1024-dimensional embeddings."""

from alembic import op

revision = "0013_material_chunks"
down_revision = "0012_discovery_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
CREATE TABLE material_chunks (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_revision_id       UUID NOT NULL REFERENCES material_revisions(id) ON DELETE CASCADE,
    chunk_index                INTEGER NOT NULL CHECK (chunk_index >= 0),
    content                    TEXT NOT NULL CHECK (length(content) > 0),
    content_hash               VARCHAR(64) NOT NULL CHECK (length(content_hash) = 64),
    embedding                  vector(1024),
    embedding_model_config_id  UUID NOT NULL REFERENCES model_configs(id) ON DELETE RESTRICT,
    embedding_config_version   INTEGER NOT NULL CHECK (embedding_config_version >= 1),
    embedding_model_name       VARCHAR(128) NOT NULL,
    embedding_dimension        SMALLINT NOT NULL DEFAULT 1024 CHECK (embedding_dimension = 1024),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (material_revision_id, chunk_index, embedding_model_config_id, embedding_config_version)
)
        """
    )
    op.execute(
        "CREATE INDEX ix_material_chunks_revision ON material_chunks(material_revision_id, chunk_index)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_chunks_revision")
    op.execute("DROP TABLE IF EXISTS material_chunks")
