"""Short-lived one-time OIDC handoff state (memory or Redis)."""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from backend.core.config import get_settings
from backend.core.redis_client import get_redis

HANDOFF_KEY_PREFIX = "refraq:sso_handoff:"
HANDOFF_TTL_SECONDS = 300
HANDOFF_COOKIE_NAME = "refraq_sso"


@dataclass(frozen=True)
class Handoff:
    provider_id: str
    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    return_to: str
    expires_at: float


class HandoffStore(Protocol):
    def put(self, value: Handoff, ttl: int) -> None: ...

    def pop(self, state: str) -> Handoff | None: ...


class MemoryHandoffStore:
    def __init__(self) -> None:
        self._values: dict[str, Handoff] = {}
        self._lock = threading.Lock()

    def put(self, value: Handoff, ttl: int) -> None:
        with self._lock:
            self._values[value.state] = value

    def pop(self, state: str) -> Handoff | None:
        with self._lock:
            value = self._values.pop(state, None)
            if value is None or value.expires_at <= time.time():
                return None
            return value


def _payload(value: Handoff) -> str:
    return json.dumps(
        {
            "provider_id": value.provider_id,
            "nonce": value.nonce,
            "verifier": value.verifier,
            "redirect_uri": value.redirect_uri,
            "return_to": value.return_to,
            "expires_at": value.expires_at,
        },
        separators=(",", ":"),
    )


def _from_payload(state: str, raw: str) -> Handoff | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Handoff(
            provider_id=str(data["provider_id"]),
            state=state,
            nonce=str(data["nonce"]),
            verifier=str(data["verifier"]),
            redirect_uri=str(data["redirect_uri"]),
            return_to=str(data["return_to"]),
            expires_at=float(data["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


class RedisHandoffStore:
    def put(self, value: Handoff, ttl: int) -> None:
        get_redis().set(HANDOFF_KEY_PREFIX + value.state, _payload(value), ex=max(ttl, 1))

    def pop(self, state: str) -> Handoff | None:
        key = HANDOFF_KEY_PREFIX + state
        client = get_redis()
        raw = client.getdel(key) if hasattr(client, "getdel") else None
        if raw is None and not hasattr(client, "getdel"):
            raw = client.get(key)
            if raw is not None:
                client.delete(key)
        if not raw:
            return None
        value = _from_payload(state, str(raw))
        if value is None or value.expires_at <= time.time():
            return None
        return value


_memory: MemoryHandoffStore | None = None
_lock = threading.Lock()


@lru_cache
def get_handoff_store() -> HandoffStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryHandoffStore()
            return _memory
    return RedisHandoffStore()


def new_handoff(
    provider_id: str,
    redirect_uri: str,
    return_to: str,
    ttl: int = HANDOFF_TTL_SECONDS,
) -> Handoff:
    value = Handoff(
        provider_id=provider_id,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(24),
        verifier=secrets.token_urlsafe(48),
        redirect_uri=redirect_uri,
        return_to=return_to,
        expires_at=time.time() + ttl,
    )
    get_handoff_store().put(value, ttl)
    return value


def reset_handoff_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_handoff_store.cache_clear()
