"""Backup/restore object payloads; restore always requires a fresh target bucket."""
import argparse
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.object_storage import _client
from app.config import load_settings


def backup(settings, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'manifest.json').exists():
        raise RuntimeError('Snapshot already exists; use a new directory')
    storage = _client(settings)
    objects = []
    for index, obj in enumerate(storage.list_objects(settings.rustfs_bucket, recursive=True)):
        stream = storage.get_object(settings.rustfs_bucket,obj.object_name)
        try:
            data = stream.read()
        finally:
            stream.close(); stream.release_conn()
        file = f'{index:08d}.bin'
        (directory/file).write_bytes(data)
        metadata = storage.stat_object(settings.rustfs_bucket,obj.object_name)
        objects.append({'key':obj.object_name,'file':file,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content_type':metadata.content_type,'version_id':metadata.version_id})
    manifest = {'created_at':datetime.now(timezone.utc).isoformat(),'source_bucket':settings.rustfs_bucket,'objects':objects}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'objects':len(objects),'bytes':sum(row['bytes'] for row in objects)}


def restore(settings, directory, target_bucket):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    storage = _client(settings)
    if storage.bucket_exists(target_bucket):
        raise RuntimeError('Restore target bucket already exists; use a fresh target')
    # Validate the complete snapshot before creating the restore target.
    for row in manifest['objects']:
        file = (directory/row['file']).resolve()
        if file.parent != directory.resolve():
            raise RuntimeError('Invalid snapshot payload path')
        data = file.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise RuntimeError('Snapshot checksum mismatch')
    storage.make_bucket(target_bucket)
    for row in manifest['objects']:
        data = (directory/row['file']).read_bytes()
        storage.put_object(target_bucket,row['key'],io.BytesIO(data),len(data),content_type=row['content_type'])
        stream = storage.get_object(target_bucket,row['key'])
        try:
            if hashlib.sha256(stream.read()).hexdigest() != row['sha256']:
                raise RuntimeError('Restored object checksum mismatch')
        finally:
            stream.close(); stream.release_conn()
    return {'objects':len(manifest['objects']),'target_bucket':target_bucket,'verified':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup','restore'])
    parser.add_argument('--directory',required=True)
    parser.add_argument('--target-bucket')
    args = parser.parse_args()
    settings = load_settings()
    if args.operation == 'restore' and not args.target_bucket:
        parser.error('restore requires --target-bucket')
    result = backup(settings,args.directory) if args.operation == 'backup' else restore(settings,args.directory,args.target_bucket)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
