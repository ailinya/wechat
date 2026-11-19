"""30 concurrent users for five minutes against the annual-scale isolated corpus."""
import argparse
import asyncio
import json
import math
import platform
import random
import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import text
from release_support import api, client, engine, environment, save, wait_job


def percentiles(values):
    ordered = sorted(values)
    return {name:round(ordered[min(len(ordered)-1,max(0,math.ceil(len(ordered)*fraction)-1))],2) if ordered else None for name,fraction in [('p50',.5),('p95',.95),('p99',.99)]}


async def measure(cookies, csrf, duration):
    deadline = time.monotonic()+duration
    samples = {kind:[] for kind in ['materials_list','keyword_selective','keyword_common','semantic_search']}
    wall_samples = {kind:[] for kind in samples}
    statuses = Counter()
    errors = []
    async with httpx.AsyncClient(base_url='http://127.0.0.1:58020',cookies=cookies,headers={'X-CSRF-Token':csrf},timeout=120,trust_env=False,limits=httpx.Limits(max_connections=30,max_keepalive_connections=30)) as c:
        async def user(index):
            rng = random.Random(index)
            iteration = 0
            while time.monotonic()<deadline:
                slot = iteration%10
                kind = 'materials_list' if slot<7 else 'keyword_selective' if slot==7 else 'keyword_common' if slot==8 else 'semantic_search'
                start = time.monotonic()
                try:
                    if kind == 'materials_list':
                        response = await c.get('/api/v1/materials',params={'page':rng.randint(1,20),'page_size':20})
                    else:
                        query = 'sample'+str(rng.randint(1,500000)) if kind=='keyword_selective' else '电池回收' if kind=='keyword_common' else 'palette_'+str(rng.randint(0,9999))
                        response = await c.post('/api/v1/materials/search',json={'query':query,'scope':'all','top_k':10,'keyword_mode':'hybrid' if kind=='semantic_search' else 'keyword_only'})
                    statuses[str(response.status_code)] += 1
                    if response.status_code != 200:
                        errors.append({'kind':kind,'status':response.status_code})
                    else:
                        timing = re.search(r'dur=([0-9.]+)',response.headers.get('server-timing',''))
                        assert timing, 'Missing server-side timing'
                        samples[kind].append(float(timing.group(1)))
                        wall_samples[kind].append((time.monotonic()-start)*1000)
                        payload = response.json()
                        if kind!='materials_list' and not payload['items']:
                            errors.append({'kind':kind,'error':'empty_result'})
                except Exception as exc:
                    statuses['transport_error'] += 1
                    errors.append({'kind':kind,'error':type(exc).__name__})
                iteration += 1
        await asyncio.gather(*(user(index) for index in range(30)))
    return samples, wall_samples, statuses, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',action='store_true')
    args = parser.parse_args()
    values = environment()
    db = engine('wetchat_acceptance_perf')
    with db.connect() as conn:
        counts = dict(conn.execute(text('SELECT (SELECT count(*) FROM materials) AS materials,(SELECT count(*) FROM material_chunks) AS chunks,(SELECT count(*) FROM material_chunks WHERE embedding IS NOT NULL) AS vectors')).mappings().one())
        index_counts = dict(conn.execute(text('SELECT (SELECT count(*) FROM material_chunk_search_vectors) AS mapped_chunks,(SELECT count(*) FROM material_search_vectors) AS distinct_vectors')).mappings().one())
        version = conn.execute(text('SELECT version()')).scalar_one()
        pg_settings = {name:conn.execute(text('SELECT current_setting(:name)'), {'name':name}).scalar_one() for name in ('shared_buffers','max_wal_size','work_mem','checkpoint_timeout','max_parallel_workers_per_gather')}
        body_size = float(conn.execute(text('SELECT avg(length(content_markdown)) FROM (SELECT content_markdown FROM material_revisions LIMIT 1000) sample')).scalar_one() or 0)
        indexes = conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname IN ('ix_material_list_active','ix_material_search_vectors_binary_hnsw')")).scalars().all()
    if not args.probe:
        assert counts == {'materials':500000,'chunks':2500000,'vectors':2500000}, 'Full annual-scale corpus required'
        assert index_counts['mapped_chunks'] == counts['vectors'], 'Every embedded chunk must have an index mapping'
        assert len(indexes) == 2, 'Search and list indexes must be complete'
        with db.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.execute(text('VACUUM (ANALYZE) materials'))
    c = httpx.Client(base_url='http://127.0.0.1:58020',trust_env=False,timeout=120)
    assert c.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']}).status_code == 200
    c.headers['X-CSRF-Token'] = c.cookies['wetchat_csrf']
    if args.probe:
        for path,body in [('/materials',None),('/materials/search',{'query':'sample5000','keyword_mode':'keyword_only','scope':'all','top_k':10}),('/materials/search',{'query':'电池回收','keyword_mode':'keyword_only','scope':'all','top_k':10})]:
            response = c.request('POST' if body else 'GET','/api/v1'+path,json=body)
            print(json.dumps({'probe':path,'status':response.status_code,'server_timing':response.headers.get('server-timing'),'counts':counts}),flush=True)
        return
    # Warm caches before the controlled run, after seeding/index construction finish.
    assert c.get('/api/v1/materials').status_code == 200
    assert c.post('/api/v1/materials/search',json={'query':'palette_123','scope':'all','top_k':10}).status_code == 200
    started = time.monotonic()
    samples,wall,statuses,errors = asyncio.run(measure(dict(c.cookies),c.cookies['wetchat_csrf'],300))
    elapsed = time.monotonic()-started
    docker_info = subprocess.check_output(['docker','info','--format','{{.NCPU}} {{.MemTotal}}'],text=True).split()
    metrics = {kind:{'requests':len(times),'server_ms':percentiles(times),'client_ms':percentiles(wall[kind])} for kind,times in samples.items()}
    total = sum(statuses.values())
    result = {'passed':bool(samples['materials_list']) and metrics['materials_list']['server_ms']['p95']<=500 and len(errors)/max(total,1)<.001,'environment':{'host':platform.platform(),'docker_cpus':8,'docker_memory_gib':8,'postgres':version,'api_workers':2,'data_location':values['ACCEPTANCE_DATA_ROOT'],'external_embedding':'deterministic fixture; model network time excluded'},'concurrent_users':30,'duration_seconds':round(elapsed,2),'counts':counts,'average_body_characters_sample_1000':body_size,'mix':'70% paginated list, 10% selective keyword, 10% common Chinese keyword, 10% semantic','metrics':metrics,'rps':round(total/elapsed,2),'statuses':dict(statuses),'error_rate':len(errors)/max(total,1),'errors':errors[:20],'search_slo':'No annual-scale search latency SLO was fixed in phase 4; measured separately from list target','raw_server_samples_ms':samples}
    result['environment']['docker_cpus'] = int(docker_info[0])
    result['environment']['docker_memory_gib'] = round(int(docker_info[1])/(1024**3),3)
    result['environment']['transport'] = 'direct API port 58020; server timings exclude client network'
    result['environment']['postgres_settings'] = pg_settings
    result['search_index_counts'] = index_counts
    result['synthetic_vector_limitation'] = 'The 1024-dimensional vectors use a 10000-vector synthetic palette; this does not represent 2500000 distinct vectors or real semantic quality.'
    save('performance',result)
    # Independent 20-job burst uses the main acceptance Worker/broker, no model calls.
    main_client = client()
    def submit(index):
        start = time.monotonic()
        row = api(main_client,'/__acceptance__/health-job','POST')
        wait_job(main_client,row['async_job_id'])
        return (time.monotonic()-start)*1000
    with ThreadPoolExecutor(max_workers=20) as pool:
        latencies = list(pool.map(submit,range(20)))
    save('queue-performance',{'passed':True,'jobs':20,'worker_concurrency':2,'acceptance_to_observed_completion_ms':percentiles(latencies),'raw_ms':latencies,'poll_interval_ms':400})


if __name__ == '__main__':
    main()
