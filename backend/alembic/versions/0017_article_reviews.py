"""Version-bound human reviews and review queue indexes."""
from alembic import op

revision = '0017_article_reviews'
down_revision = '0016_articles'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE articles ADD COLUMN submitted_at TIMESTAMPTZ")
    op.execute("UPDATE articles SET submitted_at=created_at WHERE status='pending_review'")
    op.execute("""
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id UUID NOT NULL REFERENCES articles(id) ON DELETE RESTRICT,
    article_revision_id UUID NOT NULL,
    action VARCHAR(16) NOT NULL CHECK (action IN ('approve','return','reject')),
    checklist JSONB NOT NULL CHECK (jsonb_typeof(checklist)='object'),
    comment TEXT NOT NULL DEFAULT '',
    reviewer_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (article_revision_id,article_id) REFERENCES article_revisions(id,article_id) ON DELETE RESTRICT,
    CHECK (action='approve' OR length(trim(comment)) > 0)
)
    """)
    op.execute('CREATE INDEX ix_reviews_revision ON reviews(article_revision_id,created_at,id)')
    op.execute('CREATE INDEX ix_articles_list ON articles(created_at DESC,id DESC)')
    op.execute("CREATE INDEX ix_articles_review_queue ON articles(submitted_at,id) WHERE status='pending_review'")


def downgrade():
    op.execute('DROP TABLE reviews')
    op.execute('DROP INDEX ix_articles_review_queue')
    op.execute('DROP INDEX ix_articles_list')
    op.execute('ALTER TABLE articles DROP COLUMN submitted_at')
