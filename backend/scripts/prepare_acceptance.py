"""Create a fresh ignored environment for an isolated release acceptance stack."""
import secrets
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    folder = root/'.acceptance'
    target = folder/'stack.env'
    if target.exists():
        print('Existing isolated environment preserved: .acceptance/stack.env')
        return
    folder.mkdir(exist_ok=True)
    for name in ['postgres','rustfs']:
        (folder/'data'/name).mkdir(parents=True,exist_ok=True)
    password, appkey, access, storage, admin = (secrets.token_hex(24) for _ in range(5))
    values = {
        'STACK_NAME':'wetchat-acceptance','APP_IMAGE':'wetchat-api:acceptance','APP_TARGET':'acceptance','WEB_IMAGE':'wetchat-web:acceptance',
        'APP_ENV_FILE':target.as_posix(),'ACCEPTANCE_DATA_ROOT':(folder/'data').as_posix(),
        'POSTGRES_DB':'wetchat_acceptance','POSTGRES_PASSWORD':password,'POSTGRES_PORT':'55439',
        'REDIS_PORT':'56379','RUSTFS_API_PORT':'59000','RUSTFS_CONSOLE_PORT':'59001','API_PORT':'58019','WEB_PORT':'55179',
        'DATABASE_URL':f'postgresql+psycopg://wetchat:{password}@postgres:5432/wetchat_acceptance',
        'APP_SECRET_KEY':appkey,'APP_ENV':'test','APP_LOG_LEVEL':'INFO','ACCEPTANCE_FIXTURE':'1',
        'ASGI_APP':'acceptance.api:app','CELERY_APP':'acceptance.worker:celery_app',
        'REDIS_URL':'redis://redis:6379/0','RUSTFS_ENDPOINT':'http://rustfs:9000','RUSTFS_PUBLIC_ENDPOINT':'http://127.0.0.1:59000',
        'RUSTFS_CORS_ALLOWED_ORIGINS':'http://127.0.0.1:55179',
        'RUSTFS_ACCESS_KEY':access,'RUSTFS_SECRET_KEY':storage,'RUSTFS_BUCKET':'attachments',
        'SESSION_COOKIE_SECURE':'false','WETCHAT_ADMIN_PASSWORD':admin,
        'JOB_RETRY_BACKOFF_SECONDS':'1','JOB_STALE_TIMEOUT_MINUTES':'2',
        'EMBEDDING_MODEL':'acceptance-fixture','EMBEDDING_BASE_URL':'https://acceptance.example.test/v1','EMBEDDING_DIMENSION':'1024',
        'OPENAI_API_KEY':'','MODEL_NAME':'acceptance-fixture','OPENAI_BASE_URL':'',
    }
    target.write_text('\n'.join(f'{key}={value}' for key,value in values.items())+'\n',encoding='utf-8')
    print('Created ignored .acceptance/stack.env; no real credentials copied or printed')


if __name__=='__main__':
    main()
