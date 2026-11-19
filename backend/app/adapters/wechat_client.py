"""Bounded direct WeChat calls. Publication submission is never retried."""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken


class WechatError(Exception):
    def __init__(self, code, message='微信接口调用失败', *, uncertain=False):
        self.code, self.message, self.uncertain = code, message, uncertain
        super().__init__(message)


def cipher(settings):
    key = hashlib.sha256(settings.secret_key.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(settings, value):
    return cipher(settings).encrypt(value.encode()).decode()


def decrypt(settings, value):
    try:
        return cipher(settings).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise WechatError('credential_unreadable', '凭据无法解密，请重新录入') from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_transport(path, payload, token=None, upload=None):
    query = {'access_token': token} if token else {}
    if path == '/cgi-bin/material/add_material':
        query['type'] = 'image'
    url = 'https://api.weixin.qq.com' + path + ('?' + urlencode(query) if query else '')
    headers = {'Accept': 'application/json'}
    if upload:
        boundary = 'wetchat' + uuid4().hex
        data, content_type = upload
        filename = 'image.png' if content_type == 'image/png' else 'image.jpg'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode() + data + f'\r\n--{boundary}--\r\n'.encode())
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    else:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers['Content-Type'] = 'application/json; charset=utf-8'
    try:
        with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers, method='POST'), timeout=20) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        raise WechatError('wechat_unreachable', '微信响应不可用，请检查网络和接口配置', uncertain=path in ('/cgi-bin/freepublish/submit', '/cgi-bin/draft/add')) from None


class WechatClient:
    def __init__(self, account, settings, transport=None):
        self.account, self.settings = account, settings
        self.transport = transport or http_transport
        self._token = None
        self.expires_in = 0
        self.token_expires_at = None
        expires = account.get('token_expires_at')
        if account.get('token_encrypted') and expires:
            remaining = int((expires - datetime.now(timezone.utc)).total_seconds())
            if remaining > 60:
                self._token = decrypt(settings, account['token_encrypted'])
                self.expires_in = remaining
                self.token_expires_at = expires

    def call(self, path, payload, *, authenticated=True, upload=None):
        value = self.transport(path, payload, self.token() if authenticated else None, upload)
        code = value.get('errcode', 0)
        if code:
            if code in (40001, 40013, 40014, 40125, 42001):
                message = '公众号凭据无效或已失效，请重新接入'
            elif code == 40164:
                message = '微信 API IP 白名单未包含当前服务器'
            elif code in (48001, 48004, 48002):
                message = '公众号无此接口权限或接口已停用'
            elif code in (45009, 45011):
                message = '微信接口调用额度不足'
            else:
                message = f'微信接口拒绝请求（错误码 {int(code)}）'
            raise WechatError(f'wechat_{int(code)}', message)
        return value

    def token(self):
        if self._token and self.token_expires_at and self.token_expires_at > datetime.now(timezone.utc) + timedelta(seconds=30):
            return self._token
        result = self.call('/cgi-bin/stable_token', {'grant_type': 'client_credential', 'appid': self.account['app_id'], 'secret': decrypt(self.settings, self.account['secret_encrypted']), 'force_refresh': False}, authenticated=False)
        token = result.get('access_token')
        if not isinstance(token, str) or not token or not isinstance(result.get('expires_in'), int) or result['expires_in'] <= 0:
            raise WechatError('invalid_wechat_response', '微信未返回有效凭据')
        self._token, self.expires_in = token, result['expires_in']
        self.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.expires_in)
        return token

    def capabilities(self):
        self.token()
        capabilities = {}
        probes = {'materials': ('/cgi-bin/material/batchget_material', {'type': 'news', 'offset': 0, 'count': 1}), 'drafts': ('/cgi-bin/draft/batchget', {'offset': 0, 'count': 1, 'no_content': 1}), 'published_read': ('/cgi-bin/freepublish/batchget', {'offset': 0, 'count': 1, 'no_content': 1})}
        for name, (path, payload) in probes.items():
            try:
                self.call(path, payload)
                capabilities[name] = {'available': True, 'reason': '只读接口检测通过'}
            except WechatError as exc:
                capabilities[name] = {'available': False, 'reason': exc.message}
                if exc.code in ('wechat_40001', 'wechat_40014', 'wechat_42001'):
                    raise
        allowed = self.account.get('publish_permission_confirmed') and capabilities['drafts']['available'] and capabilities['published_read']['available']
        capabilities['publish'] = {'available': bool(allowed), 'reason': '运营已确认后台发布权限，且草稿/发布读取检测通过；执行仍受微信权限校验' if allowed else '需运营确认微信后台发布接口权限，且草稿与发布读取检测通过'}
        return capabilities

    def news(self, offset):
        return self.call('/cgi-bin/material/batchget_material', {'type': 'news', 'offset': offset, 'count': 20})

    def upload(self, data, content_type, *, cover=False):
        if content_type not in ('image/png', 'image/jpeg') or len(data) > (10 * 1024 * 1024 if cover else 1024 * 1024):
            raise WechatError('unsupported_publish_image', '微信发布图片须为 PNG/JPEG；正文图片须小于 1MB')
        result = self.call('/cgi-bin/material/add_material' if cover else '/cgi-bin/media/uploadimg', {}, upload=(data, content_type))
        key = 'media_id' if cover else 'url'
        if not isinstance(result.get(key), str) or not result[key]:
            raise WechatError('invalid_wechat_response', '微信未返回图片标识')
        return result[key]

    def draft(self, content):
        result = self.call('/cgi-bin/draft/add', {'articles': [content]})
        if not isinstance(result.get('media_id'), str) or not result['media_id']:
            raise WechatError('invalid_wechat_response', '微信未返回草稿标识', uncertain=True)
        return result['media_id']

    def drafts(self, offset=0):
        return self.call('/cgi-bin/draft/batchget', {'offset': offset, 'count': 20, 'no_content': 0})

    def publish(self, media_id):
        result = self.call('/cgi-bin/freepublish/submit', {'media_id': media_id})
        if not result.get('publish_id'):
            raise WechatError('invalid_wechat_response', '发布提交响应缺少标识，须核对', uncertain=True)
        return str(result['publish_id'])

    def query(self, publish_id):
        return self.call('/cgi-bin/freepublish/get', {'publish_id': publish_id})
