"""Quiesced PostgreSQL/object snapshot restored into a new isolated database/bucket."""
import hashlib
import io
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from uuid import uuid4

from minio import Minio
from sqlalchemy import create_engine, text
from release_support import ROOT, api, client, compose, engine, environment, save, wait_until


def fingerprints(db):
    with db.connect() as conn:
        tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        return {table: dict(conn.execute(text(f'SELECT count(*) AS count,md5(COALESCE(string_agg(md5(to_jsonb(t)::text),\'\' ORDER BY md5(to_jsonb(t)::text)),\'\')) AS checksum FROM "{table}" t')).mappings().one()) for table in tables}


def main():
    values = environment()
    c = client()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6]
    backup = ROOT/'.acceptance/backups'/stamp
    backup.mkdir(parents=True)
    objects = backup/'objects'
    objects.mkdir()
    s3 = Minio('127.0.0.1:'+values['RUSTFS_API_PORT'], access_key=values['RUSTFS_ACCESS_KEY'], secret_key=values['RUSTFS_SECRET_KEY'], secure=False, region='us-east-1')
    source_bucket = values['RUSTFS_BUCKET']
    restore_db = 'wetchat_acceptance_restore_'+uuid4().hex[:8]
    restore_bucket = 'acceptance-restore-'+uuid4().hex[:12]
    services = ['api','worker','beat','dispatcher']
    started = time.monotonic()
    compose('stop', *services)
    try:
        with engine().connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM async_jobs WHERE status='running'")).scalar_one() == 0, 'Wait for active jobs before taking a snapshot'
        before = fingerprints(engine())
        with engine().connect() as conn:
            schema_version=conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        with engine().connect() as conn:
            completed_upload = conn.execute(text('SELECT g.id AS grant_id,s.id AS object_id,s.sha256 FROM upload_grants g JOIN stored_objects s ON s.bucket=g.bucket AND s.object_key=g.object_key WHERE g.completed_at IS NOT NULL ORDER BY g.created_at DESC LIMIT 1')).mappings().first()
            assert completed_upload, 'Browser upload acceptance must run before the restore drill'
        manifest = []
        for index, obj in enumerate(s3.list_objects(source_bucket, recursive=True)):
            stream = s3.get_object(source_bucket, obj.object_name)
            try:
                data = stream.read()
            finally:
                stream.close(); stream.release_conn()
            file = str(index)+'.bin'
            (objects/file).write_bytes(data)
            manifest.append({'key':obj.object_name,'file':file,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content_type':s3.stat_object(source_bucket,obj.object_name).content_type})
        (backup/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        with (backup/'database.dump').open('wb') as output:
            result = subprocess.run(['docker','exec','wetchat-acceptance-postgres-1','pg_dump','-U','wetchat','-d','wetchat_acceptance','-Fc','--no-owner','--no-acl'], stdout=output, stderr=subprocess.PIPE)
        assert result.returncode == 0, 'PostgreSQL backup failed'
        backup_seconds = time.monotonic()-started
    finally:
        compose('start', *services)
    wait_until(lambda:c.get('/ready').status_code == 200)
    base = create_engine(engine().url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    with base.connect() as conn:
        assert not conn.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name':restore_db}).scalar(), 'Existing restore database retained; select a fresh target before rerunning'
        conn.execute(text(f'CREATE DATABASE {restore_db}'))
    restore_started = time.monotonic()
    with (backup/'database.dump').open('rb') as source:
        result = subprocess.run(['docker','exec','-i','wetchat-acceptance-postgres-1','pg_restore','-U','wetchat','-d',restore_db,'--no-owner','--no-acl','--exit-on-error'], stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert result.returncode == 0, 'PostgreSQL restore failed'
    restored = engine(restore_db)
    assert fingerprints(restored) == before, 'Restored row count/content differs'
    s3.make_bucket(restore_bucket)
    for obj in manifest:
        data = (objects/obj['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == obj['sha256']
        s3.put_object(restore_bucket,obj['key'],io.BytesIO(data),len(data),content_type=obj['content_type'])
        stream = s3.get_object(restore_bucket,obj['key'])
        try:
            assert hashlib.sha256(stream.read()).hexdigest() == obj['sha256']
        finally:
            stream.close(); stream.release_conn()
    with restored.begin() as conn:
        conn.execute(text('UPDATE stored_objects SET bucket=:bucket WHERE bucket=:source'), {'bucket':restore_bucket,'source':source_bucket})
        conn.execute(text('UPDATE upload_grants SET bucket=:bucket WHERE bucket=:source'), {'bucket':restore_bucket,'source':source_bucket})
        conn.execute(text('UPDATE upload_grants SET expires_at=LEAST(expires_at,now()) WHERE completed_at IS NULL'))
    # Read the restored article/citation/review/draft chain through the actual API.
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    settings = Settings(APP_SECRET_KEY=values['APP_SECRET_KEY'], DATABASE_URL=restored.url.render_as_string(hide_password=False), REDIS_URL='redis://127.0.0.1:'+values['REDIS_PORT']+'/14', RUSTFS_ENDPOINT='http://127.0.0.1:'+values['RUSTFS_API_PORT'], RUSTFS_ACCESS_KEY=values['RUSTFS_ACCESS_KEY'], RUSTFS_SECRET_KEY=values['RUSTFS_SECRET_KEY'], RUSTFS_BUCKET=restore_bucket)
    record = json.loads((ROOT/'.acceptance/workflow.json').read_text())
    with TestClient(create_app(settings)) as restored_client:
        assert restored_client.post('/api/v1/auth/login',json={'account':'admin','password':values['WETCHAT_ADMIN_PASSWORD']}).status_code == 200
        article = restored_client.get('/api/v1/articles/'+record['article_id']).json()
        assert article['revision_id'] == record['revision_id'] and '100吨' in article['materials'][0]['content_markdown']
        delivery = restored_client.get('/api/v1/wechat-draft-deliveries/'+record['delivery_id']).json()
        assert delivery['status'] == 'manual_published' and delivery['publication_source'] == 'operator'
        headers = {'X-CSRF-Token':restored_client.cookies['wetchat_csrf']}
        replay = restored_client.post('/api/v1/files/upload-grants/'+str(completed_upload['grant_id'])+'/complete',headers=headers,json={'sha256':completed_upload['sha256']})
        assert replay.status_code==200 and replay.json()['id']==str(completed_upload['object_id'])
        download = restored_client.post('/api/v1/files/'+str(completed_upload['object_id'])+'/download-grant',headers=headers)
        assert download.status_code==200
        import httpx
        with httpx.Client(trust_env=False) as transport:
            response = transport.get(download.json()['url'])
            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==completed_upload['sha256']
        from app.adapters.wechat_client import decrypt
        with restored.connect() as conn:
            encrypted = conn.execute(text('SELECT secret_encrypted FROM wechat_accounts WHERE id=:id'),{'id':record['account_id']}).scalar_one()
        assert decrypt(settings,encrypted)=='acceptance-only-not-real-secret'
    save('backup-restore', {'passed':True,'backup_id':stamp,'database_version':schema_version,'table_count':len(before),'objects':[{k:v for k,v in obj.items() if k!='file'} for obj in manifest],'database_sha256':hashlib.sha256((backup/'database.dump').read_bytes()).hexdigest(),'backup_seconds':round(backup_seconds,2),'restore_seconds':round(time.monotonic()-restore_started,2),'checks':['all_table_counts_and_checksums','all_object_sha256','restored_login','article_and_historical_citation','manual_delivery_history','completed_upload_replay_same_object','authenticated_attachment_download','encrypted_account_secret_decrypts'],'restore_metadata_adjustments':['stored_objects_and_upload_grants_bucket_remap','expire_unfinished_upload_grants'],'restore_database':restore_db,'restore_bucket':restore_bucket,'credentials_in_backup':'encrypted database fields; retain APP_SECRET_KEY separately'})


if __name__ == '__main__':
    main()
