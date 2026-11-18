"""Search service configuration persistence (task 3.17)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def list_configs(conn: Connection, page: int, page_size: int) -> tuple[list[dict], int]:
    total = conn.execute(text("SELECT count(*) FROM search_configs")).scalar_one()
    rows = conn.execute(
        text(
            "SELECT * FROM search_configs ORDER BY created_at DESC, id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return [dict(row) for row in rows], total


def get_config(conn: Connection, config_id: UUID | str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM search_configs WHERE id = :id"), {"id": str(config_id)}
    ).mappings().first()
    return dict(row) if row else None


def name_exists(conn: Connection, name: str) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM search_configs WHERE name = :name LIMIT 1"), {"name": name}).first()
        is not None
    )


def create_config(
    conn: Connection, *, name: str, provider: str, credential_ref: str | None,
    enabled: bool, max_results: int, supports_domain_filter: bool, supports_date_filter: bool,
) -> dict:
    row = conn.execute(
        text(
            "INSERT INTO search_configs "
            "(name, provider, credential_ref, enabled, max_results, "
            " supports_domain_filter, supports_date_filter) "
            "VALUES (:name, :provider, :cred, :enabled, :max_results, :domain, :date) RETURNING *"
        ),
        {
            "name": name, "provider": provider, "cred": credential_ref,
            "enabled": enabled, "max_results": max_results,
            "domain": supports_domain_filter, "date": supports_date_filter,
        },
    ).mappings().one()
    return dict(row)


def update_config(conn: Connection, config_id: UUID | str, updates: dict) -> dict | None:
    allowed = {"name", "credential_ref", "enabled", "max_results", "supports_domain_filter", "supports_date_filter"}
    values = {key: value for key, value in updates.items() if key in allowed}
    if not values:
        return get_config(conn, config_id)
    assignments = ", ".join(f"{key} = :{key}" for key in values)
    row = conn.execute(text(
        f"UPDATE search_configs SET {assignments}, config_version = config_version + 1, "
        "updated_at = now() WHERE id = :id RETURNING *"
    ), {**values, "id": str(config_id)}).mappings().first()
    return dict(row) if row else None
