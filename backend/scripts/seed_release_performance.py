"""Annual-scale synthetic corpus in a separate acceptance database only."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
import time
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.engine import URL
from alembic import command
from alembic.config import Config
from release_support import engine,environment,save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--materials',type=int,default=500000)
    parser.add_argument('--workers',type=int,default=3,choices=range(1,5))
    args=parser.parse_args()
    assert 1<=args.materials<=500000
    values=environment()
    from sqlalchemy import create_engine
    base=create_engine(URL.create('postgresql+psycopg',username='wetchat',password=values['POSTGRES_PASSWORD'],host='127.0.0.1',port=int(values['POSTGRES_PORT']),database='postgres'),isolation_level='AUTOCOMMIT')
    with base.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname='wetchat_acceptance_perf'")).scalar():
            conn.execute(text('CREATE DATABASE wetchat_acceptance_perf'))
    perf=engine('wetchat_acceptance_perf')
    os.environ['DATABASE_URL']=perf.url.render_as_string(hide_password=False)
    os.environ['APP_SECRET_KEY']=values['APP_SECRET_KEY']
    os.environ['EMBEDDING_MODEL']=values['EMBEDDING_MODEL']
    os.environ['EMBEDDING_BASE_URL']=values['EMBEDDING_BASE_URL']
    os.environ['EMBEDDING_DIMENSION']='1024'
    command.upgrade(Config('alembic.ini'),'head')
    from app.services.material_embedding_service import ensure_environment_embedding_config
    from app.commands.create_admin import create_admin
    with perf.begin() as conn:
        config=ensure_environment_embedding_config(conn)
        exists=conn.execute(text("SELECT 1 FROM users WHERE account='admin'")).scalar()
        conn.execute(text('CREATE TABLE IF NOT EXISTS acceptance_vector_palette(id integer PRIMARY KEY,embedding vector(1024) NOT NULL)'))
        if not conn.execute(text('SELECT 1 FROM acceptance_vector_palette LIMIT 1')).scalar():
            conn.execute(text("INSERT INTO acceptance_vector_palette SELECT i,ARRAY(SELECT (get_byte(decode(md5(i::text||':'||d::text),'hex'),0)/127.5-1)::real FROM generate_series(1,1024) d)::vector FROM generate_series(0,9999) i"))
    if not exists:
        create_admin('admin','验收管理员',values['WETCHAT_ADMIN_PASSWORD'])
    started=time.monotonic()
    seeded_batches=[]
    def seed_batch_once(first):
        last=min(first+4999,args.materials)
        with perf.connect() as check:
            complete=check.execute(text("SELECT count(*) FROM material_chunks WHERE material_revision_id=CAST(md5('perf-revision-'||CAST(:last AS text)) AS uuid)"),{'last':last}).scalar_one()==5
        if complete:
            return
        with perf.begin() as conn:
            params={'first':first,'last':last,'config':config['id'],'version':config['config_version'],'model':config['model_name']}
            conn.execute(text("INSERT INTO materials(id,title,origin,usage_status,current_revision_id) SELECT md5('perf-material-'||n)::uuid,'[perf] 样例 sample'||n,'manual','ready_to_use',md5('perf-revision-'||n)::uuid FROM generate_series(CAST(:first AS integer),CAST(:last AS integer)) n ON CONFLICT DO NOTHING"),params)
            conn.execute(text("INSERT INTO material_revisions(id,material_id,revision_no,content_markdown) SELECT md5('perf-revision-'||n)::uuid,md5('perf-material-'||n)::uuid,1,'样例 sample'||n||'。'||repeat('产业观察：电池回收与传感器试点，记录工艺、产量和时间。这是用于性能测试的合成资料，不作为正式事实。',60) FROM generate_series(CAST(:first AS integer),CAST(:last AS integer)) n ON CONFLICT DO NOTHING"),params)
            conn.execute(text("INSERT INTO material_embedding_runs(material_revision_id,embedding_model_config_id,embedding_config_version,status) SELECT md5('perf-revision-'||n)::uuid,:config,:version,'succeeded' FROM generate_series(CAST(:first AS integer),CAST(:last AS integer)) n ON CONFLICT DO NOTHING"),params)
            conn.execute(text("INSERT INTO material_chunks(material_revision_id,chunk_index,content,content_hash,embedding,embedding_model_config_id,embedding_config_version,embedding_model_name) SELECT md5('perf-revision-'||n)::uuid,c,'[perf] sample'||n||' chunk'||c,md5(n::text||':'||c)||md5('seed'||n||':'||c),p.embedding,:config,:version,:model FROM generate_series(CAST(:first AS integer),CAST(:last AS integer)) n CROSS JOIN generate_series(0,4) c JOIN acceptance_vector_palette p ON p.id=mod(n*5+c,10000) ON CONFLICT DO NOTHING"),params)
        seeded_batches.append(last)
        print(json.dumps({'seeded_materials':last,'target':args.materials,'elapsed_seconds':round(time.monotonic()-started,1)}),flush=True)
    def seed_batch(first):
        # Different batches can introduce the same new vector fingerprints in
        # different orders. Retry the entire rolled-back transaction on deadlock.
        for attempt in range(6):
            try:
                return seed_batch_once(first)
            except OperationalError as exc:
                if getattr(exc.orig, 'sqlstate', None) != '40P01' or attempt == 5:
                    raise
                print(json.dumps({'deadlock_retry_batch':first,'attempt':attempt+1}),flush=True)
                time.sleep((attempt + 1) * .5)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(seed_batch,range(1,args.materials+1,5000)))
    print('verifying distinct-vector search index',flush=True)
    with perf.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.execute(text('ANALYZE' if seeded_batches else 'ANALYZE material_search_vectors, material_chunk_search_vectors'))
        counts=conn.execute(text('SELECT (SELECT count(*) FROM materials) AS materials,(SELECT count(*) FROM material_chunks) AS chunks,(SELECT count(*) FROM material_chunks WHERE embedding IS NOT NULL) AS vectors,(SELECT count(*) FROM material_chunk_search_vectors) AS mappings,(SELECT count(*) FROM material_search_vectors) AS distinct_vectors')).mappings().one()
        sizes=[dict(r) for r in conn.execute(text("SELECT relname,n_live_tup,pg_total_relation_size(relid) AS bytes FROM pg_stat_user_tables ORDER BY relname")).mappings()]
    save('performance-seed',{'passed':counts['materials']==args.materials and counts['chunks']==args.materials*5 and counts['vectors']==args.materials*5 and counts['mappings']==args.materials*5,'material_count':counts['materials'],'chunk_count':counts['chunks'],'vector_count':counts['vectors'],'mapped_chunk_count':counts['mappings'],'indexed_distinct_vector_count':counts['distinct_vectors'],'schema_head':'0023_distinct_search_vectors','duration_seconds':round(time.monotonic()-started,2),'duration_scope':'final resumable invocation; earlier seeding attempts excluded','vector_palette_size':10000,'embedding_dimension':1024,'synthetic':True,'tables':sizes})


if __name__=='__main__':
    main()
