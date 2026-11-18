"""Source management logic (task 3.4).

Validates source URLs before persistence so internal/forbidden addresses are
rejected up front. Connection testing uses the bounded adapter and records
reachability timestamps; the adapter's transport/resolver are injectable for
reproducible fixtures.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from app.adapters import source_fetch
from app.errors import ApiError
from app.repositories import collection_repository as repo
from app.schemas.collection import CollectionSourceIn, SourceTestResult
from app.services import audit_service

ALLOWED_SCHEMES_MESSAGE = "来源地址必须是可访问的公网 http/https 地址"


def _validate_base_url(url: str) -> None:
    try:
        source_fetch.validate_url(url)
    except source_fetch.FetchError as exc:
        raise ApiError(400, "source_url_rejected", exc.message or ALLOWED_SCHEMES_MESSAGE) from None


def create_source(
    conn: Connection, payload: CollectionSourceIn, user_id: UUID | str | None
) -> dict:
    _validate_base_url(payload.base_url.strip())
    if repo.source_with_name_exists(conn, payload.name):
        raise ApiError(409, "conflict", "来源名称已存在")
    return repo.create_source(
        conn,
        name=payload.name,
        source_type=payload.source_type,
        base_url=payload.base_url.strip(),
        description=payload.description,
        enabled=payload.enabled,
        created_by=user_id,
        page_kind=payload.page_kind,
        article_link_selector=payload.article_link_selector,
        next_page_selector=payload.next_page_selector,
    )


def list_sources(conn: Connection, page: int, page_size: int, keyword: str | None) -> tuple[list[dict], int]:
    return repo.list_sources(conn, page, page_size, keyword)


def get_source(conn: Connection, source_id: UUID | str) -> dict:
    row = repo.get_source(conn, source_id)
    if not row:
        raise ApiError(404, "not_found", "来源不存在")
    return row


def update_source(
    conn: Connection, source_id: UUID | str, payload: CollectionSourceIn
) -> dict:
    current = get_source(conn, source_id)
    _validate_base_url(payload.base_url.strip())
    if repo.source_with_name_exists(conn, payload.name, exclude_id=source_id):
        raise ApiError(409, "conflict", "来源名称已存在")
    updated = repo.update_source(
        conn,
        source_id,
        name=payload.name,
        source_type=payload.source_type,
        base_url=payload.base_url.strip(),
        description=payload.description,
        enabled=payload.enabled,
        page_kind=payload.page_kind,
        article_link_selector=payload.article_link_selector,
        next_page_selector=payload.next_page_selector,
    )
    assert updated is not None  # get_source already confirmed existence
    if current["base_url"] != updated["base_url"]:
        # A changed address invalidates previous reachability.
        conn.execute(
            text(
                "UPDATE collection_sources SET status = 'active', last_success_at = NULL "
                "WHERE id = :id"
            ),
            {"id": str(source_id)},
        )
    return updated


def delete_source(
    conn: Connection, source_id: UUID | str, user_id: UUID | str | None
) -> dict:
    row = repo.soft_delete_source(conn, source_id)
    if not row:
        raise ApiError(404, "not_found", "来源不存在")
    audit_service.record_operation(
        conn,
        user_id=user_id,
        action="collection.source.delete",
        object_type="collection_source",
        object_id=source_id,
        detail={"name": row["name"]},
    )
    return row


def test_source(
    conn: Connection,
    source_id: UUID | str,
    *,
    transport: Any = None,
    resolver: Any = None,
    allowed_hosts: list[str] | None = None,
) -> SourceTestResult:
    source = get_source(conn, source_id)
    try:
        result = source_fetch.fetch(
            source["base_url"],
            transport=transport,
            resolver=resolver,
            allowed_hosts=allowed_hosts,
        )
    except source_fetch.FetchError as exc:
        repo.set_check_result(conn, source_id, reachable=False)
        return SourceTestResult(
            reachable=False,
            error=exc.message,
        )
    reachable = 200 <= result.status_code < 400
    repo.set_check_result(conn, source_id, reachable=reachable)
    return SourceTestResult(
        reachable=reachable,
        status_code=result.status_code,
        latency_ms=result.elapsed_ms,
        error=None if reachable else f"来源返回 HTTP {result.status_code}",
    )
