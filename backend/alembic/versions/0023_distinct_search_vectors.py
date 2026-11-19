"""Index each distinct vector once; retain every original chunk and reference."""
from alembic import op

revision = '0023_distinct_search_vectors'
down_revision = '0022_search_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE material_search_vectors (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 embedding_model_config_id uuid NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
 embedding_config_version integer NOT NULL CHECK (embedding_config_version>0),
 fingerprint varchar(64) NOT NULL CHECK (length(fingerprint)=64),
 embedding vector(1024) NOT NULL,
 UNIQUE(embedding_model_config_id,embedding_config_version,fingerprint)
);
CREATE TABLE material_chunk_search_vectors (
 chunk_id uuid PRIMARY KEY REFERENCES material_chunks(id) ON DELETE CASCADE,
 vector_id uuid NOT NULL REFERENCES material_search_vectors(id) ON DELETE RESTRICT
);
LOCK TABLE material_chunks IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE vector_backfill ON COMMIT DROP AS
 SELECT id AS chunk_id,embedding_model_config_id,embedding_config_version,
 encode(sha256(vector_send(embedding)),'hex') AS fingerprint
 FROM material_chunks WHERE embedding IS NOT NULL;
INSERT INTO material_search_vectors(embedding_model_config_id,embedding_config_version,fingerprint,embedding)
 SELECT r.embedding_model_config_id,r.embedding_config_version,r.fingerprint,c.embedding
 FROM (SELECT embedding_model_config_id,embedding_config_version,fingerprint,min(chunk_id::text)::uuid AS chunk_id
       FROM vector_backfill GROUP BY embedding_model_config_id,embedding_config_version,fingerprint) r
 JOIN material_chunks c ON c.id=r.chunk_id;
INSERT INTO material_chunk_search_vectors(chunk_id,vector_id)
 SELECT b.chunk_id,v.id FROM vector_backfill b JOIN material_search_vectors v
 ON v.embedding_model_config_id=b.embedding_model_config_id
 AND v.embedding_config_version=b.embedding_config_version AND v.fingerprint=b.fingerprint;
CREATE INDEX ix_chunk_search_vector ON material_chunk_search_vectors(vector_id,chunk_id);
CREATE OR REPLACE FUNCTION register_material_search_vector() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE vector_key text; target_id uuid;
BEGIN
 IF NEW.embedding IS NULL THEN
  DELETE FROM material_chunk_search_vectors WHERE chunk_id=NEW.id;
  RETURN NEW;
 END IF;
 vector_key:=encode(sha256(vector_send(NEW.embedding)),'hex');
 INSERT INTO material_search_vectors(embedding_model_config_id,embedding_config_version,fingerprint,embedding)
 VALUES(NEW.embedding_model_config_id,NEW.embedding_config_version,vector_key,NEW.embedding)
 ON CONFLICT DO NOTHING;
 SELECT id INTO target_id FROM material_search_vectors
 WHERE embedding_model_config_id=NEW.embedding_model_config_id
 AND embedding_config_version=NEW.embedding_config_version AND fingerprint=vector_key;
 INSERT INTO material_chunk_search_vectors(chunk_id,vector_id) VALUES(NEW.id,target_id)
 ON CONFLICT(chunk_id) DO UPDATE SET vector_id=excluded.vector_id;
 RETURN NEW;
END $$;
CREATE TRIGGER sync_material_search_vector AFTER INSERT OR UPDATE OF embedding,embedding_model_config_id,embedding_config_version
 ON material_chunks FOR EACH ROW EXECUTE FUNCTION register_material_search_vector();
DROP INDEX IF EXISTS ix_material_chunks_binary_hnsw;
CREATE INDEX ix_material_search_vectors_binary_hnsw ON material_search_vectors USING hnsw
 ((binary_quantize(embedding)::bit(1024)) bit_hamming_ops) WITH(m=16,ef_construction=128);
""")


def downgrade():
    op.execute("""
DROP TRIGGER sync_material_search_vector ON material_chunks;
DROP FUNCTION register_material_search_vector();
DROP TABLE material_chunk_search_vectors;
DROP TABLE material_search_vectors;
CREATE INDEX ix_material_chunks_binary_hnsw ON material_chunks USING hnsw
 ((binary_quantize(embedding)::bit(1024)) bit_hamming_ops) WITH(m=8,ef_construction=32) WHERE embedding IS NOT NULL;
""")
