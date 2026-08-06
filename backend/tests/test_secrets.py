"""Unit tests for REFRAQ_SECRETS_MASTER_KEY helper."""

from __future__ import annotations

import os

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.secrets import (  # noqa: E402
    SecretsDecryptError,
    SecretsMasterKeyMissing,
    decrypt_secret,
    encrypt_secret,
)


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-master-key")
    reset_settings_cache()
    token = encrypt_secret("db-password")
    assert token != "db-password"
    assert decrypt_secret(token) == "db-password"


def test_missing_master_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Override env files / process env (delenv alone still loads backend/.env).
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "")
    reset_settings_cache()
    with pytest.raises(SecretsMasterKeyMissing):
        encrypt_secret("x")


def test_wrong_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "key-a")
    reset_settings_cache()
    token = encrypt_secret("secret")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "key-b")
    reset_settings_cache()
    with pytest.raises(SecretsDecryptError):
        decrypt_secret(token)
