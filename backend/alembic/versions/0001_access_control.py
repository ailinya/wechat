"""Create access-control schema.

Creates users, roles, permissions, user_roles, role_permissions and the
revocable sessions table, with explicit UUID primary keys, timezone-aware
timestamps, password hashing support, uniqueness and status constraints.
Seeds the four baseline roles required by the access-control capability.

Revision ID: 0001_access_control
Revises:
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0001_access_control"
down_revision = None
branch_labels = None
depends_on = None


BASELINE_ROLES = (
    ("admin", "系统管理员"),
    ("operations", "运营"),
    ("editor", "内容编辑"),
    ("reviewer", "内容审核"),
)


def upgrade() -> None:
    # gen_random_uuid() is core in PostgreSQL 13+; pgcrypto keeps older hosts working.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE roles (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        VARCHAR(64) NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE permissions (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code        VARCHAR(128) NOT NULL UNIQUE,
            module      VARCHAR(64) NOT NULL,
            action      VARCHAR(64) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account       VARCHAR(64) NOT NULL UNIQUE,
            name          VARCHAR(128) NOT NULL,
            contact       VARCHAR(255),
            status        VARCHAR(16) NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'disabled')),
            password_hash TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE user_roles (
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id    UUID NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, role_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE role_permissions (
            role_id       UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE RESTRICT,
            PRIMARY KEY (role_id, permission_id)
        )
        """
    )

    # Revocable sessions: only a hash of the bearer token is stored, never the
    # raw token. A session can be ended by setting revoked_at or letting it
    # expire; disabling the user also invalidates it at request time.
    op.execute(
        """
        CREATE TABLE sessions (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX ix_users_status ON users (status)")
    op.execute("CREATE INDEX ix_user_roles_role_id ON user_roles (role_id)")
    op.execute(
        "CREATE INDEX ix_role_permissions_permission_id "
        "ON role_permissions (permission_id)"
    )
    op.execute("CREATE INDEX ix_permissions_module ON permissions (module)")
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute("CREATE INDEX ix_sessions_expires_at ON sessions (expires_at)")

    role_rows = ",\n".join(
        f"('{name}', '{description}')" for name, description in BASELINE_ROLES
    )
    op.execute(
        f"INSERT INTO roles (name, description) VALUES {role_rows} "
        "ON CONFLICT (name) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
