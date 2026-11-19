"""Tie-aware ANN checks on the deterministic annual-scale vector palette."""
import httpx
from sqlalchemy import text
from release_support import engine, environment, save


def main():
    values = environment()
    with engine('wetchat_acceptance_perf').connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM material_chunks')).scalar_one() == 2500000
        assert conn.execute(text("SELECT count(*) FROM pg_indexes WHERE indexname='ix_material_search_vectors_binary_hnsw'")).scalar_one() == 1
    with httpx.Client(base_url='http://127.0.0.1:58020',timeout=120,trust_env=False) as c:
        assert c.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']}).status_code == 200
        headers = {'X-CSRF-Token':c.cookies['wetchat_csrf']}
        rows = []
        for palette in [0,1,7,42,123,999,2048,5000,7777,9999]:
            response = c.post('/api/v1/materials/search',headers=headers,json={'query':'palette_'+str(palette),'scope':'all','top_k':10,'keyword_mode':'hybrid'})
            assert response.status_code == 200
            result = response.json()
            scores = [item['semantic_score'] for item in result['items']]
            passed = result['mode']=='hybrid' and not result['degraded'] and len(scores)==10 and min(scores)>=.99999
            rows.append({'palette':palette,'returned':len(scores),'min_score':min(scores) if scores else None,'passed':passed})
        save('search-quality',{'passed':all(row['passed'] for row in rows),'checks':rows,'oracle':'Each query equals a known palette vector, repeated across 250 chunks; exact optimal cosine=1. All top-k ties are acceptable.','limitation':'Synthetic self-vector retrieval proves index/configuration plumbing; it is not a natural language relevance benchmark or general ANN recall estimate.','corpus_chunks':2500000,'distinct_vectors':10000,'embedding_dimension':1024})
        assert all(row['passed'] for row in rows)


if __name__ == '__main__':
    main()
