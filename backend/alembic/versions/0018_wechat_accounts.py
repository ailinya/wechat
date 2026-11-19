"""Direct WeChat account identity, encrypted credentials and sync history."""
from alembic import op

revision = '0018_wechat_accounts'
down_revision = '0017_article_reviews'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE wechat_accounts (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR(128) NOT NULL,
 app_id VARCHAR(18) NOT NULL UNIQUE, account_type VARCHAR(16) NOT NULL CHECK(account_type IN ('subscription','service')),
 secret_encrypted TEXT NOT NULL, credential_version INTEGER NOT NULL DEFAULT 1 CHECK(credential_version>0),
 token_encrypted TEXT, token_expires_at TIMESTAMPTZ,
 status VARCHAR(16) NOT NULL CHECK(status IN ('active','invalid','unbound')),
 is_default BOOLEAN NOT NULL DEFAULT false, publish_permission_confirmed BOOLEAN NOT NULL DEFAULT false,
 publish_defaults JSONB NOT NULL DEFAULT '{}'::jsonb, capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
 checked_at TIMESTAMPTZ, authorized_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_synced_at TIMESTAMPTZ,
 error_code VARCHAR(64), created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
    """)
    op.execute('CREATE UNIQUE INDEX ux_wechat_default ON wechat_accounts(is_default) WHERE is_default')
    op.execute('ALTER TABLE creation_rules DROP CONSTRAINT creation_rules_target_account_id_check')
    op.execute('ALTER TABLE creation_rules ADD CONSTRAINT fk_rule_account FOREIGN KEY(target_account_id) REFERENCES wechat_accounts(id) ON DELETE RESTRICT')
    op.execute("""
CREATE TABLE account_sync_runs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), account_id UUID NOT NULL REFERENCES wechat_accounts(id) ON DELETE RESTRICT,
 async_job_id UUID REFERENCES async_jobs(id), status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','succeeded','failed')),
 imported_count INTEGER NOT NULL DEFAULT 0, reused_count INTEGER NOT NULL DEFAULT 0, error_code VARCHAR(64),
 created_by UUID REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ
)
    """)
    op.execute("""
CREATE TABLE account_synced_materials (
 account_id UUID NOT NULL REFERENCES wechat_accounts(id), media_id VARCHAR(256) NOT NULL, item_index INTEGER NOT NULL CHECK(item_index>=0),
 material_id UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT, sync_run_id UUID NOT NULL REFERENCES account_sync_runs(id),
 PRIMARY KEY(account_id,media_id,item_index)
)
    """)
    op.execute('CREATE INDEX ix_account_sync_history ON account_sync_runs(account_id,created_at DESC,id DESC)')


def downgrade():
    op.execute('DROP TABLE account_synced_materials')
    op.execute('DROP TABLE account_sync_runs')
    op.execute('ALTER TABLE creation_rules DROP CONSTRAINT fk_rule_account')
    # A downgrade with real target bindings must fail rather than discard them.
    op.execute('ALTER TABLE creation_rules ADD CONSTRAINT creation_rules_target_account_id_check CHECK(target_account_id IS NULL)')
    op.execute('DROP TABLE wechat_accounts')
