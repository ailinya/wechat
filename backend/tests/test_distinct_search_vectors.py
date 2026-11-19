"""Duplicate vectors preserve recall, immutable chunks and configuration isolation."""
from sqlalchemy import text
from app.schemas.materials import MaterialSearchIn
from app.services import material_embedding_service, material_search_service


VECTOR = '['+','.join(['1']+['0']*1023)+']'


def material(conn,config,index,version=1,chunks=2):
    mid=conn.execute(text("INSERT INTO materials(title,usage_status) VALUES (:title,'ready_to_use') RETURNING id"),{'title':f'Shared vector {index}'}).scalar_one()
    rid=conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'合成正文') RETURNING id"),{'id':mid}).scalar_one()
    conn.execute(text('UPDATE materials SET current_revision_id=:rid WHERE id=:id'),{'rid':rid,'id':mid})
    conn.execute(text("INSERT INTO material_embedding_runs(material_revision_id,embedding_model_config_id,embedding_config_version,status) VALUES (:rid,:config,:version,'succeeded')"),{'rid':rid,'config':config['id'],'version':version})
    for slot in range(chunks):
        conn.execute(text('INSERT INTO material_chunks(material_revision_id,chunk_index,content,content_hash,embedding_model_config_id,embedding_config_version,embedding_model_name,embedding) VALUES (:rid,:slot,\'共享向量正文\',:hash,:config,:version,:model,CAST(:vector AS vector))'),{'rid':rid,'slot':slot,'hash':'a'*64,'config':config['id'],'version':version,'model':config['model_name'],'vector':VECTOR})
    return mid,rid


def results(conn):
    return material_search_service.search(conn,MaterialSearchIn(query='unrelated',scope='all',top_k=10),embed=lambda *_args,**_kwargs:([[1.]+[0.]*1023],{}))['items']


def test_duplicates_recall_all_materials_after_original_chunk_deleted(db_engine):
    with db_engine.begin() as conn:
        config=material_embedding_service.ensure_environment_embedding_config(conn)
        pairs=[material(conn,config,index) for index in range(3)]
        assert conn.execute(text('SELECT count(*) FROM material_search_vectors')).scalar_one()==1
        assert conn.execute(text('SELECT count(*) FROM material_chunks WHERE embedding IS NOT NULL')).scalar_one()==6
        assert {item['material_id'] for item in results(conn)}=={mid for mid,_ in pairs}
        conn.execute(text('DELETE FROM material_chunks WHERE material_revision_id=:rid'),{'rid':pairs[0][1]})
        assert {item['material_id'] for item in results(conn)}=={mid for mid,_ in pairs[1:]}
        assert all(item['semantic_score']==1 for item in results(conn))
        conn.execute(text('UPDATE material_chunks SET embedding=NULL'))
        assert not results(conn)
        assert conn.execute(text('SELECT count(*) FROM material_chunk_search_vectors')).scalar_one()==0


def test_model_version_isolation_and_embedding_update_remaps_atomically(db_engine):
    with db_engine.begin() as conn:
        config=material_embedding_service.ensure_environment_embedding_config(conn)
        first=material(conn,config,1,version=1,chunks=1)
        second=material(conn,config,2,version=2,chunks=1)
        assert conn.execute(text('SELECT count(*) FROM material_search_vectors')).scalar_one()==2
        assert {item['material_id'] for item in results(conn)}=={first[0]}
        conn.execute(text("INSERT INTO material_embedding_runs(material_revision_id,embedding_model_config_id,embedding_config_version,status) VALUES (:rid,:config,1,'succeeded')"),{'rid':second[1],'config':config['id']})
        conn.execute(text('UPDATE material_chunks SET embedding_config_version=1 WHERE material_revision_id=:rid'),{'rid':second[1]})
        assert {item['material_id'] for item in results(conn)}=={first[0],second[0]}
        assert conn.execute(text('SELECT count(DISTINCT vector_id) FROM material_chunk_search_vectors')).scalar_one()==1
