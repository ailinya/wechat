"""Password hashing and session/CSRF token helpers.

Argon2id is used with library-managed random salts. Only the encoded hash is
stored in the database; no plaintext password is ever persisted or logged.
Session tokens are random bearer values; only their SHA-256 digest is stored,
so a leaked database row cannot be replayed as a valid cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an Argon2id encoded hash suitable for the ``password_hash`` column."""
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password against an Argon2id hash without raising on bad input."""
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_session_token() -> str:
    """Return a URL-safe random session token (the value put in the cookie)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Digest stored in the sessions table; never store the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def tokens_equal(left: str | None, right: str | None) -> bool:
    """Constant-time comparison for tokens; both must be non-empty."""
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)
