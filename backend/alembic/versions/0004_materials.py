"""Create material-library schema (task 3.3).

Creates material_categories, materials, material_revisions, tags,
material_tags, material_files, material_relations and material_favorites.
Revision numbers are unique per material; link tables are deduplicated by
unique keys; materials.current_revision_id is constrained (composite FK) to a
revision that belongs to the same material; deletes are retention-safe
(soft delete + RESTRICT/SET NULL so existing references stay resolvable).
Also adds the deferred FK from collection_results.material_id -> materials.

Revision ID: 0004_materials
Revises: 0003_collection
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0004_materials"
down_revision = "0003_collection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- categories (self-referencing tree) ---
    op.execute(
        """
CREATE TABLE material_categories (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR(64) NOT NULL,
    parent_id  UUID REFERENCES material_categories(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (parent_id IS NULL OR parent_id <> id)
)
        """
    )

    # --- materials ---
    op.execute(
        """
CREATE TABLE materials (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title              VARCHAR(256) NOT NULL,
    summary            TEXT NOT NULL DEFAULT '',
    material_type      VARCHAR(32) NOT NULL DEFAULT 'document',
    origin             VARCHAR(16) NOT NULL DEFAULT 'manual'
                       CHECK (origin IN ('collection', 'upload', 'link', 'manual',
                                         'article', 'enterprise')),
    usage_status       VARCHAR(20) NOT NULL DEFAULT 'pending_review'
                       CHECK (usage_status IN ('pending_review', 'ready_to_use',
                                               'partially_used', 'used', 'archived',
                                               'duplicate')),
    category_id        UUID REFERENCES material_categories(id) ON DELETE SET NULL,
    current_revision_id UUID,
    deleted_at         TIMESTAMPTZ,
    created_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- revisions (immutable history; unique revision_no per material) ---
    op.execute(
        """
CREATE TABLE material_revisions (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id            UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    revision_no            INTEGER NOT NULL CHECK (revision_no >= 1),
    content_markdown       TEXT NOT NULL,
    content_hash           VARCHAR(64),
    file_ids               JSONB NOT NULL DEFAULT '[]'::jsonb
                           CHECK (jsonb_typeof(file_ids) = 'array'),
    created_from_result_id UUID REFERENCES collection_results(id) ON DELETE SET NULL,
    created_by             UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (material_id, revision_no),
    UNIQUE (id, material_id)
)
        """
    )

    # current_revision_id must point at a revision of THIS material.
    # Deferred so a material and its first revision can be created in one txn.
    op.execute(
        """
ALTER TABLE materials
ADD CONSTRAINT fk_materials_current_revision
FOREIGN KEY (current_revision_id, id) REFERENCES material_revisions (id, material_id)
DEFERRABLE INITIALLY DEFERRED
        """
    )

    # --- tags ---
    op.execute(
        """
CREATE TABLE tags (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
        """
    )

    # --- material <-> tags (dedup) ---
    op.execute(
        """
CREATE TABLE material_tags (
    material_id UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    tag_id      UUID NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (material_id, tag_id)
)
        """
    )

    # --- material <-> stored files (dedup by material/file/role) ---
    op.execute(
        """
CREATE TABLE material_files (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id    UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    stored_object_id UUID NOT NULL REFERENCES stored_objects(id) ON DELETE RESTRICT,
    role           VARCHAR(32) NOT NULL DEFAULT 'attachment',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (material_id, stored_object_id, role)
)
        """
    )

    # --- material relations (duplicate_of / update_of / related_to) ---
    op.execute(
        """
CREATE TABLE material_relations (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_material_id UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    target_material_id UUID NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    relation_type      VARCHAR(16) NOT NULL
                       CHECK (relation_type IN ('duplicate_of', 'update_of', 'related_to')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_material_id, target_material_id, relation_type),
    CHECK (source_material_id <> target_material_id)
)
        """
    )

    # --- favorites (per-user isolated, dedup) ---
    op.execute(
        """
CREATE TABLE material_favorites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_id UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (material_id, user_id)
)
        """
    )

    # --- deferred FK from collection results to the materialized material ---
    op.execute(
        """
ALTER TABLE collection_results
ADD CONSTRAINT fk_collection_results_material
FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL
        """
    )

    # --- indexes ---
    op.execute("CREATE INDEX ix_materials_status ON materials (usage_status, created_at)")
    op.execute("CREATE INDEX ix_materials_category ON materials (category_id, created_at)")
    op.execute("CREATE INDEX ix_materials_origin ON materials (origin, created_at)")
    op.execute("CREATE INDEX ix_materials_deleted ON materials (deleted_at)")
    op.execute("CREATE INDEX ix_material_revisions_material ON material_revisions (material_id, revision_no)")
    op.execute("CREATE INDEX ix_material_revisions_result ON material_revisions (created_from_result_id)")
    op.execute("CREATE INDEX ix_material_tags_tag ON material_tags (tag_id)")
    op.execute("CREATE INDEX ix_material_files_object ON material_files (stored_object_id)")
    op.execute("CREATE INDEX ix_material_relations_source ON material_relations (source_material_id, relation_type)")
    op.execute("CREATE INDEX ix_material_relations_target ON material_relations (target_material_id, relation_type)")
    op.execute("CREATE INDEX ix_material_favorites_user ON material_favorites (user_id, created_at)")


def downgrade() -> None:
    op.execute("ALTER TABLE collection_results DROP CONSTRAINT IF EXISTS fk_collection_results_material")
    op.execute("DROP TABLE IF EXISTS material_favorites")
    op.execute("DROP TABLE IF EXISTS material_relations")
    op.execute("DROP TABLE IF EXISTS material_files")
    op.execute("DROP TABLE IF EXISTS material_tags")
    op.execute("DROP TABLE IF EXISTS tags")
    op.execute("ALTER TABLE materials DROP CONSTRAINT IF EXISTS fk_materials_current_revision")
    op.execute("DROP TABLE IF EXISTS material_revisions")
    op.execute("DROP TABLE IF EXISTS materials")
    op.execute("DROP TABLE IF EXISTS material_categories")
