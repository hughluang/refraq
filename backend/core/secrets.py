"""Application-level encrypt/decrypt for Connection secrets (ADR 0005)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from backend.core.config import get_settings


class SecretsMasterKeyMissing(RuntimeError):
    """Raised when encrypt/decrypt is attempted without REFRAQ_SECRETS_MASTER_KEY."""


class SecretsDecryptError(RuntimeError):
    """Raised when ciphertext cannot be decrypted with the configured master key."""


def _fernet_from_master_key(master_key: str) -> Fernet:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _require_fernet() -> Fernet:
    settings = get_settings()
    if not settings.refraq_secrets_master_key:
        raise SecretsMasterKeyMissing(
            "REFRAQ_SECRETS_MASTER_KEY is required to encrypt or decrypt secrets"
        )
    return _fernet_from_master_key(settings.refraq_secrets_master_key)


def encrypt_secret(plaintext: str) -> str:
    """Return a Fernet token (url-safe text) for the given plaintext secret."""
    token = _require_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a Fernet token produced by encrypt_secret."""
    try:
        return _require_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretsDecryptError("secret decrypt failed") from exc
