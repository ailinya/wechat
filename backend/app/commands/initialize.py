"""Migrate and initialize the storage bucket; optionally create the first admin."""
import os

from alembic import command
from alembic.config import Config

from app.adapters.object_storage import ensure_bucket
from app.commands.create_admin import create_admin
from app.config import load_settings


def main():
    command.upgrade(Config('alembic.ini'), 'head')
    settings = load_settings()
    ensure_bucket(settings)
    # No default password, and an ordinary restart never resets an existing admin.
    if os.environ.get('WETCHAT_ADMIN_PASSWORD'):
        from app.database import get_engine
        from sqlalchemy import text
        account = os.environ.get('WETCHAT_ADMIN_ACCOUNT','admin')
        with get_engine(settings).connect() as conn:
            exists = conn.execute(text('SELECT 1 FROM users WHERE account=:account'),{'account':account}).scalar()
        if not exists:
            create_admin(account,'管理员',os.environ['WETCHAT_ADMIN_PASSWORD'])
    print('migration, storage and optional first administrator initialized')


if __name__ == '__main__':
    main()
