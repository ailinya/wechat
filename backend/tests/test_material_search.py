from datetime import datetime, timezone

from sqlalchemy import text

from app.adapters.embedding_client import EmbeddingError
from app.schemas.materials import MaterialSearchIn
from app.services import material_embedding_service, material_search_service


def test_chinese_search_filters_degradation_and_revision_isolation(db_engine):
    samples = [
        ("传感器新品发布", "星河公司发布新型传感器，采样率每秒 200 次。", "ready_to_use"),
        ("新能源汽车电池回收", "动力电池回收产线采用梯次利用和材料再生工艺。", "used"),
        ("城市气象服务升级", "提高强降雨预警和城市内涝监测能力。", "archived"),
    ]
    with db_engine.begin() as conn:
        config = material_embedding_service.ensure_environment_embedding_config(conn)
        revisions = []
        for title, body, status in samples:
            material = conn.execute(text("INSERT INTO materials(title,usage_status) VALUES (:title,:status) RETURNING id"), {"title": title, "status": status}).scalar_one()
            revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,:body) RETURNING id"), {"id": material, "body": body}).scalar_one()
            conn.execute(text("UPDATE materials SET current_revision_id=:rev WHERE id=:id"), {"id": material, "rev": revision})
            revisions.append((material, revision))

        def fail(*args, **kwargs):
            raise EmbeddingError("embedding_unreachable", "unavailable")

        result = material_search_service.search(conn, MaterialSearchIn(query="传感器采样率", keyword_mode="hybrid"), embed=fail)
        assert result["degraded"] and result["degradation_reason"] == "embedding_unreachable"
        assert result["items"][0]["matched_revision_id"] == revisions[0][1]
        assert result["items"][0]["semantic_score"] is None
        assert not material_search_service.search(conn, MaterialSearchIn(query="动力电池回收", keyword_mode="keyword_only"))["items"]
        assert material_search_service.search(conn, MaterialSearchIn(query="动力电池回收", scope="all", keyword_mode="keyword_only"))["items"][0]["material_id"] == revisions[1][0]
        assert not material_search_service.search(conn, MaterialSearchIn(query="内涝预警", scope="all", keyword_mode="keyword_only"))["items"]
        assert not material_search_service.search(conn, MaterialSearchIn(query="传感器", keyword_mode="keyword_only", **{"from": datetime(2026, 1, 1, tzinfo=timezone.utc)}))["items"]
        assert not material_search_service.search(conn, MaterialSearchIn(query="古典诗词格律", min_relevance=.75, keyword_mode="keyword_only"))["items"]

        material, old_revision = revisions[0]
        revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,2,'新的正文完全不同') RETURNING id"), {"id": material}).scalar_one()
        conn.execute(text("UPDATE materials SET current_revision_id=:rev WHERE id=:id"), {"id": material, "rev": revision})
        assert not material_search_service.search(conn, MaterialSearchIn(query="采样率", keyword_mode="keyword_only"))["items"]
        assert config["id"] and old_revision != revision


def test_exact_semantic_search_uses_succeeded_current_chunks(db_engine):
    with db_engine.begin() as conn:
        config = material_embedding_service.ensure_environment_embedding_config(conn)
        material = conn.execute(text("INSERT INTO materials(title,usage_status) VALUES ('电池回收','ready_to_use') RETURNING id")).scalar_one()
        revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'电池回收利用') RETURNING id"), {"id": material}).scalar_one()
        conn.execute(text("UPDATE materials SET current_revision_id=:revision WHERE id=:id"), {"id": material, "revision": revision})
        vec = "[1," + ",".join(["0"] * 1023) + "]"
        conn.execute(text("INSERT INTO material_chunks(material_revision_id,chunk_index,content,content_hash,embedding_model_config_id,embedding_config_version,embedding_model_name,embedding) VALUES (:revision,0,'电池回收利用',:hash,:config,:version,:model,CAST(:vec AS vector))"), {"revision": revision, "hash": "a" * 64, "config": config["id"], "version": config["config_version"], "model": config["model_name"], "vec": vec})
        conn.execute(text("INSERT INTO material_embedding_runs(material_revision_id,embedding_model_config_id,embedding_config_version,status) VALUES (:revision,:config,:version,'succeeded')"), {"revision": revision, "config": config["id"], "version": config["config_version"]})
        def embedding(_texts, **_kwargs):
            return [[1.] + [0.] * 1023], {}
        result = material_search_service.search(conn, MaterialSearchIn(query="循环再生", scope="all"), embed=embedding)
        assert result["mode"] == "hybrid" and not result["degraded"]
        assert result["items"][0]["matched_revision_id"] == revision
        assert result["items"][0]["semantic_score"] == 1.0


def test_search_http_contract_and_current_revision(client):
    assert client.post("/api/v1/materials/search", json={"query": "传感器"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"account": "admin", "password": "correct-password"}).status_code == 200
    headers = {"X-CSRF-Token": client.cookies.get("wetchat_csrf")}
    created = client.post("/api/v1/materials", headers=headers, json={"title": "传感器", "content_markdown": "采样率每秒200次"})
    assert created.status_code == 201
    material = created.json()
    response = client.post("/api/v1/materials/search", headers=headers, json={"query": "采样率", "keyword_mode": "keyword_only"})
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["material_id"] == material["id"]
    assert item["matched_revision_id"] == material["current_revision_id"]
    assert item["source"]["type"] == "manual"


def test_saturated_keyword_candidates_keep_sorted_eligible_results(db_engine):
    with db_engine.begin() as conn:
        expected = []
        for index in range(125):
            status = 'archived' if index < 15 else 'ready_to_use'
            material = conn.execute(text("INSERT INTO materials(title,usage_status) VALUES ('同主题',:status) RETURNING id"), {'status':status}).scalar_one()
            revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:id,1,'同主题') RETURNING id"), {'id':material}).scalar_one()
            conn.execute(text('UPDATE materials SET current_revision_id=:revision WHERE id=:id'), {'id':material,'revision':revision})
            if status != 'archived':
                expected.append(material)
        result = material_search_service.search(conn, MaterialSearchIn(query='同主题', scope='all', keyword_mode='keyword_only', top_k=10))
        assert [item['material_id'] for item in result['items']] == sorted(expected, key=str)[:10]


def test_query_term_patterns_match_tokenizer_boundaries():
    from app.services.material_search_service import _term_patterns, terms
    import unicodedata

    cases = [
        ("中文文词 x A123", "中文文词 x a1234"),
        ("电池回收 A-ß 中", "电池回收 a ss 中中"),
        ("ABC １２３ 中", "abc 123 中!"),
        ("中文 文词", "中文词"),
    ]
    for query, document in cases:
        query_terms = terms(query)
        normalized = unicodedata.normalize('NFKC', document).casefold()
        actual = {term for term, pattern in _term_patterns(query_terms).items() if pattern.search(normalized)}
        assert actual == query_terms & terms(document)
