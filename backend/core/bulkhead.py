"""Process-local admission pool: bounded executor, no queue, per-actor share."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

from backend.core.runtime import get_runtime_capacity

T = TypeVar("T")


class CapacityExceeded(Exception):
    """Peek cabin total occupancy is full."""

    def __init__(self, *, occupied: int, limit: int) -> None:
        super().__init__("peek cabin is full")
        self.occupied = occupied
        self.limit = limit


class ActorShareExceeded(Exception):
    """This actor already holds its fair share of the peek cabin."""

    def __init__(self, *, occupied: int, limit: int) -> None:
        super().__init__("actor peek share is full")
        self.occupied = occupied
        self.limit = limit


@dataclass(frozen=True)
class PeekSnapshot:
    occupied: int
    limit: int
    share_limit: int


class PeekBulkhead:
    def __init__(self, slots: int, share: int) -> None:
        self._slots = max(0, slots)
        self._share = max(0, share)
        self._lock = threading.Lock()
        self._total = 0
        self._per_actor: dict[str, int] = defaultdict(int)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, self._slots or 1),
            thread_name_prefix="refraq-peek",
        )

    def snapshot(self) -> PeekSnapshot:
        with self._lock:
            return PeekSnapshot(
                occupied=self._total,
                limit=self._slots,
                share_limit=self._share,
            )

    def submit_nowait(self, actor_key: str, fn: Callable[[], T]) -> Future[T]:
        if self._slots < 1:
            raise CapacityExceeded(occupied=0, limit=0)
        with self._lock:
            actor_used = self._per_actor[actor_key]
            if actor_used >= self._share:
                raise ActorShareExceeded(occupied=actor_used, limit=self._share)
            if self._total >= self._slots:
                raise CapacityExceeded(occupied=self._total, limit=self._slots)
            self._total += 1
            self._per_actor[actor_key] = actor_used + 1
        try:
            return self._executor.submit(self._run, actor_key, fn)
        except Exception:
            self._release(actor_key)
            raise

    def _run(self, actor_key: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        finally:
            self._release(actor_key)

    def _release(self, actor_key: str) -> None:
        with self._lock:
            self._total = max(0, self._total - 1)
            left = self._per_actor[actor_key] - 1
            if left <= 0:
                self._per_actor.pop(actor_key, None)
            else:
                self._per_actor[actor_key] = left

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


_bulkhead: PeekBulkhead | None = None
_bulkhead_lock = threading.Lock()


def get_peek_bulkhead() -> PeekBulkhead:
    global _bulkhead
    with _bulkhead_lock:
        if _bulkhead is None:
            cap = get_runtime_capacity()
            _bulkhead = PeekBulkhead(cap.admission_slots, cap.admission_actor_share)
        return _bulkhead


def reset_peek_bulkhead() -> None:
    global _bulkhead
    with _bulkhead_lock:
        if _bulkhead is not None:
            _bulkhead.shutdown()
            _bulkhead = None
