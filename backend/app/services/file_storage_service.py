"""File upload grant / completion / download logic (task 2.6)."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from app.adapters import object_storage
from app.config import Settings
from app.errors import ApiError

UPLOAD_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "application/pdf",
    "text/plain",
    "text/markdown",
}
MAX_UPLOAD_BYTES = 52_428_800  # 50 MiB, mirrors UploadGrantRequest validation

_UNSAFE = re.compile(r"[^\w.-]+")


def _safe_filename(filename: str) -> str:
    stem = _UNSAFE.sub("-", filename.strip())[:80]
    return stem or "file"


def _grant_row(conn: Connection, grant_id: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM upload_grants WHERE id = :id"), {"id": str(grant_id)}
    ).mappings().first()
    return dict(row) if row else None


def _stored_row(conn: Connection, object_id: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM stored_objects WHERE id = :id"), {"id": str(object_id)}
    ).mappings().first()
    return dict(row) if row else None


def _stored_by_key(conn: Connection, bucket: str, object_key: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM stored_objects WHERE bucket = :b AND object_key = :k"),
        {"b": bucket, "k": object_key},
    ).mappings().first()
    return dict(row) if row else None


def create_grant(
    conn: Connection, settings: Settings, user_id: UUID | str, *, filename: str, content_type: str, size_bytes: int
) -> dict:
    """Validate limits, persist the authorization and return a short-lived
    presigned PUT URL. Long-term credentials never reach the client."""
    if content_type not in UPLOAD_CONTENT_TYPES:
        raise ApiError(400, "unsupported_content_type", f"不支持的文件类型：{content_type}")
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise ApiError(400, "payload_too_large", f"文件大小超出限制（最大 {MAX_UPLOAD_BYTES} 字节）")

    object_key = f"{datetime.now(timezone.utc):%Y/%m}/{uuid4().hex[:8]}-{_safe_filename(filename)}"
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.upload_grant_ttl_minutes)

    row = conn.execute(
        text(
            "INSERT INTO upload_grants (user_id, bucket, object_key, max_bytes, "
            "content_type, token_hash, expires_at) "
            "VALUES (:user_id, :bucket, :object_key, :max_bytes, :content_type, "
            ":token_hash, :expires_at) "
            "RETURNING id, bucket, object_key, max_bytes, content_type, expires_at"
        ),
        {
            "user_id": str(user_id),
            "bucket": settings.rustfs_bucket,
            "object_key": object_key,
            "max_bytes": size_bytes,
            "content_type": content_type,
            "token_hash": token_hash,
            "expires_at": expires.isoformat(),
        },
    ).mappings().one()
    grant = dict(row)
    grant["upload_url"] = object_storage.presigned_put(
        settings, object_key, settings.upload_grant_ttl_minutes
    )
    return grant


def complete_grant(
    conn: Connection, settings: Settings, user_id: UUID | str, grant_id: str, sha256: str
) -> dict:
    """Verify applicant, grant validity, and the actual stored object before
    registering it; repeated completion replays the same stored object."""
    grant = _grant_row(conn, grant_id)
    if not grant:
        raise ApiError(404, "not_found", "上传授权不存在")
    if str(grant["user_id"]) != str(user_id):
        raise ApiError(403, "forbidden", "只能完成本人申请的上传授权")

    expires_at = grant["expires_at"] if grant["expires_at"].tzinfo else grant["expires_at"].replace(tzinfo=timezone.utc)
    if grant["completed_at"] is None and expires_at < datetime.now(timezone.utc):
        raise ApiError(400, "grant_expired", "上传授权已过期，请重新申请")

    # Already registered (idempotent replay of a lost completion response).
    existing = _stored_by_key(conn, grant["bucket"], grant["object_key"])
    if existing and grant["completed_at"] is not None:
        return existing

    stat = object_storage.stat_object(settings, grant["object_key"])
    if stat is None:
        raise ApiError(400, "object_not_uploaded", "对象尚未上传或不存在")
    if stat["size_bytes"] > grant["max_bytes"] or stat["size_bytes"] == 0:
        raise ApiError(400, "object_mismatch", "实际文件大小与授权不符")

    inserted = conn.execute(
        text(
            "INSERT INTO stored_objects (bucket, object_key, size_bytes, "
            "content_type, sha256, uploader_id) "
            "VALUES (:bucket, :object_key, :size, :ctype, :sha, :uploader) "
            "ON CONFLICT (bucket, object_key) DO NOTHING RETURNING id"
        ),
        {
            "bucket": grant["bucket"],
            "object_key": grant["object_key"],
            "size": stat["size_bytes"],
            "ctype": grant["content_type"],
            "sha": sha256,
            "uploader": str(user_id),
        },
    ).scalar()
    object_id = inserted or _stored_by_key(conn, grant["bucket"], grant["object_key"])["id"]
    conn.execute(
        text("UPDATE upload_grants SET completed_at = now() WHERE id = :id AND completed_at IS NULL"),
        {"id": grant["id"]},
    )
    return _stored_row(conn, str(object_id))


def create_download_grant(
    conn: Connection, settings: Settings, user_id: UUID | str, object_id: str, has_resource_access: bool
) -> dict:
    """Short-term download authorization for a registered object."""
    stored = _stored_row(conn, str(object_id))
    if not stored:
        raise ApiError(404, "not_found", "文件不存在")
    allowed = str(stored["uploader_id"]) == str(user_id) or has_resource_access
    if not allowed:
        raise ApiError(403, "forbidden", "没有下载该文件的权限")
    url = object_storage.presigned_get(
        settings, stored["object_key"], settings.download_grant_ttl_minutes
    )
    return {
        "object_id": stored["id"],
        "url": url,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=settings.download_grant_ttl_minutes),
    }
