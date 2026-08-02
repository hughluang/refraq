"""In-memory session store for the first Management Foundation slice."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from backend.admin.security import new_session_id


@dataclass
class _SessionEntry:
    user_id: str
    expires_at: float


class SessionStore:
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


_session_singleton: SessionStore | None = None
_session_lock = threading.Lock()


def get_session_store() -> SessionStore:
    global _session_singleton
    with _session_lock:
        if _session_singleton is None:
            _session_singleton = SessionStore()
        return _session_singleton


def reset_session_store() -> None:
    global _session_singleton
    with _session_lock:
        _session_singleton = None
