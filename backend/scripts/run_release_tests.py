"""Run the full suite with explicit isolated PostgreSQL/Redis/RustFS settings."""
import os
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values


def main():
    root=Path(__file__).resolve().parents[2]
    values=dotenv_values(root/'.acceptance/stack.env')
    if values.get('STACK_NAME')!='wetchat-acceptance':
        raise SystemExit('Prepare the isolated acceptance environment first')
    env={**os.environ,'POSTGRES_PORT':'55437','REDIS_URL':'redis://127.0.0.1:56379/15',
         'RUSTFS_ENDPOINT':'http://127.0.0.1:59000','RUSTFS_PUBLIC_ENDPOINT':'http://127.0.0.1:59000',
         'RUSTFS_ACCESS_KEY':values['RUSTFS_ACCESS_KEY'],'RUSTFS_SECRET_KEY':values['RUSTFS_SECRET_KEY'],
         'RUSTFS_BUCKET':'release-tests','OPENAI_API_KEY':'','OPENAI_BASE_URL':'','MODEL_NAME':'fixture-model',
         'EMBEDDING_MODEL':'fixture-embedding','EMBEDDING_BASE_URL':'https://acceptance.example.test/v1',
         'HTTP_PROXY':'','HTTPS_PROXY':'','ALL_PROXY':'','http_proxy':'','https_proxy':'','all_proxy':'',
         'NO_PROXY':'127.0.0.1,localhost,testserver'}
    from app.config import Settings
    from app.adapters.object_storage import ensure_bucket
    ensure_bucket(Settings(APP_SECRET_KEY='t'*40,RUSTFS_ENDPOINT=env['RUSTFS_ENDPOINT'],RUSTFS_PUBLIC_ENDPOINT=env['RUSTFS_PUBLIC_ENDPOINT'],RUSTFS_ACCESS_KEY=env['RUSTFS_ACCESS_KEY'],RUSTFS_SECRET_KEY=env['RUSTFS_SECRET_KEY'],RUSTFS_BUCKET=env['RUSTFS_BUCKET']))
    return subprocess.call([sys.executable,'scripts/test_article_review.py',*(sys.argv[1:] or ['tests','--tb=short'])],env=env,cwd=root/'backend')


if __name__=='__main__':
    raise SystemExit(main())
