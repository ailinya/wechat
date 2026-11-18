"""Material library logic (task 3.8): manual/link/upload, revisions, categories,
tags, favorites, archive and constrained delete."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from app.adapters import source_fetch
from app.errors import ApiError
from app.repositories import material_repository as repo
from app.services import audit_service, document_parser


def _tags(conn: Connection, tag_ids: list[UUID | str]) -> list[str]:
    resolved = repo.valid_tag_ids(conn, tag_ids)
    if len(resolved) != len(set(str(value) for value in tag_ids)):
        raise ApiError(422, "invalid_tags", "部分标签不存在")
    return resolved


def _category(conn: Connection, category_id: UUID | str | None) -> str | None:
    if category_id is None:
        return None
    if not repo.category_by_id(conn, category_id):
        raise ApiError(422, "invalid_category", "分类不存在")
    return str(category_id)


def create_material(
    conn: Connection,
    *,
    title: str,
    content_markdown: str,
    origin: str,
    user_id: UUID | str | None,
    category_id: UUID | str | None = None,
    tag_ids: list[UUID | str] | None = None,
    source_url: str | None = None,
    file_ids: list[UUID | str] | None = None,
) -> dict:
    category = _category(conn, category_id)
    tag_values = _tags(conn, tag_ids or [])
    material_id = conn.execute(
        text(
            "INSERT INTO materials (title, origin, usage_status, category_id, created_by) "
            "VALUES (:title, :origin, 'pending_review', :category, :user) RETURNING id"
        ),
        {"title": title[:256], "origin": origin, "category": category,
         "user": str(user_id) if user_id else None},
    ).scalar_one()
    repo.add_revision(
        conn, material_id, revision_no=1, content_markdown=content_markdown,
        title=title, created_by=user_id, file_ids=file_ids,
    )
    repo.set_material_tags(conn, material_id, tag_values)
    if source_url:
        conn.execute(
            text("UPDATE materials SET summary = :url WHERE id = :id"),
            {"url": source_url[:2000], "id": str(material_id)},
        )
    return repo.material_by_id(conn, material_id)


def create_from_text(conn: Connection, payload, user_id: UUID | str | None) -> dict:
    return create_material(
        conn, title=payload.title, content_markdown=payload.content_markdown,
        origin="manual", user_id=user_id, category_id=payload.category_id,
        tag_ids=payload.tag_ids,
    )


def create_from_link(
    conn: Connection, url: str, title: str | None, user_id: UUID | str | None,
    *, transport=None, resolver=None,
) -> dict:
    try:
        fetched = source_fetch.fetch(url, transport=transport, resolver=resolver)
        parsed = document_parser.parse_bytes(
            fetched.content.encode("utf-8"), fetched.content_type or "text/html"
        )
    except source_fetch.FetchError as exc:
        raise ApiError(400, "source_url_rejected", exc.message) from None
    except document_parser.ParseError as exc:
        raise ApiError(422, "parse_failed", exc.message) from None
    return create_material(
        conn, title=title or parsed.title or url[:256],
        content_markdown=parsed.content_markdown, origin="link", user_id=user_id,
        source_url=fetched.final_url,
    )


def create_from_upload(
    conn: Connection,
    *,
    object_id: UUID | str,
    object_meta: dict,
    data: bytes,
    title: str,
    user_id: UUID | str | None,
) -> dict:
    try:
        parsed = document_parser.parse_bytes(
            data, object_meta["content_type"], object_meta.get("object_key")
        )
    except document_parser.ParseError as exc:
        raise ApiError(422, "parse_failed", exc.message) from None
    return create_material(
        conn, title=title, content_markdown=parsed.content_markdown,
        origin="upload", user_id=user_id, file_ids=[object_id],
    )


def get_detail(conn: Connection, material_id: UUID | str, user_id: UUID | str | None) -> dict:
    material = repo.material_by_id(conn, material_id)
    if not material:
        raise ApiError(404, "not_found", "素材不存在")
    revision = repo.current_revision(conn, material_id)
    return {
        "material": material,
        "revision": revision,
        "tags": repo.tags_for_material(conn, material_id),
        "favorite_count": repo.favorite_count(conn, material_id),
        "favorited_by_me": bool(user_id and repo.is_favorite(conn, material_id, user_id)),
    }


def list_materials(conn: Connection, page, page_size, user_id, *, usage_status, category_id,
                   tag_id, keyword, favorite_mine) -> tuple[list[dict], int]:
    return repo.list_materials(
        conn, page, page_size, usage_status=usage_status, category_id=category_id,
        tag_id=tag_id, keyword=keyword,
        favorite_user_id=user_id if favorite_mine else None,
    )


def update_material(
    conn: Connection, material_id: UUID | str, payload, user_id: UUID | str | None
) -> dict:
    current = repo.material_by_id(conn, material_id)
    if not current:
        raise ApiError(404, "not_found", "素材不存在")

    locked=repo.lock_metadata(conn,material_id)
    if getattr(payload,'base_metadata_version',None) is not None and locked['metadata_version'] != payload.base_metadata_version:
        raise ApiError(409,'conflict','素材元数据版本已变化')
    manual=set(current.get('manual_fields') or [])
    manual.update(locked['manual_fields'] or [])
    if getattr(payload,'summary',None) is not None:
        manual.add('summary')
    if payload.title is not None or payload.content_markdown is not None:
        manual.add('body')
    if payload.category_id is not None:
        manual.add('category')
    if payload.tag_ids is not None:
        manual.add('tags')
    repo.record_manual_metadata(conn,material_id,manual,getattr(payload,'summary',None))

    if payload.title is not None or payload.content_markdown is not None:
        revision = repo.current_revision(conn, material_id)
        body = payload.content_markdown or revision["content_markdown"]
        repo.add_revision(
            conn, material_id, revision_no=repo.next_revision_no(conn, material_id),
            content_markdown=body, title=payload.title, created_by=user_id,
        )
    if payload.usage_status is not None:
        repo.update_material_fields(conn, material_id, usage_status=payload.usage_status)
    if payload.category_id is not None:
        repo.update_material_fields(conn, material_id, category_id=_category(conn, payload.category_id))
    if payload.tag_ids is not None:
        repo.set_material_tags(conn, material_id, _tags(conn, payload.tag_ids))
    audit_service.record_operation(
        conn, user_id=user_id, action="material.update",
        object_type="material", object_id=material_id,
    )
    return get_detail(conn, material_id, user_id)


def delete_material(conn: Connection, material_id: UUID | str, user_id: UUID | str | None) -> dict:
    material = repo.material_by_id(conn, material_id)
    if not material:
        raise ApiError(404, "not_found", "素材不存在")
    repo.soft_delete_material(conn, material_id)
    audit_service.record_operation(
        conn, user_id=user_id, action="material.delete",
        object_type="material", object_id=material_id,
    )
    return {"id": str(material_id), "usage_status": "archived"}


def favorite(conn: Connection, material_id: UUID | str, user_id: UUID | str) -> dict:
    if not repo.material_by_id(conn, material_id):
        raise ApiError(404, "not_found", "素材不存在")
    return repo.favorite(conn, material_id, user_id)


def unfavorite(conn: Connection, material_id: UUID | str, user_id: UUID | str) -> None:
    repo.unfavorite(conn, material_id, user_id)


# --- categories ---


def _would_cycle(conn: Connection, category_id: UUID | str, parent_id: UUID | str | None) -> bool:
    seen: set[str] = set()
    current = parent_id
    while current and str(current) not in seen:
        current = str(current)
        if current == str(category_id):
            return True
        seen.add(current)
        category = repo.category_by_id(conn, current)
        current = category["parent_id"] if category else None
    return False


def create_category(conn: Connection, name: str, parent_id: UUID | str | None) -> dict:
    if parent_id and not repo.category_by_id(conn, parent_id):
        raise ApiError(422, "invalid_category", "父分类不存在")
    return repo.create_category(conn, name, parent_id)


def update_category(conn: Connection, category_id: UUID | str, name: str, parent_id) -> dict:
    if not repo.category_by_id(conn, category_id):
        raise ApiError(404, "not_found", "分类不存在")
    if parent_id and not repo.category_by_id(conn, parent_id):
        raise ApiError(422, "invalid_category", "父分类不存在")
    if _would_cycle(conn, category_id, parent_id):
        raise ApiError(409, "category_cycle", "分类父级不得形成循环")
    return repo.update_category(conn, category_id, name, parent_id)


def delete_category(conn: Connection, category_id: UUID | str) -> None:
    if not repo.category_by_id(conn, category_id):
        raise ApiError(404, "not_found", "分类不存在")
    if repo.category_has_children(conn, category_id) or repo.category_has_materials(conn, category_id):
        raise ApiError(409, "category_not_empty", "分类下仍有素材或子分类")
    repo.delete_category(conn, category_id)


# --- tags ---


def create_tag(conn: Connection, name: str) -> dict:
    if repo.tag_by_name(conn, name):
        raise ApiError(409, "conflict", "标签名称已存在")
    return repo.create_tag(conn, name)


def update_tag(conn: Connection, tag_id: UUID | str, name: str) -> dict:
    if not repo.tag_by_id(conn, tag_id):
        raise ApiError(404, "not_found", "标签不存在")
    existing = repo.tag_by_name(conn, name)
    if existing and str(existing["id"]) != str(tag_id):
        raise ApiError(409, "conflict", "标签名称已存在")
    return repo.update_tag(conn, tag_id, name)


def delete_tag(conn: Connection, tag_id: UUID | str) -> None:
    if not repo.tag_by_id(conn, tag_id):
        raise ApiError(404, "not_found", "标签不存在")
    repo.delete_tag(conn, tag_id)  # links removed by ON DELETE CASCADE


# --- bulk ---


def bulk_action(conn: Connection, payload, user_id: UUID | str | None) -> dict:
    items: list[dict] = []
    counts = {"success": 0, "skipped": 0, "failed": 0}
    for material_id in payload.material_ids:
        material = repo.material_by_id(conn, material_id)
        if not material:
            items.append({"material_id": str(material_id), "status": "failed", "error": "素材不存在"})
            counts["failed"] += 1
            continue
        try:
            action = payload.action
            if action == "archive":
                repo.update_material_fields(conn, material_id, usage_status="archived")
            elif action == "unarchive":
                repo.update_material_fields(conn, material_id, usage_status="ready_to_use")
            elif action == "mark_used":
                repo.update_material_fields(conn, material_id, usage_status="used")
            elif action == "mark_ready":
                repo.update_material_fields(conn, material_id, usage_status="ready_to_use")
            elif action == "set_category":
                repo.update_material_fields(conn, material_id, category_id=_category(conn, payload.category_id))
            elif action == "add_tags":
                merged = {str(t["id"]) for t in repo.tags_for_material(conn, material_id)}
                merged.update(str(value) for value in payload.tag_ids)
                repo.set_material_tags(conn, material_id, _tags(conn, list(merged)))
            elif action == "remove_tags":
                remaining = {str(t["id"]) for t in repo.tags_for_material(conn, material_id)}
                remaining.difference_update(str(value) for value in payload.tag_ids)
                repo.set_material_tags(conn, material_id, list(remaining))
            else:
                raise ApiError(400, "bad_request", "不支持的批量操作")
            items.append({"material_id": str(material_id), "status": "success", "error": None})
            counts["success"] += 1
        except ApiError as exc:
            items.append({"material_id": str(material_id), "status": "failed", "error": exc.message})
            counts["failed"] += 1
    audit_service.record_operation(
        conn, user_id=user_id, action="material.bulk", object_type="material",
        detail={"action": payload.action, "counts": counts},
    )
    return {"items": items, "counts": counts}
