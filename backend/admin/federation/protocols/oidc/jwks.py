"""JWKS fetch with TTL cache and unknown-kid cooldown. Do not use PyJWKClient."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKSet

from backend.admin.federation.errors import SsoAssertionRejected, SsoProviderUnavailable

JWKS_TTL_SEC = 300.0
UNKNOWN_KID_COOLDOWN_SEC = 30.0
JWKS_TIMEOUT_SEC = 8.0
ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


def permitted_signing_algs(advertised: tuple[str, ...]) -> tuple[str, ...]:
    allowed = tuple(alg for alg in advertised if alg in ALLOWED_ALGS)
    if not allowed:
        raise SsoAssertionRejected("ID token signing algorithms are not allowed")
    return allowed


_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_kid_cooldown: dict[str, float] = {}


def reset_jwks_cache() -> None:
    with _lock:
        _cache.clear()
        _kid_cooldown.clear()


def _fetch(jwks_uri: str) -> dict[str, Any]:
    try:
        response = httpx.get(jwks_uri, timeout=JWKS_TIMEOUT_SEC)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SsoProviderUnavailable() from exc
    data = response.json()
    if not isinstance(data, dict) or "keys" not in data:
        raise SsoAssertionRejected("JWKS document is invalid")
    return data


def _cached(jwks_uri: str, *, force: bool) -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(jwks_uri)
        if not force and hit is not None and hit[0] > now:
            return hit[1]
    document = _fetch(jwks_uri)
    with _lock:
        _cache[jwks_uri] = (now + JWKS_TTL_SEC, document)
    return document


def signing_key(jwks_uri: str, kid: str | None, alg: str) -> Any:
    if alg not in ALLOWED_ALGS:
        raise SsoAssertionRejected("ID token algorithm is not allowed")
    document = _cached(jwks_uri, force=False)
    key = _find_key(document, kid)
    if key is not None:
        return key
    now = time.monotonic()
    cooldown_key = f"{jwks_uri}:{kid or ''}"
    with _lock:
        until = _kid_cooldown.get(cooldown_key, 0.0)
        if until > now:
            raise SsoAssertionRejected("ID token signing key is unknown")
        _kid_cooldown[cooldown_key] = now + UNKNOWN_KID_COOLDOWN_SEC
    document = _cached(jwks_uri, force=True)
    key = _find_key(document, kid)
    if key is None:
        raise SsoAssertionRejected("ID token signing key is unknown")
    return key


def _find_key(document: dict[str, Any], kid: str | None) -> Any | None:
    try:
        jwks = PyJWKSet.from_dict(document)
    except Exception as exc:
        raise SsoAssertionRejected("JWKS document is invalid") from exc
    if kid:
        try:
            return jwks[kid].key
        except KeyError:
            return None
    keys = getattr(jwks, "keys", None)
    if not keys:
        return None
    if len(keys) == 1:
        return keys[0].key
    return None
