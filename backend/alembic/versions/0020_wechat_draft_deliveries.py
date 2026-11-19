"""Approved-revision draft delivery and explicitly sourced manual publication."""
from alembic import op

revision = '0020_wechat_draft_deliveries'
down_revision = '0019_publish_orders'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE wechat_draft_deliveries (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), article_id UUID NOT NULL REFERENCES articles(id),
 article_revision_id UUID NOT NULL, account_id UUID NOT NULL REFERENCES wechat_accounts(id),
 status VARCHAR(32) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','preparing','syncing','unknown','awaiting_manual_publish','manual_published','failed','cancelled')),
 publish_defaults JSONB NOT NULL, note TEXT NOT NULL DEFAULT '',
 confirmed_by UUID NOT NULL REFERENCES users(id), confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 async_job_id UUID REFERENCES async_jobs(id), remote_media_id TEXT, error_code VARCHAR(64),
 manual_published_by UUID REFERENCES users(id), manual_published_at TIMESTAMPTZ, manual_article_url TEXT, manual_note TEXT,
 publication_source VARCHAR(16) CHECK(publication_source='operator'),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(article_revision_id,article_id) REFERENCES article_revisions(id,article_id),
 CHECK(status<>'awaiting_manual_publish' OR remote_media_id IS NOT NULL),
 CHECK(status<>'manual_published' OR (remote_media_id IS NOT NULL AND manual_published_by IS NOT NULL AND manual_published_at IS NOT NULL AND manual_article_url IS NOT NULL AND manual_note IS NOT NULL AND length(trim(manual_note))>0 AND publication_source IS NOT NULL))
)
    """)
    op.execute("CREATE UNIQUE INDEX ux_draft_delivery_active ON wechat_draft_deliveries(article_revision_id,account_id) WHERE status NOT IN ('failed','cancelled')")
    op.execute('CREATE INDEX ix_draft_delivery_article ON wechat_draft_deliveries(article_id,created_at DESC,id DESC)')
    op.execute("""
CREATE TABLE wechat_draft_attempts (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), delivery_id UUID NOT NULL REFERENCES wechat_draft_deliveries(id),
 attempt_no INTEGER NOT NULL CHECK(attempt_no>0),
 status VARCHAR(16) NOT NULL CHECK(status IN ('preparing','syncing','unknown','synced','failed')),
 expected_payload JSONB NOT NULL DEFAULT '{}'::jsonb, remote_media_id TEXT, error_code VARCHAR(64),
 started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 reconciled_by UUID REFERENCES users(id), reconciliation_note TEXT,
 UNIQUE(delivery_id,attempt_no)
)
    """)


def downgrade():
    op.execute('DROP TABLE wechat_draft_attempts')
    op.execute('DROP TABLE wechat_draft_deliveries')
