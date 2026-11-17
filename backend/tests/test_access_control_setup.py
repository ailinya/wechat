"""Tests for the access-control database setup helpers."""

import pytest
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.modules.auth.security import hash_password


def test_hash_password_is_argon2id_and_verifies() -> None:
    password = "a-strong-password"
    hashed = hash_password(password)

    assert hashed.startswith("$argon2id$")
    assert password not in hashed
    assert PasswordHasher().verify(hashed, password)


def test_hash_password_rejects_wrong_password() -> None:
    hashed = hash_password("the-right-password")
    with pytest.raises(VerifyMismatchError):
        PasswordHasher().verify(hashed, "a-different-password")


def test_hash_password_uses_random_salt() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_create_admin_requires_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WETCHAT_ADMIN_PASSWORD", raising=False)
    from app.commands.create_admin import main

    result = main([])
    assert result == 2
