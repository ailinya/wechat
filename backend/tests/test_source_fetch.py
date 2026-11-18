"""Unit tests for the collection-source fetch adapter (task 3.4).

Fixtures inject the transport and DNS resolver so no network is used.
"""

from __future__ import annotations

import pytest

from app.adapters import source_fetch

PUBLIC = "93.184.216.34"


def _resolver(*addresses: str):
    return lambda host, port: list(addresses)


def _transport(status: int = 200, body: bytes = b"ok", headers: dict | None = None):
    return lambda url, timeout: (status, headers or {"Content-Type": "text/plain"}, body)


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.validate_url("ftp://example.com/feed")
    assert exc.value.code == "invalid_url_scheme"


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.validate_url("http://user:pass@example.com/feed")
    assert exc.value.code == "invalid_url"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"])
def test_rejects_internal_addresses(address: str) -> None:
    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.validate_url("http://example.com/feed", resolver=_resolver(address))
    assert exc.value.code == "host_not_allowed"


def test_allows_public_address() -> None:
    url = source_fetch.validate_url("http://example.com/feed", resolver=_resolver(PUBLIC))
    assert url == "http://example.com/feed"


def test_host_allowlist_rejects_other_host() -> None:
    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.validate_url(
            "https://other.com/feed", resolver=_resolver(PUBLIC), allowed_hosts=["example.com"]
        )
    assert exc.value.code == "host_not_allowed"


def test_success_fixture_returns_content() -> None:
    result = source_fetch.fetch(
        "https://example.com/feed",
        resolver=_resolver(PUBLIC),
        transport=_transport(200, "中文正文".encode(), {"Content-Type": "application/rss+xml"}),
    )
    assert result.status_code == 200
    assert result.content == "中文正文"
    assert result.content_type == "application/rss+xml"
    assert result.elapsed_ms >= 0


def test_redirect_target_is_revalidated() -> None:
    calls = []

    def transport(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            return 302, {"Location": "http://127.0.0.1/admin"}, b""
        return 200, {}, b"ok"

    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.fetch(
            "https://example.com/feed",
            resolver=_resolver(PUBLIC),
            transport=transport,
        )
    assert exc.value.code == "host_not_allowed"
    assert len(calls) == 1  # never fetched the internal target


def test_redirect_limit_enforced() -> None:
    def transport(url, timeout):
        return 302, {"Location": "https://example.com/next"}, b""

    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.fetch(
            "https://example.com/feed",
            resolver=_resolver(PUBLIC),
            transport=transport,
            max_redirects=1,
        )
    assert exc.value.code == "too_many_redirects"


def test_response_size_limit_enforced() -> None:
    with pytest.raises(source_fetch.FetchError) as exc:
        source_fetch.fetch(
            "https://example.com/feed",
            resolver=_resolver(PUBLIC),
            transport=_transport(200, b"x" * 101),
            max_bytes=100,
        )
    assert exc.value.code == "response_too_large"


def test_timeout_forwarded_to_transport() -> None:
    seen = {}

    def transport(url, timeout):
        seen["timeout"] = timeout
        return 200, {}, b"ok"

    source_fetch.fetch(
        "https://example.com/feed",
        resolver=_resolver(PUBLIC),
        transport=transport,
        timeout_seconds=3,
    )
    assert seen["timeout"] == 3
