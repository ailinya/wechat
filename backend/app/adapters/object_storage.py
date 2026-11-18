"""RustFS (S3-compatible) adapter (task 2.6).

Short-term presigned URLs only; the long-term access keys never leave the
server process.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

from minio import Minio

from app.config import Settings
from app.errors import ApiError

_REGION = None


def _client(settings: Settings) -> Minio:
    parsed = urlparse(settings.rustfs_endpoint)
    if not parsed.netloc:
        raise ApiError(503, "storage_unavailable", "对象存储端点配置无效")
    secure = parsed.scheme == "https"
    try:
        return Minio(
            parsed.netloc,
            access_key=settings.rustfs_access_key,
            secret_key=settings.rustfs_secret_key.get_secret_value(),
            secure=secure,
        )
    except Exception as exc:  # invalid credentials shape etc.
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc


def ensure_bucket(settings: Settings) -> None:
    client = _client(settings)
    bucket = settings.rustfs_bucket
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc


def presigned_put(settings: Settings, object_key: str, expires_minutes: int) -> str:
    client = _client(settings)
    try:
        return client.presigned_put_object(
            settings.rustfs_bucket, object_key, timedelta(minutes=expires_minutes)
        )
    except Exception as exc:
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc


def presigned_get(settings: Settings, object_key: str, expires_minutes: int) -> str:
    client = _client(settings)
    try:
        return client.presigned_get_object(
            settings.rustfs_bucket, object_key, timedelta(minutes=expires_minutes)
        )
    except Exception as exc:
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc


def get_object(settings: Settings, object_key: str) -> bytes:
    """Read an object's bytes for server-side parsing (never sent to browser)."""
    client = _client(settings)
    try:
        response = client.get_object(settings.rustfs_bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc


def stat_object(settings: Settings, object_key: str) -> dict | None:
    """Return size/content_type for an uploaded object, or None when absent."""
    client = _client(settings)
    try:
        stat = client.stat_object(settings.rustfs_bucket, object_key)
    except Exception as exc:
        from minio.error import S3Error

        if isinstance(exc, S3Error) and exc.code in ("NoSuchKey", "NoSuchObject"):
            return None
        raise ApiError(503, "storage_unavailable", "对象存储不可用") from exc
    return {
        "size_bytes": stat.size,
        "content_type": stat.content_type,
        "etag": (stat.etag or "").strip('"'),
    }
