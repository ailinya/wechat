"""Read-only live acceptance. Never creates drafts or publishes content."""
import hashlib
import json
import ipaddress
import re
from datetime import datetime, timezone
from pathlib import Path

from app.adapters.wechat_client import WechatClient, WechatError, encrypt, http_transport
from app.config import Settings
from app.credentials import resolve_setting, resolve_credential


def main():
    appid = resolve_setting('WECHAT_APP_ID')
    secret = resolve_credential('WECHAT_APP_SECRET')
    checked_at = datetime.now(timezone.utc).isoformat()
    if not appid or not secret:
        evidence = {'checked_at': checked_at, 'state': 'blocked', 'reason': '未配置真实 WECHAT_APP_ID/WECHAT_APP_SECRET', 'real_publish_executed': False}
    else:
        # Temporary in-memory key; no credentials/tokens are written to evidence.
        import secrets
        settings = Settings(APP_SECRET_KEY=secrets.token_urlsafe(40))
        row = {'app_id': appid, 'secret_encrypted': encrypt(settings, secret), 'publish_permission_confirmed': False}
        observed = {}
        def diagnostic_transport(path, payload, token=None, upload=None):
            value = http_transport(path, payload, token, upload)
            if value.get('errcode') == 40164:
                match = re.search(r'invalid ip\s+([^,\s]+)', str(value.get('errmsg', '')), re.IGNORECASE)
                if match:
                    try:
                        observed['observed_egress_ip'] = str(ipaddress.ip_address(match.group(1).strip('[]')))
                    except ValueError:
                        pass
            return value
        try:
            capabilities = WechatClient(row, settings, transport=diagnostic_transport).capabilities()
            evidence = {'checked_at': checked_at, 'state': 'connected', 'appid_fingerprint': hashlib.sha256(appid.encode()).hexdigest()[:12], 'capabilities': capabilities, 'real_publish_executed': False}
        except WechatError as exc:
            evidence = {'checked_at': checked_at, 'state': 'failed', 'error_code': exc.code, 'message': exc.message, **observed, 'real_publish_executed': False}
    output = Path(__file__).resolve().parents[2] / 'doc/development/wechat-live-evidence.json'
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
