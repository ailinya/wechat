"""Create (or update) the initial administrator account.

The password has no default: it must be supplied with ``--password`` or the
``WETCHAT_ADMIN_PASSWORD`` environment variable. Only an Argon2id hash is
written to the database. Run migrations first, then:

    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/wetchat \
        WETCHAT_ADMIN_PASSWORD='...' wetchat-create-admin --account admin
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.modules.auth.security import hash_password

ADMIN_ROLE_NAME = "admin"
ADMIN_ROLE_DESCRIPTION = "系统管理员"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required, e.g. "
            "postgresql+psycopg://user:password@host:5432/wetchat"
        )
    return url


def _ensure_admin_role(session: Session) -> object:
    role_id = session.execute(
        text("SELECT id FROM roles WHERE name = :name"),
        {"name": ADMIN_ROLE_NAME},
    ).scalar()
    if role_id is None:
        role_id = session.execute(
            text(
                "INSERT INTO roles (name, description) "
                "VALUES (:name, :description) RETURNING id"
            ),
            {"name": ADMIN_ROLE_NAME, "description": ADMIN_ROLE_DESCRIPTION},
        ).scalar_one()
    return role_id


def create_admin(account: str, name: str, password: str) -> str:
    """Create or update an active admin account and grant the admin role."""
    engine = create_engine(_database_url(), connect_args={"connect_timeout": 10})
    try:
        with Session(engine) as session:
            with session.begin():
                role_id = _ensure_admin_role(session)
                password_hash = hash_password(password)

                user_id = session.execute(
                    text("SELECT id FROM users WHERE account = :account"),
                    {"account": account},
                ).scalar()
                if user_id is None:
                    user_id = session.execute(
                        text(
                            "INSERT INTO users (account, name, status, password_hash) "
                            "VALUES (:account, :name, 'active', :password_hash) "
                            "RETURNING id"
                        ),
                        {
                            "account": account,
                            "name": name,
                            "password_hash": password_hash,
                        },
                    ).scalar_one()
                    action = "created"
                else:
                    session.execute(
                        text(
                            "UPDATE users SET name = :name, password_hash = :password_hash, "
                            "status = 'active', updated_at = now() WHERE id = :id"
                        ),
                        {
                            "name": name,
                            "password_hash": password_hash,
                            "id": user_id,
                        },
                    )
                    action = "updated"

                session.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) "
                        "VALUES (:user_id, :role_id) ON CONFLICT DO NOTHING"
                    ),
                    {"user_id": user_id, "role_id": role_id},
                )
                from app.repositories.auth_repository import ensure_permissions_seeded

                ensure_permissions_seeded(session.connection())
    finally:
        engine.dispose()

    return f"admin account '{account}' {action}; admin role granted"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建或更新初始管理员账号")
    parser.add_argument("--account", default="admin", help="登录账号，默认 admin")
    parser.add_argument("--name", default="系统管理员", help="显示名称")
    parser.add_argument(
        "--password",
        help="登录密码；不提供时读取 WETCHAT_ADMIN_PASSWORD 环境变量",
    )
    args = parser.parse_args(argv)

    password = args.password or os.environ.get("WETCHAT_ADMIN_PASSWORD")
    if not password:
        print(
            "错误：必须通过 --password 或 WETCHAT_ADMIN_PASSWORD 提供密码；"
            "没有默认密码。",
            file=sys.stderr,
        )
        return 2

    if len(password) < 8:
        print("错误：密码长度至少为 8 个字符。", file=sys.stderr)
        return 2

    try:
        result = create_admin(args.account, args.name, password)
    except Exception as exc:  # operational CLI: surface a clear, safe message
        print(f"创建管理员失败：{exc}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
