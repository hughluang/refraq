"""Session repository ports and adapters (memory + Redis)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from backend.admin.security import new_session_id
from backend.core.config import get_settings

SESSION_KEY_PREFIX = "refraq:session:"
USER_SESSIONS_KEY_PREFIX = "refraq:user_sessions:"


@dataclass
class _SessionEntry:
    user_id: str
    expires_at: float


class SessionStore(Protocol):
    def create(self, user_id: str, ttl_seconds: int) -> str: ...

    def get(self, session_id: str) -> str | None: ...

    def delete(self, session_id: str) -> None: ...

    def delete_by_user_id(self, user_id: str) -> None: ...


class MemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str, ttl_seconds: int) -> str:
        session_id = new_session_id()
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._purge_expired_locked()
            self._sessions[session_id] = _SessionEntry(user_id, expires_at)
        return session_id

    def get(self, session_id: str) -> str | None:
        if not session_id:
            return None
        now = time.time()
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._sessions.pop(session_id, None)
                return None
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

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, entry in self._sessions.items() if entry.expires_at <= now]
        for sid in expired:
            self._sessions.pop(sid, None)


class RedisSessionStore:
    def create(self, user_id: str, ttl_seconds: int) -> str:
        from backend.core.redis_client import get_redis

        session_id = new_session_id()
        ttl = max(int(ttl_seconds), 1)
        client = get_redis()
        pipe = client.pipeline()
        pipe.set(f"{SESSION_KEY_PREFIX}{session_id}", user_id, ex=ttl)
        pipe.sadd(f"{USER_SESSIONS_KEY_PREFIX}{user_id}", session_id)
        pipe.execute()
        return session_id

    def get(self, session_id: str) -> str | None:
        if not session_id:
            return None
        from backend.core.redis_client import get_redis

        client = get_redis()
        key = f"{SESSION_KEY_PREFIX}{session_id}"
        user_id = client.get(key)
        if user_id is None:
            # Lazy cleanup of stale membership if any user set still references this id.
            # We cannot know user_id here; callers of delete_by_user_id clean zombies.
            return None
        return str(user_id)

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        from backend.core.redis_client import get_redis

        client = get_redis()
        key = f"{SESSION_KEY_PREFIX}{session_id}"
        user_id = client.get(key)
        pipe = client.pipeline()
        pipe.delete(key)
        if user_id:
            pipe.srem(f"{USER_SESSIONS_KEY_PREFIX}{user_id}", session_id)
        pipe.execute()

    def delete_by_user_id(self, user_id: str) -> None:
        if not user_id:
            return
        from backend.core.redis_client import get_redis

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
