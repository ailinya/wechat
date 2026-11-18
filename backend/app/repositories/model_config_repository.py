"""Model configuration persistence (task 3.16)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def list_configs(
    conn: Connection, page: int, page_size: int, purpose: str | None = None
) -> tuple[list[dict], int]:
    where, params = ["TRUE"], {}
    if purpose:
        where.append("purpose = :purpose")
        params["purpose"] = purpose
    clause = " AND ".join(where)
    total = conn.execute(
        text(f"SELECT count(*) FROM model_configs WHERE {clause}"), params
    ).scalar_one()
    rows = conn.execute(
        text(
            f"SELECT * FROM model_configs WHERE {clause} "
            "ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def get_config(conn: Connection, config_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM model_configs WHERE id = :id"), {"id": str(config_id)}
    ).mappings().first()
    return dict(row) if row else None


def name_exists(conn: Connection, name: str, exclude_id: UUID | str | None = None) -> bool:
    params: dict[str, Any] = {"name": name}
    clause = "name = :name"
    if exclude_id is not None:
        clause += " AND id <> :exclude"
        params["exclude"] = str(exclude_id)
    return (
        conn.execute(text(f"SELECT 1 FROM model_configs WHERE {clause} LIMIT 1"), params).first()
        is not None
    )


def create_config(conn: Connection, *, name: str, provider: str, purpose: str,
                  endpoint: str, model_name: str, credential_ref: str | None,
                  enabled: bool, max_input_tokens: int, max_output_tokens: int,
                  timeout_seconds: int, params: dict) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO model_configs "
            "(name, provider, purpose, endpoint, model_name, credential_ref, enabled, "
            " max_input_tokens, max_output_tokens, timeout_seconds, params) "
            "VALUES (:name, :provider, :purpose, :endpoint, :model, :cred, :enabled, "
            " :in_tokens, :out_tokens, :timeout, CAST(:params AS jsonb)) RETURNING *"
        ),
        {
            "name": name, "provider": provider, "purpose": purpose,
            "endpoint": endpoint, "model": model_name, "cred": credential_ref,
            "enabled": enabled, "in_tokens": max_input_tokens,
            "out_tokens": max_output_tokens, "timeout": timeout_seconds,
            "params": json.dumps(params or {}, ensure_ascii=False),
        },
    ).mappings().one()
    return dict(row)


def set_enabled(conn: Connection, config_id: UUID | str, enabled: bool) -> dict | None:
    row = conn.execute(
        text(
            "UPDATE model_configs SET enabled = :enabled, config_version = config_version + 1, "
            "updated_at = now() WHERE id = :id RETURNING *"
        ),
        {"id": str(config_id), "enabled": enabled},
    ).mappings().first()
    return dict(row) if row else None
