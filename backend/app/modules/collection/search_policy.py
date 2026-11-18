"""Deterministic query and URL rules shared by discovery and fetching."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


def normalize_domain(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("非法网站域名") from exc
    if len(host) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
        for part in host.split(".")
    ):
        raise ValueError("网站范围只能填写域名，不包含协议、路径或通配符")
    return host


def domain_matches(host: str, domains: list[str]) -> bool:
    host = normalize_domain(host)
    return any(host == domain or host.endswith("." + domain) for domain in map(normalize_domain, domains))


def normalize_url(value: str, domains: list[str] | None = None) -> str:
    if len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError("invalid_url")
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("invalid_url")
        host = parsed.hostname.lower().rstrip(".")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = normalize_domain(host)
            if host == "localhost" or host.endswith((".localhost", ".local")):
                raise ValueError("host_not_allowed")
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError("host_not_allowed")
        if domains and not domain_matches(host, domains):
            raise ValueError("domain_out_of_scope")
        port = parsed.port
        if port == 0:
            raise ValueError("invalid_url")
        authority = f"[{host}]" if ":" in host else host
        if port and (parsed.scheme, port) not in (("http", 80), ("https", 443)):
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
    except ValueError as exc:
        code = str(exc)
        raise ValueError(code if code in ("host_not_allowed", "domain_out_of_scope") else "invalid_url") from None


def build_query(topic: str, keywords: list[str]) -> str:
    parts = [" ".join(unicodedata.normalize("NFKC", item).split()) for item in [topic, *keywords]]
    if not parts[0]:
        raise ValueError("主题不能为空")
    unique: dict[str, str] = {}
    for part in parts:
        if part:
            unique.setdefault(part.casefold(), part)
    query = " ".join(unique.values())
    if len(query) > 400:
        raise ValueError("搜索词超过提供方 400 字符限制")
    return query
