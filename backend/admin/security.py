"""Password hashing and session id helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PBKDF2_ITERATIONS = 200_000
_PBKDF2_ALGO = "sha256"
_SALT_BYTES = 16
_HASH_BYTES = 32


def hash_password(plain: str) -> str:
    """Return a self-describing PBKDF2 hash for the given plain password."""
    if not plain:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGO, plain.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=_HASH_BYTES
    )
    return f"pbkdf2_{_PBKDF2_ALGO}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time verification of a plain password against a stored hash."""
    if not plain or not stored:
        return False
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if not scheme.startswith("pbkdf2_"):
        return False
    algo = scheme.split("_", 1)[1]
    try:
        iterations_int = int(iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        algo, plain.encode("utf-8"), salt, iterations_int, dklen=len(expected)
    )
    return hmac.compare_digest(candidate, expected)


def new_session_id() -> str:
    return secrets.token_urlsafe(32)
