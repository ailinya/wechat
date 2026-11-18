"""Evaluate the fixed Chinese corpus on an explicitly isolated local test database."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.credentials import resolve_setting
from app.schemas.materials import MaterialSearchIn
from app.services import async_job_service, material_embedding_service, material_search_service

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = [
    ("传感器新品发布", "星河公司发布新型传感器，采样率每秒 200 次，比上一代提高 25%，计划于 12 月开始交付。"),
    ("新能源汽车电池回收", "某企业建设动力电池回收产线，采用梯次利用和材料再生工艺。"),
    ("城市气象服务升级", "气象部门升级短临预报系统，提高强降雨预警和城市内涝监测能力。"),
]
QUERIES = [("传感器采样率提升", SAMPLES[0][0]), ("动力电池循环利用", SAMPLES[1][0]),
           ("暴雨预警和内涝", SAMPLES[2][0]), ("古典诗词格律", None)]


def main() -> None:
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if (url.host, url.port, url.database) != ("127.0.0.1", 55432, "wechat_test"):
        raise RuntimeError("Evaluation requires the isolated local wechat_test database on port 55432")
    sys.path.insert(0, str(ROOT / "backend" / "tests"))
    from conftest import reset_schema

    reset_schema()
    engine = create_engine(url)
    jobs = []
    with engine.begin() as conn:
        for title, content in SAMPLES:
            material = conn.execute(text("INSERT INTO materials(title,usage_status) VALUES (:title,'ready_to_use') RETURNING id"), {"title": title}).scalar_one()
            revision = conn.execute(text("INSERT INTO material_revisions(material_id,revision_no,content_markdown) VALUES (:material,1,:content) RETURNING id"), {"material": material, "content": content}).scalar_one()
            conn.execute(text("UPDATE materials SET current_revision_id=:revision WHERE id=:material"), {"revision": revision, "material": material})
            accepted = material_embedding_service.enqueue_rebuild(conn, material)
            async_job_service.claim_job(conn, accepted["async_job_id"])
            jobs.append(async_job_service.get_job(conn, accepted["async_job_id"]))
    for job in jobs:
        material_embedding_service.material_embedding_job(engine, job)
        with engine.begin() as conn:
            async_job_service.finish_job(conn, job["id"], "succeeded")
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(), "dataset": "synthetic Chinese fixtures", "material_count": len(SAMPLES),
                "embedding_model": resolve_setting("EMBEDDING_MODEL"), "dimension": 1024, "queries": []}
    with engine.connect() as conn:
        for query, expected in QUERIES:
            started = perf_counter()
            result = material_search_service.search(conn, MaterialSearchIn(query=query, scope="all", min_relevance=.75 if expected is None else 0))
            evidence["queries"].append({"query": query, "expected_first_title": expected, "mode": result["mode"],
                "degraded": result["degraded"], "latency_ms": round((perf_counter() - started) * 1000),
                "results": [{"title": item["title"], "revision_id": str(item["matched_revision_id"]),
                             "relevance": round(item["relevance_score"], 4)} for item in result["items"]]})
    engine.dispose()
    path = ROOT / "doc" / "development" / "material-search-live-evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if any(row["degraded"] or (row["results"][0]["title"] if row["results"] else None) != row["expected_first_title"] for row in evidence["queries"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
