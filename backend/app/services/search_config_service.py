"""Search configuration changes and safe, transaction-free connection probes."""
from __future__ import annotations

import time

from sqlalchemy.exc import IntegrityError

from app.adapters.search_client import SearchClient, SearchError
from app.errors import ApiError
from app.repositories import search_config_repository as repo


def get_config(conn, config_id):
    config = repo.get_config(conn, config_id)
    if config is None:
        raise ApiError(404, "not_found", "搜索配置不存在")
    return config


def save_config(conn, payload, config_id=None):
    try:
        with conn.begin_nested():
            if config_id is None:
                return repo.create_config(conn, **payload.model_dump())
            get_config(conn, config_id)
            return repo.update_config(conn, config_id, payload.model_dump(exclude_unset=True))
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise ApiError(409, "conflict", "搜索配置名称已存在") from None
        raise


def probe(config, client=None):
    started = time.monotonic()
    try:
        (client or SearchClient(max_attempts=1)).search(config, "科技新闻", max_results=1, remaining_calls=1)
    except SearchError as exc:
        return {"reachable": False, "error": exc.message, "error_code": exc.code,
                "latency_ms": int((time.monotonic() - started) * 1000)}
    return {"reachable": True, "error": None, "error_code": None,
            "latency_ms": int((time.monotonic() - started) * 1000)}
