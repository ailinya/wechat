"""Data access for authentication, users and roles.

Table definitions mirror the 0001_access_control migration. Raw SQLAlchemy
Core is used to keep queries explicit and reviewable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Table, Column, MetaData, String, DateTime, select, insert, update, delete, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Connection

from app.modules.auth.security import hash_token
from app.schemas.auth import INITIAL_ROLE_PERMISSIONS, PermissionCode

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("account", String(64), nullable=False, unique=True),
    Column("name", String(128), nullable=False),
    Column("contact", String(255)),
    Column("status", String(16), nullable=False),
    Column("password_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

roles = Table(
    "roles",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", String(64), nullable=False, unique=True),
    Column("description", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("code", String(128), nullable=False, unique=True),
    Column("module", String(64), nullable=False),
    Column("action", String(64), nullable=False),
    Column("description", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", PGUUID(as_uuid=True), nullable=False),
    Column("role_id", PGUUID(as_uuid=True), nullable=False),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", PGUUID(as_uuid=True), nullable=False),
    Column("permission_id", PGUUID(as_uuid=True), nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", PGUUID(as_uuid=True), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def find_user_by_account(conn: Connection, account: str) -> dict[str, Any] | None:
    row = conn.execute(
        select(users).where(users.c.account == account)
    ).mappings().first()
    return dict(row) if row else None


def get_user(conn: Connection, user_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return dict(row) if row else None


def list_users(
    conn: Connection,
    page: int,
    page_size: int,
    status: str | None = None,
    keyword: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    query = select(users)
    count_query = select(func.count()).select_from(users)
    if status:
        query = query.where(users.c.status == status)
        count_query = count_query.where(users.c.status == status)
    if keyword:
        like = f"%{keyword}%"
        condition = users.c.account.ilike(like) | users.c.name.ilike(like)
        query = query.where(condition)
        count_query = count_query.where(condition)
    total = conn.execute(count_query).scalar_one()
    rows = (
        conn.execute(
            query.order_by(users.c.created_at.desc(), users.c.id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows], total


def create_user(
    conn: Connection,
    *,
    account: str,
    name: str,
    contact: str | None,
    password_hash: str,
    role_ids: list[UUID],
) -> UUID:
    now = _utcnow()
    result = conn.execute(
        insert(users).values(
            account=account,
            name=name,
            contact=contact,
            status="active",
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        ).returning(users.c.id)
    )
    user_id = result.scalar_one()
    for role_id in role_ids:
        conn.execute(
            insert(user_roles).values(user_id=user_id, role_id=role_id)
        )
    return user_id


def update_user(
    conn: Connection,
    user_id: UUID,
    *,
    name: str | None,
    contact: str | None,
    status: str | None,
    role_ids: list[UUID] | None,
) -> None:
    values: dict[str, Any] = {"updated_at": _utcnow()}
    if name is not None:
        values["name"] = name
    if contact is not None:
        values["contact"] = contact
    if status is not None:
        values["status"] = status
    conn.execute(update(users).where(users.c.id == user_id).values(**values))
    if role_ids is not None:
        conn.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
        for role_id in role_ids:
            conn.execute(
                insert(user_roles).values(user_id=user_id, role_id=role_id)
            )


def roles_for_user(conn: Connection, user_id: UUID) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            select(roles)
            .join(user_roles, user_roles.c.role_id == roles.c.id)
            .where(user_roles.c.user_id == user_id)
            .order_by(roles.c.name.asc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def permissions_for_user(conn: Connection, user_id: UUID) -> list[str]:
    rows = (
        conn.execute(
            select(permissions.c.code)
            .join(role_permissions, role_permissions.c.permission_id == permissions.c.id)
            .join(user_roles, user_roles.c.role_id == role_permissions.c.role_id)
            .where(user_roles.c.user_id == user_id)
            .distinct()
        )
        .scalars()
        .all()
    )
    return list(rows)


def list_roles(conn: Connection, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    total = conn.execute(select(func.count()).select_from(roles)).scalar_one()
    rows = (
        conn.execute(
            select(roles)
            .order_by(roles.c.name.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows], total


def get_role(conn: Connection, role_id: UUID) -> dict[str, Any] | None:
    row = conn.execute(select(roles).where(roles.c.id == role_id)).mappings().first()
    return dict(row) if row else None


def create_role(conn: Connection, name: str, description: str) -> UUID:
    now = _utcnow()
    result = conn.execute(
        insert(roles).values(
            name=name, description=description, created_at=now, updated_at=now
        ).returning(roles.c.id)
    )
    return result.scalar_one()


def permissions_for_role(conn: Connection, role_id: UUID) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            select(permissions)
            .join(role_permissions, role_permissions.c.permission_id == permissions.c.id)
            .where(role_permissions.c.role_id == role_id)
            .order_by(permissions.c.code.asc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def users_for_role(conn: Connection, role_id: UUID) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            select(users.c.id, users.c.name)
            .join(user_roles, user_roles.c.user_id == users.c.id)
            .where(user_roles.c.role_id == role_id)
            .order_by(users.c.name.asc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def role_id_by_name(conn: Connection, name: str) -> UUID | None:
    return conn.execute(
        select(roles.c.id).where(roles.c.name == name)
    ).scalar_one_or_none()


def replace_role_permissions(
    conn: Connection, role_id: UUID, permission_ids: list[UUID]
) -> None:
    conn.execute(delete(role_permissions).where(role_permissions.c.role_id == role_id))
    for permission_id in permission_ids:
        conn.execute(
            insert(role_permissions).values(
                role_id=role_id, permission_id=permission_id
            )
        )


def permission_id_by_code(conn: Connection, code: str) -> UUID | None:
    return conn.execute(
        select(permissions.c.id).where(permissions.c.code == code)
    ).scalar_one_or_none()


def ensure_permissions_seeded(conn: Connection) -> None:
    """Insert the full permission catalog and initial role grants if missing."""
    existing = set(
        conn.execute(select(permissions.c.code)).scalars().all()
    )
    now = _utcnow()
    for code in PermissionCode:
        if code.value in existing:
            continue
        module, _, action = code.value.partition(":")
        conn.execute(
            insert(permissions).values(
                code=code.value,
                module=module,
                action=action,
                description="",
                created_at=now,
                updated_at=now,
            )
        )
    for role_name, codes in INITIAL_ROLE_PERMISSIONS.items():
        role_id = role_id_by_name(conn, role_name)
        if role_id is None:
            continue
        current = set(
            conn.execute(
                select(permissions.c.code)
                .join(
                    role_permissions,
                    role_permissions.c.permission_id == permissions.c.id,
                )
                .where(role_permissions.c.role_id == role_id)
            )
            .scalars()
            .all()
        )
        for code in codes:
            if code.value in current:
                continue
            permission_id = permission_id_by_code(conn, code.value)
            if permission_id:
                conn.execute(
                    insert(role_permissions).values(
                        role_id=role_id, permission_id=permission_id
                    )
                )


# --- sessions ---

def create_session(
    conn: Connection, user_id: UUID, token: str, ttl_minutes: int
) -> datetime:
    expires_at = _utcnow() + timedelta(minutes=ttl_minutes)
    conn.execute(
        insert(sessions).values(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=expires_at,
            created_at=_utcnow(),
        )
    )
    return expires_at


def active_session_user_id(conn: Connection, token: str) -> UUID | None:
    """Return the user id for a valid, unexpired, non-revoked session token."""
    row = (
        conn.execute(
            select(sessions.c.user_id, sessions.c.expires_at, sessions.c.revoked_at)
            .where(sessions.c.token_hash == hash_token(token))
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    if row["revoked_at"] is not None:
        return None
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _utcnow():
        return None
    return row["user_id"]


def revoke_session(conn: Connection, token: str) -> bool:
    result = conn.execute(
        update(sessions)
        .where(sessions.c.token_hash == hash_token(token))
        .where(sessions.c.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    return result.rowcount > 0
