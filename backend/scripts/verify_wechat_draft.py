"""One private synthetic draft, with durable no-resend checkpoints. Never publishes."""
import argparse
import hashlib
import json
import secrets
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.wechat_client import WechatClient, WechatError, encrypt
from app.config import Settings
from app.credentials import resolve_setting, resolve_credential

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'doc/development/wechat-draft-live-evidence.json'
SAMPLE = ROOT / 'doc/development/wechat-draft-sample.json'


def save(value):
    EVIDENCE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def cover_png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    width, height = 900, 383
    rows = b''.join(b'\x00' + bytes((225, 235, 245)) * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-test-draft', action='store_true', help='Explicitly create the committed synthetic sample once')
    args = parser.parse_args()
    appid, secret = resolve_setting('WECHAT_APP_ID'), resolve_credential('WECHAT_APP_SECRET')
    if not appid or not secret:
        raise SystemExit('未配置真实公众号凭据')
    settings = Settings(APP_SECRET_KEY=secrets.token_urlsafe(40))
    client = WechatClient({'app_id': appid, 'secret_encrypted': encrypt(settings, secret)}, settings)
    fingerprint = hashlib.sha256(appid.encode()).hexdigest()[:12]
    content = json.loads(SAMPLE.read_text(encoding='utf-8'))
    signature = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
    previous = json.loads(EVIDENCE.read_text(encoding='utf-8')) if EVIDENCE.exists() else None
    if previous and (previous.get('appid_fingerprint') != fingerprint or previous.get('sample_sha256') != signature):
        raise SystemExit('既有证据对应其他账号或样例，拒绝自动重写')
    evidence = previous or {'checked_at': datetime.now(timezone.utc).isoformat(), 'appid_fingerprint': fingerprint, 'sample_sha256': signature, 'title': content['title'], 'state': 'prepared', 'real_publish_executed': False}
    try:
        if evidence['state'] == 'prepared':
            if not args.write_test_draft:
                print('样例已准备；显式指定 --write-test-draft 才会上传测试封面并创建私有草稿')
                return
            evidence['state'] = 'cover_upload_started'
            save(evidence)
            evidence['cover_media_id'] = client.upload(cover_png(), 'image/png', cover=True)
            evidence['state'] = 'cover_uploaded'
            save(evidence)
        if evidence['state'] == 'cover_uploaded':
            if not args.write_test_draft:
                print('已有测试封面，尚未写入草稿')
                return
            content['thumb_media_id'] = evidence['cover_media_id']
            evidence['state'] = 'draft_write_started'
            save(evidence)
            evidence['draft_media_id'] = client.draft(content)
            evidence['state'] = 'draft_created'
            save(evidence)
        if evidence.get('draft_media_id'):
            result = client.call('/cgi-bin/draft/get', {'media_id': evidence['draft_media_id']})
            articles = result.get('news_item') or []
            evidence['readback_matches'] = len(articles) == 1 and articles[0].get('title') == content['title'] and '这是一份接口验证草稿' in articles[0].get('content', '') and articles[0].get('thumb_media_id') == evidence['cover_media_id']
            evidence['state'] = 'verified' if evidence['readback_matches'] else 'readback_mismatch'
            save(evidence)
        else:
            print('未取得草稿标识；保留检查点，不能自动重发。请到微信后台核对。')
    except WechatError as exc:
        evidence.update(error_code=exc.code, message=exc.message)
        if evidence['state'] == 'draft_write_started':
            evidence['state'] = 'unknown' if exc.uncertain else 'draft_write_denied'
        elif evidence['state'] == 'cover_upload_started':
            evidence['state'] = 'cover_upload_failed'
        save(evidence)
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
