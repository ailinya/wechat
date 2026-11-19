"""Persist assistance runs, immutable input revisions and separate suggestions."""
from alembic import op

revision = '0025_intelligence_assistance'
down_revision = '0024_material_counts'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE assistance_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind varchar(16) NOT NULL CHECK (kind IN ('topic','relation','search','quality')),
    status varchar(16) NOT NULL CHECK (status IN ('running','succeeded','failed')),
    created_by uuid NOT NULL REFERENCES users(id),
    algorithm_version text NOT NULL,
    model_config_id uuid REFERENCES model_configs(id),
    model_version integer,
    model_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(model_snapshot)='object'),
    article_id uuid,
    article_revision_id uuid,
    input jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(input)='object'),
    result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result)='object'),
    usage jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(usage)='object'),
    error_code text,
    elapsed_ms integer CHECK (elapsed_ms >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    FOREIGN KEY (article_revision_id, article_id) REFERENCES article_revisions(id, article_id),
    CHECK ((article_id IS NULL) = (article_revision_id IS NULL)),
    CHECK ((model_config_id IS NULL) = (model_version IS NULL))
);
CREATE INDEX ix_assistance_runs_creator ON assistance_runs(created_by,created_at DESC,id DESC);
CREATE TABLE assistance_run_materials (
    run_id uuid NOT NULL REFERENCES assistance_runs(id) ON DELETE CASCADE,
    material_id uuid NOT NULL,
    revision_id uuid NOT NULL,
    PRIMARY KEY(run_id,material_id),
    FOREIGN KEY(revision_id,material_id) REFERENCES material_revisions(id,material_id)
);
CREATE TABLE assistance_relations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES assistance_runs(id),
    source_material_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    target_material_id uuid NOT NULL,
    target_revision_id uuid NOT NULL,
    algorithm_version text NOT NULL,
    score double precision NOT NULL CHECK(score BETWEEN 0 AND 1),
    evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
    ignored_by uuid REFERENCES users(id),
    ignored_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(source_revision_id,source_material_id) REFERENCES material_revisions(id,material_id),
    FOREIGN KEY(target_revision_id,target_material_id) REFERENCES material_revisions(id,material_id),
    CHECK(source_material_id <> target_material_id),
    CHECK((ignored_by IS NULL) = (ignored_at IS NULL)),
    UNIQUE(source_revision_id,target_revision_id,algorithm_version)
);
CREATE INDEX ix_assistance_relations_source ON assistance_relations(source_material_id,created_at DESC);
""")


def downgrade():
    op.execute('DROP TABLE assistance_relations')
    op.execute('DROP TABLE assistance_run_materials')
    op.execute('DROP TABLE assistance_runs')
