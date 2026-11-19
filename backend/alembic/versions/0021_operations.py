"""Platform settings, private notifications and nullable metric snapshots."""
from alembic import op

revision = '0021_operations'
down_revision = '0020_wechat_draft_deliveries'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE system_settings (
 key VARCHAR(64) PRIMARY KEY, value JSONB NOT NULL CHECK(jsonb_typeof(value)='object'),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version>0), updated_by UUID REFERENCES users(id),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO system_settings(key,value) VALUES ('platform','{"name":"智媒助手","description":"微信公众号内容生产与运营管理平台","brand_mark":"智","timezone":"Asia/Shanghai"}');
CREATE TABLE notification_preferences (
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 category VARCHAR(16) NOT NULL CHECK(category IN ('collection','creation','review','publishing','exception')),
 channel VARCHAR(16) NOT NULL DEFAULT 'in_app' CHECK(channel='in_app'), enabled BOOLEAN NOT NULL DEFAULT true,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id,category,channel)
);
CREATE TABLE notifications (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), recipient_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 event_key VARCHAR(255) NOT NULL, channel VARCHAR(16) NOT NULL DEFAULT 'in_app' CHECK(channel='in_app'),
 category VARCHAR(16) NOT NULL CHECK(category IN ('collection','creation','review','publishing','exception')),
 title VARCHAR(255) NOT NULL, body TEXT NOT NULL DEFAULT '', url TEXT NOT NULL,
 required_permission VARCHAR(64) NOT NULL REFERENCES permissions(code),
 occurred_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), read_at TIMESTAMPTZ,
 UNIQUE(recipient_id,event_key,channel)
);
CREATE INDEX ix_notification_recipient ON notifications(recipient_id,created_at DESC,id DESC);
CREATE INDEX ix_notification_unread ON notifications(recipient_id,created_at DESC) WHERE read_at IS NULL;
CREATE TABLE account_article_metrics (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), account_id UUID NOT NULL REFERENCES wechat_accounts(id),
 article_id UUID REFERENCES articles(id), external_article_id TEXT NOT NULL,
 metric_date DATE NOT NULL, collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 availability VARCHAR(16) NOT NULL CHECK(availability IN ('available','partial','unavailable')),
 reads BIGINT CHECK(reads>=0), likes BIGINT CHECK(likes>=0), shares BIGINT CHECK(shares>=0),
 reason VARCHAR(255) NOT NULL DEFAULT '',
 CHECK(availability<>'unavailable' OR (reads IS NULL AND likes IS NULL AND shares IS NULL)),
 UNIQUE(account_id,external_article_id,metric_date)
);
CREATE INDEX ix_account_metrics_time ON account_article_metrics(account_id,metric_date DESC,collected_at DESC);
    """)


def downgrade():
    for table in ['account_article_metrics', 'notifications', 'notification_preferences', 'system_settings']:
        op.execute(f'DROP TABLE {table}')
