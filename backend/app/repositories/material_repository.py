"""Material persistence (tasks 3.7 materialization + 3.8 material library)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def lock_metadata(conn, material_id):
    return (
        conn.execute(
            text(
                "SELECT metadata_version,manual_fields FROM materials WHERE id=:id FOR UPDATE"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .one()
    )


def record_manual_metadata(conn, material_id, fields, summary=None):
    import json

    conn.execute(
        text(
            "UPDATE materials SET metadata_version=metadata_version+1,manual_fields=CAST(:manual AS jsonb),summary=COALESCE(:summary,summary) WHERE id=:id"
        ),
        {
            "id": str(material_id),
            "manual": json.dumps(sorted(fields)),
            "summary": summary,
        },
    )


def current_revision(conn: Connection, material_id: UUID | str) -> dict | None:
    row = (
        conn.execute(
            text(
                "SELECT r.* FROM material_revisions r "
                "JOIN materials m ON m.current_revision_id = r.id "
                "WHERE m.id = :id"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def find_material_by_dedup(conn: Connection, dedup_key: str) -> dict | None:
    """Find the material a previous result with the same dedup key produced."""
    row = (
        conn.execute(
            text(
                "SELECT m.id, r.content_hash FROM materials m "
                "JOIN collection_results cr ON cr.material_id = m.id "
                "LEFT JOIN material_revisions r ON r.id = m.current_revision_id "
                "WHERE cr.dedup_key = :key "
                "AND cr.materialize_status IN ('materialized', 'new_progress') "
                "AND m.deleted_at IS NULL "
                "ORDER BY cr.collected_at DESC LIMIT 1"
            ),
            {"key": dedup_key},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def find_material_by_content_hash(conn: Connection, content_hash: str) -> dict | None:
    """Find an active collected material with an identical current body."""
    row = (
        conn.execute(
            text(
                "SELECT m.id, r.content_hash FROM materials m "
                "JOIN material_revisions r ON r.id=m.current_revision_id "
                "WHERE r.content_hash=:hash AND m.origin='collection' AND m.deleted_at IS NULL "
                "ORDER BY m.created_at, m.id LIMIT 1"
            ),
            {"hash": content_hash},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_material_with_revision(
    conn: Connection,
    *,
    title: str,
    markdown: str,
    content_hash: str,
    origin: str,
    created_by: UUID | str | None,
    source_result_id: UUID | str,
) -> dict:
    material_id = conn.execute(
        text(
            "INSERT INTO materials (title, origin, usage_status, created_by) "
            "VALUES (:title, :origin, 'pending_review', :created_by) RETURNING id"
        ),
        {
            "title": title[:256],
            "origin": origin,
            "created_by": str(created_by) if created_by else None,
        },
    ).scalar_one()
    revision_id = conn.execute(
        text(
            "INSERT INTO material_revisions "
            "(material_id, revision_no, content_markdown, content_hash, "
            " created_from_result_id, created_by) "
            "VALUES (:material, 1, :body, :hash, :result, :created_by) RETURNING id"
        ),
        {
            "material": str(material_id),
            "body": markdown,
            "hash": content_hash,
            "result": str(source_result_id),
            "created_by": str(created_by) if created_by else None,
        },
    ).scalar_one()
    conn.execute(
        text("UPDATE materials SET current_revision_id = :revision WHERE id = :id"),
        {"revision": str(revision_id), "id": str(material_id)},
    )
    return {"material_id": str(material_id), "revision_id": str(revision_id)}


def add_relation(
    conn: Connection, source_id: UUID | str, target_id: UUID | str, relation_type: str
) -> None:
    conn.execute(
        text(
            "INSERT INTO material_relations (source_material_id, target_material_id, relation_type) "
            "VALUES (:source, :target, :type) ON CONFLICT DO NOTHING"
        ),
        {"source": str(source_id), "target": str(target_id), "type": relation_type},
    )


def relations_for_material(conn: Connection, material_id: UUID | str) -> list[dict]:
    rows = (
        conn.execute(
            text(
                "SELECT id, source_material_id, target_material_id, relation_type, created_at "
                "FROM material_relations WHERE source_material_id = :id OR target_material_id = :id "
                "ORDER BY created_at"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def material_by_id(conn: Connection, material_id: UUID | str) -> dict | None:
    row = (
        conn.execute(
            text("SELECT * FROM materials WHERE id = :id AND deleted_at IS NULL"),
            {"id": str(material_id)},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# --- material library (task 3.8) ---


def list_materials(
    conn: Connection,
    page: int,
    page_size: int,
    *,
    usage_status: str | None,
    category_id: UUID | str | None,
    tag_id: UUID | str | None,
    keyword: str | None,
    favorite_user_id: UUID | str | None = None,
) -> tuple[list[dict], int]:
    where, params = ["m.deleted_at IS NULL"], {}
    if usage_status:
        where.append("m.usage_status = :status")
        params["status"] = usage_status
    if category_id:
        where.append("m.category_id = :category")
        params["category"] = str(category_id)
    if tag_id:
        where.append(
            "EXISTS (SELECT 1 FROM material_tags mt WHERE mt.material_id = m.id AND mt.tag_id = :tag)"
        )
        params["tag"] = str(tag_id)
    if keyword:
        where.append("m.title ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if favorite_user_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM material_favorites f "
            "WHERE f.material_id = m.id AND f.user_id = :fav_user)"
        )
        params["fav_user"] = str(favorite_user_id)
    clause = " AND ".join(where)
    if len(where) == 1:
        total = conn.execute(text("SELECT active_count FROM material_counts WHERE singleton")).scalar_one()
    else:
        total = conn.execute(
            text(f"SELECT count(*) FROM materials m WHERE {clause}"), params
        ).scalar_one()
    rows = (
        conn.execute(
            text(
                f"SELECT m.* FROM materials m WHERE {clause} "
                "ORDER BY m.created_at DESC, m.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows], total


def tags_for_material(conn: Connection, material_id: UUID | str) -> list[dict]:
    rows = (
        conn.execute(
            text(
                "SELECT t.id, t.name FROM tags t JOIN material_tags mt ON mt.tag_id = t.id "
                "WHERE mt.material_id = :id ORDER BY t.name"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def tags_for_materials(conn: Connection, material_ids: list) -> dict[str,list[dict]]:
    result = {str(value):[] for value in material_ids}
    if not material_ids:
        return result
    rows = conn.execute(text('SELECT mt.material_id,t.id,t.name FROM material_tags mt JOIN tags t ON t.id=mt.tag_id WHERE mt.material_id=ANY(CAST(:ids AS uuid[])) ORDER BY t.name,t.id'), {'ids':[str(value) for value in material_ids]}).mappings()
    for row in rows:
        result[str(row['material_id'])].append({'id':row['id'],'name':row['name']})
    return result


def set_material_tags(
    conn: Connection, material_id: UUID | str, tag_ids: list[UUID | str]
) -> None:
    conn.execute(
        text("DELETE FROM material_tags WHERE material_id = :id"),
        {"id": str(material_id)},
    )
    for tag_id in tag_ids:
        conn.execute(
            text(
                "INSERT INTO material_tags (material_id, tag_id) VALUES (:m, :t) "
                "ON CONFLICT DO NOTHING"
            ),
            {"m": str(material_id), "t": str(tag_id)},
        )


def next_revision_no(conn: Connection, material_id: UUID | str) -> int:
    value = conn.execute(
        text(
            "SELECT COALESCE(MAX(revision_no), 0) + 1 FROM material_revisions WHERE material_id = :id"
        ),
        {"id": str(material_id)},
    ).scalar_one()
    return int(value)


def add_revision(
    conn: Connection,
    material_id: UUID | str,
    *,
    revision_no: int,
    content_markdown: str,
    title: str | None,
    created_by: UUID | str | None,
    file_ids: list[UUID | str] | None = None,
) -> dict:
    import hashlib
    import json

    row = (
        conn.execute(
            text(
                "INSERT INTO material_revisions "
                "(material_id, revision_no, content_markdown, content_hash, file_ids, created_by) "
                "VALUES (:material, :no, :body, :hash, CAST(:files AS jsonb), :created_by) RETURNING *"
            ),
            {
                "material": str(material_id),
                "no": revision_no,
                "body": content_markdown,
                "hash": hashlib.sha256(content_markdown.encode("utf-8")).hexdigest(),
                "files": json.dumps([str(value) for value in (file_ids or [])]),
                "created_by": str(created_by) if created_by else None,
            },
        )
        .mappings()
        .one()
    )
    conn.execute(
        text(
            "UPDATE materials SET current_revision_id = :revision, title = COALESCE(:title, title), updated_at = now() WHERE id = :id"
        ),
        {"revision": str(row["id"]), "title": title, "id": str(material_id)},
    )
    return dict(row)


def list_revisions(conn: Connection, material_id: UUID | str) -> list[dict]:
    rows = (
        conn.execute(
            text(
                "SELECT * FROM material_revisions WHERE material_id = :id ORDER BY revision_no"
            ),
            {"id": str(material_id)},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def update_material_fields(
    conn: Connection,
    material_id: UUID | str,
    *,
    usage_status: str | None = None,
    category_id: UUID | str | None = None,
    clear_category: bool = False,
) -> None:
    assignments = ["updated_at = now()"]
    params: dict[str, Any] = {"id": str(material_id)}
    if usage_status is not None:
        assignments.append("usage_status = :status")
        params["status"] = usage_status
    if clear_category:
        assignments.append("category_id = NULL")
    elif category_id is not None:
        assignments.append("category_id = :category")
        params["category"] = str(category_id)
    conn.execute(
        text(f"UPDATE materials SET {', '.join(assignments)} WHERE id = :id"), params
    )


def soft_delete_material(conn: Connection, material_id: UUID | str) -> bool:
    row = conn.execute(
        text(
            "UPDATE materials SET deleted_at = now(), usage_status = 'archived', "
            "updated_at = now() WHERE id = :id AND deleted_at IS NULL RETURNING id"
        ),
        {"id": str(material_id)},
    ).scalar()
    return row is not None


def material_relations(conn: Connection, material_id: UUID | str) -> list[dict]:
    return relations_for_material(conn, material_id)


# --- categories ---


def list_categories(conn: Connection) -> list[dict]:
    rows = (
        conn.execute(
            text("SELECT * FROM material_categories ORDER BY sort_order, name")
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def category_by_id(conn: Connection, category_id: UUID | str) -> dict | None:
    row = (
        conn.execute(
            text("SELECT * FROM material_categories WHERE id = :id"),
            {"id": str(category_id)},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_category(conn: Connection, name: str, parent_id: UUID | str | None) -> dict:
    row = (
        conn.execute(
            text(
                "INSERT INTO material_categories (name, parent_id) VALUES (:name, :parent) RETURNING *"
            ),
            {"name": name, "parent": str(parent_id) if parent_id else None},
        )
        .mappings()
        .one()
    )
    return dict(row)


def update_category(
    conn: Connection, category_id: UUID | str, name: str, parent_id: UUID | str | None
) -> dict | None:
    row = (
        conn.execute(
            text(
                "UPDATE material_categories SET name = :name, parent_id = :parent, "
                "updated_at = now() WHERE id = :id RETURNING *"
            ),
            {
                "id": str(category_id),
                "name": name,
                "parent": str(parent_id) if parent_id else None,
            },
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def category_has_children(conn: Connection, category_id: UUID | str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM material_categories WHERE parent_id = :id LIMIT 1"),
            {"id": str(category_id)},
        ).first()
        is not None
    )


def category_has_materials(conn: Connection, category_id: UUID | str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM materials WHERE category_id = :id AND deleted_at IS NULL LIMIT 1"
            ),
            {"id": str(category_id)},
        ).first()
        is not None
    )


def delete_category(conn: Connection, category_id: UUID | str) -> bool:
    row = conn.execute(
        text("DELETE FROM material_categories WHERE id = :id RETURNING id"),
        {"id": str(category_id)},
    ).scalar()
    return row is not None


# --- tags ---


def list_tags(conn: Connection) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM tags ORDER BY name")).mappings().all()
    return [dict(row) for row in rows]


def tag_by_id(conn: Connection, tag_id: UUID | str) -> dict | None:
    row = (
        conn.execute(text("SELECT * FROM tags WHERE id = :id"), {"id": str(tag_id)})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def tag_by_name(conn: Connection, name: str) -> dict | None:
    row = (
        conn.execute(text("SELECT * FROM tags WHERE name = :name"), {"name": name})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def create_tag(conn: Connection, name: str) -> dict:
    row = (
        conn.execute(
            text("INSERT INTO tags (name) VALUES (:name) RETURNING *"), {"name": name}
        )
        .mappings()
        .one()
    )
    return dict(row)


def update_tag(conn: Connection, tag_id: UUID | str, name: str) -> dict | None:
    row = (
        conn.execute(
            text(
                "UPDATE tags SET name = :name, updated_at = now() WHERE id = :id RETURNING *"
            ),
            {"id": str(tag_id), "name": name},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def delete_tag(conn: Connection, tag_id: UUID | str) -> bool:
    row = conn.execute(
        text("DELETE FROM tags WHERE id = :id RETURNING id"), {"id": str(tag_id)}
    ).scalar()
    return row is not None


def valid_tag_ids(conn: Connection, tag_ids: list[UUID | str]) -> list[str]:
    if not tag_ids:
        return []
    ids = [str(value) for value in tag_ids]
    rows = (
        conn.execute(text("SELECT id FROM tags WHERE id = ANY(:ids)"), {"ids": ids})
        .scalars()
        .all()
    )
    return [str(row) for row in rows]


# --- favorites (user-isolated) ---


def favorite(conn: Connection, material_id: UUID | str, user_id: UUID | str) -> dict:
    row = (
        conn.execute(
            text(
                "INSERT INTO material_favorites (material_id, user_id) VALUES (:m, :u) "
                "ON CONFLICT (material_id, user_id) DO UPDATE SET created_at = material_favorites.created_at "
                "RETURNING *"
            ),
            {"m": str(material_id), "u": str(user_id)},
        )
        .mappings()
        .one()
    )
    return dict(row)


def unfavorite(conn: Connection, material_id: UUID | str, user_id: UUID | str) -> bool:
    row = conn.execute(
        text(
            "DELETE FROM material_favorites WHERE material_id = :m AND user_id = :u RETURNING id"
        ),
        {"m": str(material_id), "u": str(user_id)},
    ).scalar()
    return row is not None


def is_favorite(conn: Connection, material_id: UUID | str, user_id: UUID | str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM material_favorites WHERE material_id = :m AND user_id = :u LIMIT 1"
            ),
            {"m": str(material_id), "u": str(user_id)},
        ).first()
        is not None
    )


def favorite_count(conn: Connection, material_id: UUID | str) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM material_favorites WHERE material_id = :id"),
            {"id": str(material_id)},
        ).scalar_one()
    )
