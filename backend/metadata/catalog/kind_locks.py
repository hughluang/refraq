"""Kind execution locks for structure and join-detection Job runners.

Same-kind contention on one Source fails the later Job with ``JOB_ALREADY_ACTIVE``.
Cross-kind may overlap. Authority is the lock, not the Job table (ADR 0032).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.db import get_engine

KindLockKind = Literal["structure", "join_detection"]

_memory_guard = threading.Lock()
_memory_locks: dict[str, threading.Lock] = {}
_memory_held: set[str] = set()


def lock_name(kind: KindLockKind, source_id: str) -> str:
    return f"{kind}:{source_id}"


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


@dataclass
class KindExecutionLock:
    """Held lock; call ``release`` exactly once (or use ``hold_kind_execution_lock``)."""

    _name: str = field(repr=False)
    _mode: Literal["memory", "postgres"] = field(repr=False)
    _conn: object | None = field(default=None, repr=False)
    _released: bool = field(default=False, repr=False)

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
        finally:
            conn.close()
            self._conn = None


def try_acquire_kind_execution_lock(
    kind: KindLockKind, source_id: str
) -> KindExecutionLock | None:
    """Non-blocking try. Returns a handle when acquired; ``None`` when contested."""
    name = lock_name(kind, source_id)
    if not _use_postgres_advisory():
        with _memory_guard:
            lock = _memory_locks.setdefault(name, threading.Lock())
            if not lock.acquire(blocking=False):
                return None
            _memory_held.add(name)
        return KindExecutionLock(_name=name, _mode="memory")

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
        return KindExecutionLock(_name=name, _mode="postgres", _conn=conn)
    except Exception:
        conn.close()
        raise


@contextmanager
def hold_kind_execution_lock(
    kind: KindLockKind, source_id: str
) -> Iterator[KindExecutionLock | None]:
    """Yield the lock handle, or ``None`` if not acquired. Always releases if held."""
    held = try_acquire_kind_execution_lock(kind, source_id)
    try:
        yield held
    finally:
        if held is not None:
            held.release()


def reset_kind_execution_locks_for_tests() -> None:
    """Drop in-process lock state (memory backend / unit tests only)."""
    with _memory_guard:
        for name in list(_memory_held):
            lock = _memory_locks.get(name)
            if lock is not None:
                try:
                    lock.release()
                except RuntimeError:
                    pass
        _memory_held.clear()
        _memory_locks.clear()
