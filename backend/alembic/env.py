"""Alembic environment.

Migrations are written as raw SQL through ``op.execute`` so that constraints,
indexes and PostgreSQL-specific types stay explicit and reviewable. The target
metadata is therefore intentionally empty; autogenerate is not used.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# No SQLAlchemy ORM metadata: migrations are explicit raw SQL.
target_metadata = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required to run migrations, e.g. "
            "postgresql+psycopg://user:password@host:5432/wetchat"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
