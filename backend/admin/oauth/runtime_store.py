"""Unified runtime store for delegated OAuth tokens (rfq_oat_) and single-use JTI replay guards."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from backend.core.config import get_settings
from backend.core.redis_client import get_redis

DELEGATED_TOKEN_PREFIX = "rfq_oat_"
_TOKEN_KEY_PREFIX = "refraq:oauth_token:"
_USER_TOKENS_PREFIX = "refraq:oauth_user_tokens:"
_CLIENT_TOKENS_PREFIX = "refraq:oauth_client_tokens:"
_JTI_KEY_PREFIX = "refraq:oauth_jti:"


def hash_delegated_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_delegated_token() -> tuple[str, str, str]:
    """Return (token_id, plaintext, token_hash)."""
    token_id = f"oat_{secrets.token_hex(6)}"
    plaintext = f"{DELEGATED_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    return token_id, plaintext, hash_delegated_token(plaintext)


@dataclass(frozen=True)
class DelegatedTokenRecord:
    token_id: str
    token_hash: str
    user_id: str
    client_id: str
    provider_id: str
    scopes: tuple[str, ...]
    surfaces: tuple[str, ...]
    issued_at: float
    expires_at: float


class OAuthRuntimeStore(Protocol):
    def issue_token(
        self,
        *,
        user_id: str,
        client_id: str,
        provider_id: str,
        scopes: tuple[str, ...],
        surfaces: tuple[str, ...],
        ttl_sec: int,
    ) -> tuple[DelegatedTokenRecord, str]: ...

    def resolve_token(self, plaintext: str) -> DelegatedTokenRecord | None: ...

    def revoke_for_user(self, user_id: str) -> int: ...

    def revoke_for_client(self, client_id: str) -> int: ...

    def consume_jti_once(
        self,
        namespace: str,
        issuer: str,
        jti: str,
        ttl_sec: int,
    ) -> bool: ...


def _encode_record(record: DelegatedTokenRecord) -> str:
    return json.dumps(
        {
            "token_id": record.token_id,
            "token_hash": record.token_hash,
            "user_id": record.user_id,
            "client_id": record.client_id,
            "provider_id": record.provider_id,
            "scopes": list(record.scopes),
            "surfaces": list(record.surfaces),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
        separators=(",", ":"),
    )


def _decode_record(raw: str) -> DelegatedTokenRecord | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return DelegatedTokenRecord(
            token_id=str(data["token_id"]),
            token_hash=str(data["token_hash"]),
            user_id=str(data["user_id"]),
            client_id=str(data["client_id"]),
            provider_id=str(data["provider_id"]),
            scopes=tuple(str(item) for item in data.get("scopes") or ()),
            surfaces=tuple(str(item) for item in data.get("surfaces") or ()),
            issued_at=float(data["issued_at"]),
            expires_at=float(data["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _jti_key(namespace: str, issuer: str, jti: str) -> str:
    digest = hashlib.sha256(f"{namespace}\x00{issuer}\x00{jti}".encode("utf-8")).hexdigest()
    return f"{_JTI_KEY_PREFIX}{digest}"


class MemoryOAuthRuntimeStore:
    def __init__(self) -> None:
        self._tokens: dict[str, DelegatedTokenRecord] = {}
        self._by_user: dict[str, set[str]] = {}
        self._by_client: dict[str, set[str]] = {}
        self._jtis: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue_token(
        self,
        *,
        user_id: str,
        client_id: str,
        provider_id: str,
        scopes: tuple[str, ...],
        surfaces: tuple[str, ...],
        ttl_sec: int,
    ) -> tuple[DelegatedTokenRecord, str]:
        now = time.time()
        token_id, plaintext, token_hash = generate_delegated_token()
        record = DelegatedTokenRecord(
            token_id=token_id,
            token_hash=token_hash,
            user_id=user_id,
            client_id=client_id,
            provider_id=provider_id,
            scopes=tuple(scopes),
            surfaces=tuple(surfaces),
            issued_at=now,
            expires_at=now + max(int(ttl_sec), 1),
        )
        with self._lock:
            self._tokens[token_hash] = record
            self._by_user.setdefault(user_id, set()).add(token_hash)
            self._by_client.setdefault(client_id, set()).add(token_hash)
        return record, plaintext

    def resolve_token(self, plaintext: str) -> DelegatedTokenRecord | None:
        if not plaintext.startswith(DELEGATED_TOKEN_PREFIX):
            return None
        token_hash = hash_delegated_token(plaintext)
        now = time.time()
        with self._lock:
            record = self._tokens.get(token_hash)
            if record is None:
                return None
            if record.expires_at <= now:
                self._remove_locked(token_hash)
                return None
            return record

    def revoke_for_user(self, user_id: str) -> int:
        with self._lock:
            hashes = list(self._by_user.pop(user_id, ()))
            removed = 0
            for token_hash in hashes:
                if self._remove_locked(token_hash):
                    removed += 1
            return removed

    def revoke_for_client(self, client_id: str) -> int:
        with self._lock:
            hashes = list(self._by_client.pop(client_id, ()))
            removed = 0
            for token_hash in hashes:
                if self._remove_locked(token_hash):
                    removed += 1
            return removed

    def consume_jti_once(
        self,
        namespace: str,
        issuer: str,
        jti: str,
        ttl_sec: int,
    ) -> bool:
        key = _jti_key(namespace, issuer, jti)
        now = time.time()
        with self._lock:
            expired = [k for k, exp in self._jtis.items() if exp <= now]
            for k in expired:
                self._jtis.pop(k, None)
            if key in self._jtis:
                return False
            self._jtis[key] = now + max(int(ttl_sec), 1)
            return True

    def _remove_locked(self, token_hash: str) -> bool:
        record = self._tokens.pop(token_hash, None)
        if record is None:
            return False
        user_set = self._by_user.get(record.user_id)
        if user_set is not None:
            user_set.discard(token_hash)
            if not user_set:
                self._by_user.pop(record.user_id, None)
        client_set = self._by_client.get(record.client_id)
        if client_set is not None:
            client_set.discard(token_hash)
            if not client_set:
                self._by_client.pop(record.client_id, None)
        return True


class RedisOAuthRuntimeStore:
    def issue_token(
        self,
        *,
        user_id: str,
        client_id: str,
        provider_id: str,
        scopes: tuple[str, ...],
        surfaces: tuple[str, ...],
        ttl_sec: int,
    ) -> tuple[DelegatedTokenRecord, str]:
        ttl = max(int(ttl_sec), 1)
        now = time.time()
        token_id, plaintext, token_hash = generate_delegated_token()
        record = DelegatedTokenRecord(
            token_id=token_id,
            token_hash=token_hash,
            user_id=user_id,
            client_id=client_id,
            provider_id=provider_id,
            scopes=tuple(scopes),
            surfaces=tuple(surfaces),
            issued_at=now,
            expires_at=now + ttl,
        )
        r = get_redis()
        pipe = r.pipeline()
        pipe.set(f"{_TOKEN_KEY_PREFIX}{token_hash}", _encode_record(record), ex=ttl)
        user_key = f"{_USER_TOKENS_PREFIX}{user_id}"
        client_key = f"{_CLIENT_TOKENS_PREFIX}{client_id}"
        pipe.sadd(user_key, token_hash)
        pipe.expire(user_key, ttl + 60)
        pipe.sadd(client_key, token_hash)
        pipe.expire(client_key, ttl + 60)
        pipe.execute()
        return record, plaintext

    def resolve_token(self, plaintext: str) -> DelegatedTokenRecord | None:
        if not plaintext.startswith(DELEGATED_TOKEN_PREFIX):
            return None
        token_hash = hash_delegated_token(plaintext)
        raw = get_redis().get(f"{_TOKEN_KEY_PREFIX}{token_hash}")
        if not raw:
            return None
        record = _decode_record(raw)
        if record is None or record.expires_at <= time.time():
            return None
        return record

    def revoke_for_user(self, user_id: str) -> int:
        r = get_redis()
        user_key = f"{_USER_TOKENS_PREFIX}{user_id}"
        hashes = list(r.smembers(user_key) or ())
        if not hashes:
            return 0
        pipe = r.pipeline()
        for token_hash in hashes:
            pipe.delete(f"{_TOKEN_KEY_PREFIX}{token_hash}")
        pipe.delete(user_key)
        pipe.execute()
        return len(hashes)

    def revoke_for_client(self, client_id: str) -> int:
        r = get_redis()
        client_key = f"{_CLIENT_TOKENS_PREFIX}{client_id}"
        hashes = list(r.smembers(client_key) or ())
        if not hashes:
            return 0
        pipe = r.pipeline()
        for token_hash in hashes:
            pipe.delete(f"{_TOKEN_KEY_PREFIX}{token_hash}")
        pipe.delete(client_key)
        pipe.execute()
        return len(hashes)

    def consume_jti_once(
        self,
        namespace: str,
        issuer: str,
        jti: str,
        ttl_sec: int,
    ) -> bool:
        key = _jti_key(namespace, issuer, jti)
        ok = get_redis().set(key, "1", nx=True, ex=max(int(ttl_sec), 1))
        return bool(ok)


_memory: MemoryOAuthRuntimeStore | None = None
_lock = threading.Lock()


@lru_cache
def get_oauth_runtime_store() -> OAuthRuntimeStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryOAuthRuntimeStore()
            return _memory
    return RedisOAuthRuntimeStore()


def reset_oauth_runtime_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_oauth_runtime_store.cache_clear()
