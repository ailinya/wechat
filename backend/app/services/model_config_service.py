"""Model configuration management (task 3.16).

Queries never return credentials (only `credential_configured`). Connection
tests and model calls run outside any long write transaction: the service only
persists the config row, the network round-trip happens in the route layer via
the injected client.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.adapters import model_client
from app.errors import ApiError
from app.repositories import model_config_repository as repo


def list_configs(conn: Connection, page: int, page_size: int, purpose: str | None) -> tuple[list[dict], int]:
    return repo.list_configs(conn, page, page_size, purpose)


def create_config(conn: Connection, payload, user_id: UUID | str | None) -> dict:
    if repo.name_exists(conn, payload.name):
        raise ApiError(409, "conflict", "模型配置名称已存在")
    return repo.create_config(
        conn,
        name=payload.name,
        provider=payload.provider,
        purpose=payload.purpose,
        endpoint=payload.endpoint,
        model_name=payload.model_name,
        credential_ref=payload.credential_ref,
        enabled=payload.enabled,
        max_input_tokens=payload.max_input_tokens,
        max_output_tokens=payload.max_output_tokens,
        timeout_seconds=payload.timeout_seconds,
        params=payload.params,
    )


def get_config(conn: Connection, config_id: UUID | str) -> dict:
    config = repo.get_config(conn, config_id)
    if not config:
        raise ApiError(404, "not_found", "模型配置不存在")
    return config


def test_connection(conn: Connection, config_id: UUID | str, client: model_client.ModelClient | None = None) -> dict:
    config = get_config(conn, config_id)
    if not config.get("enabled"):
        raise ApiError(409, "model_disabled", "模型配置已禁用，无法测试")
    client = client or model_client.ModelClient()
    started = time.monotonic()
    try:
        result = client.complete_json(config, "连接测试：只输出 JSON 对象", "请仅输出合法 JSON：{}")
    except model_client.ModelError as exc:
        return {
            "reachable": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": exc.message,
        }
    return {
        "reachable": True,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": None,
    }
