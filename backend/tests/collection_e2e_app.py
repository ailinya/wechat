"""Opt-in local browser fixture: real API/DB, deterministic external services."""

import os
import json
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import Depends
from app.api.deps import require_permission
from app.schemas.auth import PermissionCode
from app.config import Settings
from app.main import create_app
from app.database import get_engine
from app.adapters import source_fetch, model_client, search_client
from app.modules.async_execution.tasks_core import execute_job
from app.modules.collection import tasks  # register production handlers

if os.environ.get("COLLECTION_E2E_FIXTURE") != "1" or not os.environ.get(
    "DATABASE_URL", ""
).endswith("/wetchat_test"):
    raise RuntimeError(
        "Fixture requires COLLECTION_E2E_FIXTURE=1 and isolated wetchat_test"
    )

settings = Settings.model_validate({})
app = create_app(settings)
engine = get_engine(settings)
source_fetch._default_resolver = lambda *_: ["93.184.216.34"]


def fetch(url, **kwargs):
    date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    html = f'<html><head><title>人工智能行业新闻</title><meta property="article:published_time" content="{date}"></head><body><article><h1>人工智能行业新闻</h1><p>这是一篇人工智能行业新闻，包含产品发布、实际进展和背景信息，供测试素材采集和智能分析。事件标识：{url}</p></article></body></html>'
    return source_fetch.FetchResult(url, 200, html, "text/html", 1)


def model_transport(*args, **kwargs):
    output = {
        "summary": "人工智能行业新闻的测试摘要",
        "relevance": "relevant",
        "relevance_reason": "符合人工智能主题",
        "facts": [],
    }
    request = json.loads(args[3][1]["content"])
    if "previous_revision_id" in request:
        output.update(
            compare_verdict="distinct",
            compare_target_revision_id=request["previous_revision_id"],
        )
    return 200, {
        "choices": [{"message": {"content": json.dumps(output, ensure_ascii=False)}}],
        "usage": {"completion_tokens": 20, "total_tokens": 200},
    }


def search_transport(*args, **kwargs):
    suffix = hashlib.sha256(args[0]["query"].encode()).hexdigest()[:12]
    return 200, {
        "results": [
            {
                "url": f"https://example.com/ai-news-{suffix}",
                "title": "人工智能行业新闻",
                "content": "仅为搜索发现摘要",
                "score": 0.9,
            }
        ]
    }


source_fetch.fetch = fetch
model_client._default_transport = model_transport
search_client._default_transport = search_transport


@app.post(
    "/__test__/drain/{job_id}",
    dependencies=[Depends(require_permission(PermissionCode.COLLECTION_RUN))],
)
def drain(job_id: str):
    return execute_job(job_id, settings)
