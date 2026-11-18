"""First collection-source adapter: bounded HTTP fetch with SSRF guards (task 3.4).

The transport and DNS resolver are injectable so fixtures are reproducible
without network access. Production uses the default urllib transport, which
never auto-follows redirects: every hop is re-validated before it is fetched.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from app.modules.collection.search_policy import normalize_url

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_BYTES = 2_097_152  # 2 MiB
DEFAULT_MAX_REDIRECTS = 2
USER_AGENT = "wetchat-collector/1.0"

Transport = Callable[[str, int], tuple[int, dict[str, str], bytes]]
Resolver = Callable[[str, int | None], list[str]]


class FetchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class FetchResult:
    final_url: str
    status_code: int
    content: str
    content_type: str
    elapsed_ms: int


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _default_resolver(host: str, port: int | None) -> list[str]:
    infos = socket.getaddrinfo(host, port or 0, proto=socket.IPPROTO_TCP)
    return list({info[4][0] for info in infos})


def validate_url(
    url: str,
    *,
    allowed_hosts: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    resolver: Resolver | None = None,
) -> str:
    """Validate scheme, credentials, host allowlist and resolved IPs."""
    resolver = resolver or _default_resolver
    if allowed_domains:
        try:
            normalize_url(url, allowed_domains)
        except ValueError:
            raise FetchError("host_not_allowed", "来源地址不在允许的网站范围内") from None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError("invalid_url_scheme", "仅允许 http/https 来源地址")
    if parsed.username or parsed.password:
        raise FetchError("invalid_url", "来源地址不得包含用户名或密码")
    host = parsed.hostname
    if not host:
        raise FetchError("invalid_url", "来源地址缺少主机名")
    normalized = host.lower().rstrip(".")
    if allowed_hosts is not None and normalized not in {h.lower().rstrip(".") for h in allowed_hosts}:
        raise FetchError("host_not_allowed", "来源主机不在允许范围内")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses: list[str] = []
    # An IP-literal host is checked directly, independent of DNS (which may be
    # stubbed or misconfigured). Bracketed IPv6 literals come without brackets.
    try:
        addresses.append(str(ipaddress.ip_address(host.strip("[]"))))
    except ValueError:
        pass
    try:
        addresses.extend(resolver(host, port))
    except (socket.gaierror, OSError) as exc:
        raise FetchError("dns_failure", "来源主机无法解析") from exc
    if not addresses:
        raise FetchError("dns_failure", "来源主机无可用地址")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise FetchError("dns_failure", "来源主机解析出非法地址") from exc
        if _is_blocked(ip):
            raise FetchError("host_not_allowed", "不允许访问内网或保留地址")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


def _default_transport(url: str, timeout_seconds: int) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.status, dict(response.headers), response.read(DEFAULT_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # 3xx is returned to the fetch loop, which re-validates the target.
        return exc.code, dict(exc.headers), b""


def fetch(
    url: str,
    *,
    transport: Transport | None = None,
    resolver: Resolver | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_domains: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> FetchResult:
    """Fetch a source URL with range/redirect/timeout/size limits."""
    transport = transport or _default_transport
    started = time.monotonic()
    current = validate_url(url, allowed_hosts=allowed_hosts, allowed_domains=allowed_domains, resolver=resolver)
    for _ in range(max_redirects + 1):
        try:
            status, headers, body = transport(current, timeout_seconds)
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError("fetch_failed", "来源连接失败") from exc
        if status in (301, 302, 303, 307, 308):
            location = next((v for k, v in headers.items() if k.lower() == "location"), None)
            if not location:
                raise FetchError("redirect_without_location", "重定向缺少目标地址")
            current = validate_url(
                urllib.parse.urljoin(current, location),
                allowed_hosts=allowed_hosts,
                allowed_domains=allowed_domains,
                resolver=resolver,
            )
            continue
        if len(body) > max_bytes:
            raise FetchError("response_too_large", "响应体超过允许大小")
        content_type = next(
            (v for k, v in headers.items() if k.lower() == "content-type"), ""
        ).split(";", 1)[0].strip()
        encoding = "utf-8"
        for header_key, header_value in headers.items():
            if header_key.lower() == "content-type" and "charset=" in header_value.lower():
                encoding = header_value.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            content = body.decode(encoding, errors="replace")
        except LookupError:
            content = body.decode("utf-8", errors="replace")
        return FetchResult(
            final_url=current,
            status_code=status,
            content=content,
            content_type=content_type,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    raise FetchError("too_many_redirects", "重定向次数超过允许上限")
