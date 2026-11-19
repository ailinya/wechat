"""Indexed Chinese/Latin lexical candidates and compact ANN retrieval."""
from alembic import op

revision='0022_search_indexes'
down_revision='0021_operations'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""
CREATE OR REPLACE FUNCTION material_search_terms(value text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 WITH words AS (SELECT DISTINCT x[1] AS word FROM regexp_matches(replace(lower(normalize(COALESCE(value,''),NFKC)),'ß','ss'),'[㐀-鿿]+|[a-z0-9]+','g') x),
 tokens AS (
 SELECT word AS token FROM words WHERE word !~ '^[㐀-鿿]'
 UNION ALL
 SELECT substring(word FROM n FOR CASE WHEN length(word)=1 THEN 1 ELSE 2 END)
 FROM words CROSS JOIN LATERAL generate_series(1,greatest(length(word)-1,1)) n WHERE word ~ '^[㐀-鿿]'
 ) SELECT COALESCE(array_agg(DISTINCT token ORDER BY token),ARRAY[]::text[]) FROM tokens
$$;
ALTER TABLE materials ADD COLUMN search_terms text[] GENERATED ALWAYS AS (material_search_terms(title)) STORED;
ALTER TABLE material_revisions ADD COLUMN search_terms text[] GENERATED ALWAYS AS (material_search_terms(content_markdown)) STORED;
CREATE INDEX ix_material_title_terms ON materials USING gin(search_terms) WHERE deleted_at IS NULL;
CREATE INDEX ix_material_body_terms ON material_revisions USING gin(search_terms);
CREATE INDEX ix_collection_result_material_source ON collection_results(material_id,collected_at,id) WHERE material_id IS NOT NULL;
CREATE INDEX ix_material_current_active ON materials(current_revision_id) WHERE deleted_at IS NULL AND usage_status<>'archived';
CREATE INDEX ix_material_list_active ON materials(created_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_material_list_status ON materials(usage_status,created_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_outbox_dispatched_job ON outbox_events((payload->'kwargs'->>'job_id')) WHERE status='dispatched';
CREATE INDEX ix_material_chunks_binary_hnsw ON material_chunks USING hnsw ((binary_quantize(embedding)::bit(1024)) bit_hamming_ops) WITH(m=8,ef_construction=32) WHERE embedding IS NOT NULL;
    """)


def downgrade():
    for index in ['ix_outbox_dispatched_job','ix_material_list_active','ix_material_list_status','ix_material_chunks_binary_hnsw','ix_material_current_active','ix_collection_result_material_source','ix_material_body_terms','ix_material_title_terms']:
        op.execute(f'DROP INDEX IF EXISTS {index}')
    op.execute('ALTER TABLE material_revisions DROP COLUMN search_terms')
    op.execute('ALTER TABLE materials DROP COLUMN search_terms')
    op.execute('DROP FUNCTION material_search_terms(text)')
