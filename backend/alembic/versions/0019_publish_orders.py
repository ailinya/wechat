"""Revision-bound, explicitly confirmed publication orders and attempts."""
from alembic import op

revision = '0019_publish_orders'
down_revision = '0018_wechat_accounts'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE publish_orders (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), article_id UUID NOT NULL REFERENCES articles(id),
 article_revision_id UUID NOT NULL, account_id UUID NOT NULL REFERENCES wechat_accounts(id),
 mode VARCHAR(16) NOT NULL CHECK(mode IN ('immediate','scheduled')), scheduled_at TIMESTAMPTZ,
 publish_note TEXT NOT NULL DEFAULT '', publish_defaults JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(32) NOT NULL DEFAULT 'awaiting_confirmation'
 CHECK(status IN ('awaiting_confirmation','confirmed','preparing','submitting','publishing','unknown','succeeded','failed','cancelled')),
 confirmed_by UUID REFERENCES users(id), confirmed_at TIMESTAMPTZ, async_job_id UUID REFERENCES async_jobs(id),
 error_code VARCHAR(64), created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(article_revision_id,article_id) REFERENCES article_revisions(id,article_id),
 CHECK((mode='immediate' AND scheduled_at IS NULL) OR (mode='scheduled' AND scheduled_at IS NOT NULL)),
 CHECK((confirmed_by IS NULL)=(confirmed_at IS NULL))
)
    """)
    op.execute("CREATE UNIQUE INDEX ux_publish_live_order ON publish_orders(article_revision_id,account_id) WHERE status NOT IN ('failed','cancelled')")
    op.execute('CREATE INDEX ix_publish_due ON publish_orders(status,scheduled_at)')
    op.execute('CREATE INDEX ix_publish_article ON publish_orders(article_id,created_at DESC,id DESC)')
    op.execute("""
CREATE TABLE publish_attempts (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), order_id UUID NOT NULL REFERENCES publish_orders(id),
 attempt_no INTEGER NOT NULL CHECK(attempt_no>0), status VARCHAR(16) NOT NULL CHECK(status IN ('preparing','submitting','publishing','unknown','succeeded','failed')),
 draft_media_id VARCHAR(256), publish_id VARCHAR(256), article_id_external VARCHAR(256), article_url TEXT,
 error_code VARCHAR(64), result JSONB NOT NULL DEFAULT '{}'::jsonb,
 started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 reconciled_by UUID REFERENCES users(id), reconciliation_note TEXT,
 UNIQUE(order_id,attempt_no)
)
    """)
    op.execute('CREATE INDEX ix_publish_attempt_order ON publish_attempts(order_id,attempt_no DESC)')


def downgrade():
    op.execute('DROP TABLE publish_attempts')
    op.execute('DROP TABLE publish_orders')
