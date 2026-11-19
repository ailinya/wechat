"""Maintain the exact active material count in the writing transaction."""
from alembic import op

revision = '0024_material_counts'
down_revision = '0023_distinct_search_vectors'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
LOCK TABLE materials IN SHARE ROW EXCLUSIVE MODE;
CREATE TABLE material_counts (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    active_count bigint NOT NULL CHECK (active_count >= 0)
);
INSERT INTO material_counts(singleton, active_count)
SELECT true, count(*) FROM materials WHERE deleted_at IS NULL;

CREATE OR REPLACE FUNCTION update_material_count() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE delta bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT count(*) INTO delta FROM new_materials WHERE deleted_at IS NULL;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT -count(*) INTO delta FROM old_materials WHERE deleted_at IS NULL;
    ELSIF TG_OP = 'UPDATE' THEN
        SELECT (SELECT count(*) FROM new_materials WHERE deleted_at IS NULL)
             - (SELECT count(*) FROM old_materials WHERE deleted_at IS NULL) INTO delta;
    ELSE
        UPDATE material_counts SET active_count = 0 WHERE singleton;
        RETURN NULL;
    END IF;
    IF delta <> 0 THEN
        UPDATE material_counts SET active_count = active_count + delta WHERE singleton;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER material_count_insert AFTER INSERT ON materials
    REFERENCING NEW TABLE AS new_materials FOR EACH STATEMENT EXECUTE FUNCTION update_material_count();
CREATE TRIGGER material_count_delete AFTER DELETE ON materials
    REFERENCING OLD TABLE AS old_materials FOR EACH STATEMENT EXECUTE FUNCTION update_material_count();
CREATE TRIGGER material_count_update AFTER UPDATE ON materials
    REFERENCING OLD TABLE AS old_materials NEW TABLE AS new_materials FOR EACH STATEMENT EXECUTE FUNCTION update_material_count();
CREATE TRIGGER material_count_truncate AFTER TRUNCATE ON materials
    FOR EACH STATEMENT EXECUTE FUNCTION update_material_count();
""")


def downgrade():
    op.execute("""
DROP TRIGGER material_count_insert ON materials;
DROP TRIGGER material_count_delete ON materials;
DROP TRIGGER material_count_update ON materials;
DROP TRIGGER material_count_truncate ON materials;
DROP FUNCTION update_material_count();
DROP TABLE material_counts;
""")
