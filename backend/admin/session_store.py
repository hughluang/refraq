"""Session repository ports and adapters (memory + Redis)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from backend.admin.security import new_session_id
from backend.core.config import get_settings
from backend.core.redis_client import get_redis


SESSION_KEY_PREFIX = "refraq:session:"
USER_SESSIONS_KEY_PREFIX = "refraq:user_sessions:"


@dataclass
class _SessionEntry:
    user_id: str
    created_at: float
    absolute_expires_at: float
    idle_seconds: int
    last_activity: float


class SessionStore(Protocol):
    def create(
        self,
        user_id: str,
        ttl_seconds: int,
        idle_seconds: int,
    ) -> str: ...

    def get(self, session_id: str) -> str | None: ...

    def delete(self, session_id: str) -> None: ...
    def delete_by_user_id(self, user_id: str) -> None: ...

    def delete_other_sessions(self, user_id: str, keep_session_id: str) -> None: ...


def _new_entry(
    user_id: str,
    ttl_seconds: int,
    idle_seconds: int,
    now: float,
) -> _SessionEntry:
    return _SessionEntry(
        user_id=user_id,
        created_at=now,
        absolute_expires_at=now + ttl_seconds,
        idle_seconds=int(idle_seconds),
        last_activity=now,
    )


def _is_expired(entry: _SessionEntry, now: float) -> bool:
    if entry.absolute_expires_at <= now:
        return True
    return entry.last_activity + entry.idle_seconds <= now


def _next_ttl_seconds(entry: _SessionEntry, now: float) -> int:
    """Redis EX for a still-valid dual-clock session. Absolute remaining wins."""
    remaining = min(float(entry.idle_seconds), entry.absolute_expires_at - now)
    return max(int(remaining), 1)


def _encode(entry: _SessionEntry) -> str:
    return json.dumps(
        {
            "user_id": entry.user_id,
            "created_at": entry.created_at,
            "absolute_expires_at": entry.absolute_expires_at,
            "idle_seconds": entry.idle_seconds,
            "last_activity": entry.last_activity,
        },
        separators=(",", ":"),
    )


def _user_id_from_stored(raw: str) -> str | None:
    if not raw.startswith("{"):
        return raw or None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    user_id = data.get("user_id") if isinstance(data, dict) else None
    if isinstance(user_id, str) and user_id:
        return user_id
    return None


def _parse_stored(raw: str) -> _SessionEntry | None:
    """Return a dual-clock record, or None when the payload is not JSON."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return None
    try:
        return _SessionEntry(
            user_id=user_id,
            created_at=float(data["created_at"]),
            absolute_expires_at=float(data["absolute_expires_at"]),
            idle_seconds=int(data["idle_seconds"]),
            last_activity=float(data["last_activity"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


class MemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()

    def create(
        self,
        user_id: str,
        ttl_seconds: int,
        idle_seconds: int,
    ) -> str:
        session_id = new_session_id()
        entry = _new_entry(user_id, ttl_seconds, idle_seconds, time.time())
        with self._lock:
            self._purge_expired_locked()
            self._sessions[session_id] = entry
        return session_id

    def get(self, session_id: str) -> str | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            if _is_expired(entry, now):
                self._sessions.pop(session_id, None)
                return None
            entry.last_activity = now
            return entry.user_id

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)

    def delete_by_user_id(self, user_id: str) -> None:
        if not user_id:
            return
        with self._lock:
            to_delete = [
                sid for sid, entry in self._sessions.items() if entry.user_id == user_id
            ]
            for sid in to_delete:
                self._sessions.pop(sid, None)

    def delete_other_sessions(self, user_id: str, keep_session_id: str) -> None:
        if not user_id:
            return
        with self._lock:
            to_delete = [
                sid
                for sid, entry in self._sessions.items()
                if entry.user_id == user_id and sid != keep_session_id
            ]
            for sid in to_delete:
                self._sessions.pop(sid, None)

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [
            sid for sid, entry in self._sessions.items() if _is_expired(entry, now)
        ]
        for sid in expired:
            self._sessions.pop(sid, None)


class RedisSessionStore:
    def create(
        self,
        user_id: str,
        ttl_seconds: int,
        idle_seconds: int,
    ) -> str:
        session_id = new_session_id()
        now = time.time()
        entry = _new_entry(user_id, ttl_seconds, idle_seconds, now)
        client = get_redis()
        pipe = client.pipeline()
        pipe.set(
            f"{SESSION_KEY_PREFIX}{session_id}",
            _encode(entry),
            ex=_next_ttl_seconds(entry, now),
        )
        pipe.sadd(f"{USER_SESSIONS_KEY_PREFIX}{user_id}", session_id)
        pipe.execute()
        return session_id

    def get(self, session_id: str) -> str | None:
        if not session_id:
            return None

        client = get_redis()
        key = f"{SESSION_KEY_PREFIX}{session_id}"
        raw = client.get(key)
        if raw is None:
            # Lazy cleanup of stale membership if any user set still references this id.
            # We cannot know user_id here; callers of delete_by_user_id clean zombies.
            return None
        stored = str(raw)
        if not stored.startswith("{"):
            return stored or None
        entry = _parse_stored(stored)
        if entry is None:
            self.delete(session_id)
            return None
        now = time.time()
        if _is_expired(entry, now):
            self.delete(session_id)
            return None
        entry.last_activity = now
        client.set(key, _encode(entry), ex=_next_ttl_seconds(entry, now))
        return entry.user_id

    def delete(self, session_id: str) -> None:
        if not session_id:
            return

        client = get_redis()
        key = f"{SESSION_KEY_PREFIX}{session_id}"
        raw = client.get(key)
        user_id = _user_id_from_stored(str(raw)) if raw else None
        pipe = client.pipeline()
        pipe.delete(key)
        if user_id:
            pipe.srem(f"{USER_SESSIONS_KEY_PREFIX}{user_id}", session_id)
        pipe.execute()

    def delete_by_user_id(self, user_id: str) -> None:
        if not user_id:
            return

        client = get_redis()
        index_key = f"{USER_SESSIONS_KEY_PREFIX}{user_id}"
        session_ids = client.smembers(index_key)
        if not session_ids:
            return
        pipe = client.pipeline()
        for sid in session_ids:
            pipe.delete(f"{SESSION_KEY_PREFIX}{sid}")
            pipe.srem(index_key, sid)
        pipe.execute()
        # Drop empty index key if present
        if client.scard(index_key) == 0:
            client.delete(index_key)

    def delete_other_sessions(self, user_id: str, keep_session_id: str) -> None:
        if not user_id:
            return

        client = get_redis()
        index_key = f"{USER_SESSIONS_KEY_PREFIX}{user_id}"
        session_ids = client.smembers(index_key)
        if not session_ids:
            return
        pipe = client.pipeline()
        for sid in session_ids:
            sid_str = str(sid)
            if sid_str == keep_session_id:
                continue
            pipe.delete(f"{SESSION_KEY_PREFIX}{sid_str}")
            pipe.srem(index_key, sid_str)
        pipe.execute()


SessionStoreImpl = MemorySessionStore

_memory_singleton: MemorySessionStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_session_store() -> SessionStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemorySessionStore()
            return _memory_singleton
    return RedisSessionStore()


def reset_session_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_session_store.cache_clear()
