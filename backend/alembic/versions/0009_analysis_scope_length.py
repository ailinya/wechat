"""Allow the declared collection analysis scope value.

Revision ID: 0009_analysis_scope_length
Revises: 0008_collection_source_creator
"""
from alembic import op
from sqlalchemy import text

revision = "0009_analysis_scope_length"
down_revision = "0008_collection_source_creator"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE collection_analyses ALTER COLUMN scope TYPE VARCHAR(32)")


def downgrade():
    bind = op.get_bind()
    has_long_scope = bind.execute(text(
        "SELECT EXISTS (SELECT 1 FROM collection_analyses WHERE length(scope) > 16)"
    )).scalar_one()
    if has_long_scope:
        raise RuntimeError("Cannot narrow analysis scope while collection_result rows exist")
    op.execute("ALTER TABLE collection_analyses ALTER COLUMN scope TYPE VARCHAR(16)")
