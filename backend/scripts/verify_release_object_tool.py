"""Exercise the shipped object snapshot command with the actual RustFS service."""
import json
from uuid import uuid4
from release_support import ROOT, environment, save
from app.config import Settings
from app.commands.object_snapshot import backup, restore
from app.adapters.object_storage import _client


def main():
    values = environment()
    settings = Settings(APP_SECRET_KEY=values['APP_SECRET_KEY'],RUSTFS_ENDPOINT='http://127.0.0.1:'+values['RUSTFS_API_PORT'],RUSTFS_ACCESS_KEY=values['RUSTFS_ACCESS_KEY'],RUSTFS_SECRET_KEY=values['RUSTFS_SECRET_KEY'],RUSTFS_BUCKET=values['RUSTFS_BUCKET'])
    directory = ROOT/'.acceptance/backups'/('object-command-'+uuid4().hex)
    result = backup(settings,directory)
    assert result['objects'] > 0
    bucket = 'object-tool-'+uuid4().hex[:16]
    assert restore(settings,directory,bucket)['verified']
    try:
        restore(settings,directory,bucket)
        raise AssertionError('Existing bucket was accepted')
    except RuntimeError as exc:
        assert 'already exists' in str(exc)
    manifest = json.loads((directory/'manifest.json').read_text())
    payload = directory/manifest['objects'][0]['file']
    original = payload.read_bytes()
    payload.write_bytes(b'corrupt')
    rejected_bucket = 'object-rejected-'+uuid4().hex[:12]
    try:
        restore(settings,directory,rejected_bucket)
        raise AssertionError('Corrupt payload was accepted')
    except RuntimeError as exc:
        assert 'checksum' in str(exc)
    finally:
        payload.write_bytes(original)
    assert not _client(settings).bucket_exists(rejected_bucket)
    save('object-snapshot-command',{'passed':True,'checks':['backup_actual_objects','restore_readback_sha256','reject_existing_target','reject_corrupt_before_creating_target'],'object_count':result['objects']})


if __name__ == '__main__':
    main()
