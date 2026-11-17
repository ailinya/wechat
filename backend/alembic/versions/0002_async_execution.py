"""Create async-execution schema.

Creates async_jobs (persistent task state), outbox_events (transactional
outbox), operation_logs (cross-module audit), stored_objects (registered
attachments), idempotency_keys (persisted request protection) and
upload_grants (short-lived upload authorizations).

Revision ID: 0002_async_execution
Revises: 0001_access_control
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0002_async_execution"
down_revision = "0001_access_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # async_jobs: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE async_jobs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type       VARCHAR(64) NOT NULL,
    resource_type  VARCHAR(64) NOT NULL,
    resource_id    UUID NOT NULL,
    created_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status         VARCHAR(16) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    stage          VARCHAR(64) NOT NULL DEFAULT '',
    progress       SMALLINT NOT NULL DEFAULT 0
                   CHECK (progress >= 0 AND progress <= 100),
    attempts       SMALLINT NOT NULL DEFAULT 0,
    last_error     TEXT,
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # outbox_events: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE outbox_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type     VARCHAR(64) NOT NULL,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id   UUID NOT NULL,
    payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status         VARCHAR(16) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'dispatched', 'failed')),
    attempts       SMALLINT NOT NULL DEFAULT 0,
    last_error     TEXT,
    available_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # operation_logs: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE operation_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(64) NOT NULL,
    object_type VARCHAR(64) NOT NULL,
    object_id   UUID,
    result      VARCHAR(16) NOT NULL
                CHECK (result IN ('success', 'denied', 'failed')),
    detail      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # stored_objects: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE stored_objects (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket       VARCHAR(64) NOT NULL,
    object_key   VARCHAR(255) NOT NULL,
    size_bytes   BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type VARCHAR(128) NOT NULL,
    sha256       VARCHAR(64) NOT NULL,
    uploader_id  UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bucket, object_key)
)
        """
    )

    # idempotency_keys: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE idempotency_keys (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope               VARCHAR(64) NOT NULL,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key                 VARCHAR(128) NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    resource_id         UUID,
    response_status     SMALLINT,
    response_body       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (scope, user_id, key)
)
        """
    )

    # upload_grants: created with explicit constraints; see docstring for purpose.
    op.execute(
        """
CREATE TABLE upload_grants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bucket       VARCHAR(64) NOT NULL,
    object_key   VARCHAR(255) NOT NULL,
    max_bytes    BIGINT NOT NULL CHECK (max_bytes > 0),
    content_type VARCHAR(128) NOT NULL,
    token_hash   VARCHAR(64) NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (bucket, object_key, created_at)
)
        """
    )

    op.execute("CREATE INDEX ix_async_jobs_type_resource ON async_jobs (job_type, resource_id, created_at)")
    op.execute("CREATE INDEX ix_async_jobs_status ON async_jobs (status, created_at)")
    op.execute("CREATE INDEX ix_async_jobs_created_by ON async_jobs (created_by, created_at)")
    op.execute("CREATE INDEX ix_outbox_pickup ON outbox_events (status, available_at)")
    op.execute("CREATE INDEX ix_outbox_aggregate ON outbox_events (aggregate_type, aggregate_id)")
    op.execute("CREATE INDEX ix_operation_logs_user_time ON operation_logs (user_id, created_at)")
    op.execute("CREATE INDEX ix_operation_logs_object ON operation_logs (object_type, object_id)")
    op.execute("CREATE INDEX ix_operation_logs_action ON operation_logs (action, created_at)")
    op.execute("CREATE INDEX ix_stored_objects_uploader ON stored_objects (uploader_id, created_at)")
    op.execute("CREATE INDEX ix_idempotency_expiry ON idempotency_keys (expires_at)")
    op.execute("CREATE INDEX ix_upload_grants_user ON upload_grants (user_id, created_at)")
    op.execute("CREATE INDEX ix_upload_grants_expiry ON upload_grants (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS upload_grants")
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP TABLE IF EXISTS stored_objects")
    op.execute("DROP TABLE IF EXISTS operation_logs")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS async_jobs")
