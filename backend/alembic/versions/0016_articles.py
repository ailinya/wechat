"""Article drafts, immutable revisions and exact material references."""

from alembic import op

revision = "0016_articles"
down_revision = "0015_creation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    creation_task_id UUID REFERENCES creation_tasks(id) ON DELETE RESTRICT,
    slot INTEGER CHECK (slot BETWEEN 1 AND 20),
    origin_type VARCHAR(16) NOT NULL CHECK (origin_type IN ('manual','generated')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending_review' CHECK (status IN ('draft','pending_review','approved','returned','rejected','published')),
    current_revision_id UUID,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((creation_task_id IS NULL AND slot IS NULL) OR (creation_task_id IS NOT NULL AND slot IS NOT NULL)),
    UNIQUE (creation_task_id,slot)
)
    """)
    op.execute("""
CREATE TABLE article_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version >= 1),
    title VARCHAR(512) NOT NULL, author VARCHAR(255) NOT NULL DEFAULT '',
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(keywords)='array'),
    summary TEXT NOT NULL DEFAULT '', body_markdown TEXT NOT NULL,
    cover_object_id UUID REFERENCES stored_objects(id) ON DELETE RESTRICT,
    layout_config JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(layout_config)='object'),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (article_id,version), UNIQUE (id,article_id)
)
    """)
    op.execute("ALTER TABLE articles ADD CONSTRAINT fk_article_current_revision FOREIGN KEY (current_revision_id,id) REFERENCES article_revisions(id,article_id) DEFERRABLE INITIALLY DEFERRED")
    op.execute("ALTER TABLE creation_outputs ADD CONSTRAINT fk_output_article_revision FOREIGN KEY (article_revision_id,article_id) REFERENCES article_revisions(id,article_id) ON DELETE RESTRICT")
    op.execute("""
CREATE TABLE article_materials (
    article_revision_id UUID NOT NULL REFERENCES article_revisions(id) ON DELETE RESTRICT,
    material_id UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    material_revision_id UUID NOT NULL,
    reference_order INTEGER NOT NULL CHECK (reference_order >= 1),
    PRIMARY KEY (article_revision_id,material_id),
    UNIQUE (article_revision_id,reference_order),
    FOREIGN KEY (material_revision_id,material_id) REFERENCES material_revisions(id,material_id) ON DELETE RESTRICT
)
    """)
    op.execute("CREATE INDEX ix_article_materials_material ON article_materials(material_id,article_revision_id)")


def downgrade() -> None:
    op.execute("DROP TABLE article_materials")
    op.execute("ALTER TABLE creation_outputs DROP CONSTRAINT fk_output_article_revision")
    op.execute("ALTER TABLE articles DROP CONSTRAINT fk_article_current_revision")
    op.execute("DROP TABLE article_revisions")
    op.execute("DROP TABLE articles")
