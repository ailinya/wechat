"""Add the source creator reference expected by existing source CRUD.

Revision ID: 0008_collection_source_creator
Revises: 0007_collection_discoveries
"""
from alembic import op

revision = "0008_collection_source_creator"
down_revision = "0007_collection_discoveries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE collection_sources ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL")


def downgrade():
    op.execute("ALTER TABLE collection_sources DROP COLUMN created_by")
