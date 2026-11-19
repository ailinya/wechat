"""Exercise additive migration rollback against the restored historical snapshot."""
import os
import json
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from release_support import ROOT, engine, environment, save


def snapshot(db):
    with db.connect() as conn:
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','material_search_vectors','material_chunk_search_vectors') ORDER BY tablename")).scalars().all()
        return {table: dict(conn.execute(text(f'SELECT count(*) AS count,md5(COALESCE(string_agg(md5((to_jsonb(t)-\'search_terms\')::text),\'\' ORDER BY md5((to_jsonb(t)-\'search_terms\')::text)),\'\')) AS checksum FROM "{table}" t')).mappings().one()) for table in tables}


def main():
    backup = json.loads((ROOT/'doc/development/release-evidence/backup-restore.json').read_text(encoding='utf-8'))
    db = engine(backup['restore_database'])
    before = snapshot(db)
    assert before['reviews']['count'] > 0 and before['article_materials']['count'] > 0 and before['wechat_draft_deliveries']['count'] > 0
    os.environ['DATABASE_URL'] = db.url.render_as_string(hide_password=False)
    os.environ['APP_SECRET_KEY'] = environment()['APP_SECRET_KEY']
    cfg = Config('alembic.ini')
    command.downgrade(cfg, '0021_operations')
    assert snapshot(db) == before
    command.upgrade(cfg, 'head')
    assert snapshot(db) == before
    with db.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM material_chunk_search_vectors')).scalar_one()==conn.execute(text('SELECT count(*) FROM material_chunks WHERE embedding IS NOT NULL')).scalar_one()
        assert conn.execute(text("SELECT count(*) FROM material_chunk_search_vectors link JOIN material_chunks c ON c.id=link.chunk_id JOIN material_search_vectors v ON v.id=link.vector_id WHERE v.embedding_model_config_id<>c.embedding_model_config_id OR v.embedding_config_version<>c.embedding_config_version OR v.fingerprint<>encode(sha256(vector_send(c.embedding)),'hex')")).scalar_one()==0
        constraints = [dict(row) for row in conn.execute(text("SELECT t.relname AS table_name,c.conname,c.contype,c.convalidated,pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c JOIN pg_class t ON c.conrelid=t.oid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' ORDER BY t.relname,c.conname")).mappings()]
        assert all(row['convalidated'] for row in constraints)
        head = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    save('migration-history', {'passed':True,'head':head,'checks':['empty_database_all_migrations_deployed','historical_restore_head_to_0021_to_head','all_business_row_counts_and_hashes_preserved','all_constraints_validated'],'tables':before,'constraints':constraints,'rollback_policy':'Only additive 0022 schema rollback demonstrated; earlier business migrations require coordinated snapshot restore'})


if __name__ == '__main__':
    main()
