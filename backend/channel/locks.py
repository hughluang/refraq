"""Per-Channel execution lock for ``concurrency = "forbid"``."""

from __future__ import annotations

import hashlib
import threading
from typing import Literal

from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.db import get_engine

__all__ = [
    "ChannelRunLock",
    "reset_channel_run_locks_for_tests",
    "try_acquire_channel_run_lock",
]

_memory_guard = threading.Lock()
_memory_locks: dict[str, threading.Lock] = {}
_memory_held: set[str] = set()


def _advisory_keys(name: str) -> tuple[int, int]:
    digest = hashlib.blake2b(name.encode(), digest_size=8).digest()
    return (
        int.from_bytes(digest[:4], "big", signed=True),
        int.from_bytes(digest[4:], "big", signed=True),
    )


def _use_postgres_advisory() -> bool:
    settings = get_settings()
    url = settings.database_url or ""
    return settings.store_backend == "persistent" and url.startswith("postgresql")


class ChannelRunLock:
    def __init__(
        self,
        name: str,
        mode: Literal["memory", "postgres"],
        conn: object | None = None,
    ) -> None:
        self._name = name
        self._mode = mode
        self._conn = conn
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._mode == "memory":
            with _memory_guard:
                lock = _memory_locks.get(self._name)
                if lock is not None and self._name in _memory_held:
                    _memory_held.discard(self._name)
                    lock.release()
            return
        conn = self._conn
        assert conn is not None
        keys = _advisory_keys(self._name)
        try:
            conn.execute(
                text("SELECT pg_advisory_unlock(:a, :b)"),
                {"a": keys[0], "b": keys[1]},
            )
            conn.commit()
        except Exception:
            conn.invalidate()
            raise
        finally:
            conn.close()
            self._conn = None


def try_acquire_channel_run_lock(channel_id: str) -> ChannelRunLock | None:
    """Acquire a non-blocking per-channel execution lock, or return None if held."""
    name = f"channel_run:{channel_id}"
    if not _use_postgres_advisory():
        with _memory_guard:
            lock = _memory_locks.setdefault(name, threading.Lock())
            if not lock.acquire(blocking=False):
                return None
            _memory_held.add(name)
        return ChannelRunLock(name, "memory")

    keys = _advisory_keys(name)
    conn = get_engine().connect()
    try:
        acquired = conn.execute(
            text("SELECT pg_try_advisory_lock(:a, :b)"),
            {"a": keys[0], "b": keys[1]},
        ).scalar()
        conn.commit()
        if not acquired:
            conn.close()
            return None
        return ChannelRunLock(name, "postgres", conn)
    except Exception:
        conn.close()
        raise


def reset_channel_run_locks_for_tests() -> None:
    with _memory_guard:
        _memory_held.clear()
        _memory_locks.clear()
