"""Run article/review tests in a dedicated local Compose database.

Never reads DATABASE_URL; only the local Compose connection parameters.
"""
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


def main():
    root = Path(__file__).resolve().parents[2]
    values = {**dotenv_values(root / '.env', encoding='utf-8-sig'), **os.environ}
    url = URL.create('postgresql+psycopg', username=values.get('POSTGRES_USER', 'wetchat'),
                     password=values['POSTGRES_PASSWORD'], host='127.0.0.1',
                     port=int(values.get('POSTGRES_PORT', 5432)), database='postgres')
    engine = create_engine(url, isolation_level='AUTOCOMMIT')
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname='wetchat_phase06_test'")).scalar()
        if not exists:
            conn.execute(text('CREATE DATABASE wetchat_phase06_test'))
    engine.dispose()
    env = {**os.environ, 'TEST_DATABASE_URL': url.set(database='wetchat_phase06_test').render_as_string(hide_password=False)}
    files = sys.argv[1:] or ['tests/test_article_contract.py', 'tests/test_article_review.py']
    return subprocess.call([sys.executable, '-m', 'pytest', *files, '-q'], env=env, cwd=root / 'backend')


if __name__ == '__main__':
    raise SystemExit(main())
