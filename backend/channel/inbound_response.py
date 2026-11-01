"""Response slot for one inbound call, keyed by the Job id.

The API process opens the slot and waits. The worker claims it from the first
Respond. Memory tests share the in-process slot. A persistent store uses Redis
so the API and the worker can be different processes.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from backend.core.config import get_settings
from backend.core.redis_client import get_redis

__all__ = [
    "InboundResponseStore",
    "get_inbound_response_store",
    "reset_inbound_response_store",
]

_PREFIX = "refraq:channel:inbound-response:"

_CLAIM = """
local state = redis.call('GET', KEYS[1])
if state ~= 'open' then
  return 0
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 1 then
  ttl = 1
end
redis.call('SET', KEYS[1], 'answered', 'EX', ttl)
redis.call('SET', KEYS[2], ARGV[1], 'EX', ttl)
redis.call('LPUSH', KEYS[3], '1')
redis.call('EXPIRE', KEYS[3], ttl)
return 1
"""

_CLOSE = """
local state = redis.call('GET', KEYS[1])
if state ~= 'open' then
  return 0
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 1 then
  ttl = 1
end
redis.call('SET', KEYS[1], 'closed', 'EX', ttl)
redis.call('LPUSH', KEYS[2], '1')
redis.call('EXPIRE', KEYS[2], ttl)
return 1
"""


class InboundResponseStore(Protocol):
    def open(self, job_id: str, *, ttl_sec: int) -> None: ...

    def claim(self, job_id: str, response: Mapping[str, Any]) -> bool: ...

    def read(self, job_id: str) -> dict[str, Any] | None: ...

    def wait(self, job_id: str, timeout_sec: float) -> dict[str, Any] | None: ...

    def close(self, job_id: str) -> None: ...


@dataclass
class _MemorySlot:
    state: str
    payload: dict[str, Any] | None
    expires_at: float
    event: threading.Event


def _snapshot(response: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(response, ensure_ascii=False))


class MemoryInboundResponseStore:
    def __init__(self) -> None:
        self._slots: dict[str, _MemorySlot] = {}
        self._lock = threading.Lock()

    def open(self, job_id: str, *, ttl_sec: int) -> None:
        with self._lock:
            if self._current(job_id) is not None:
                return
            self._slots[job_id] = _MemorySlot(
                state="open",
                payload=None,
                expires_at=time.monotonic() + ttl_sec,
                event=threading.Event(),
            )

    def claim(self, job_id: str, response: Mapping[str, Any]) -> bool:
        payload = _snapshot(response)
        with self._lock:
            slot = self._current(job_id)
            if slot is None or slot.state != "open":
                return False
            slot.state = "answered"
            slot.payload = payload
            slot.event.set()
            return True

    def read(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            slot = self._current(job_id)
            if slot is None or slot.state != "answered":
                return None
            return slot.payload

    def wait(self, job_id: str, timeout_sec: float) -> dict[str, Any] | None:
        with self._lock:
            slot = self._current(job_id)
            if slot is None:
                return None
            event = slot.event
        if timeout_sec <= 0:
            return self.read(job_id)
        event.wait(timeout_sec)
        return self.read(job_id)

    def close(self, job_id: str) -> None:
        with self._lock:
            slot = self._current(job_id)
            if slot is None or slot.state != "open":
                return
            slot.state = "closed"
            slot.event.set()

    def _current(self, job_id: str) -> _MemorySlot | None:
        slot = self._slots.get(job_id)
        if slot is None:
            return None
        if slot.expires_at <= time.monotonic():
            self._slots.pop(job_id, None)
            return None
        return slot


class RedisInboundResponseStore:
    def open(self, job_id: str, *, ttl_sec: int) -> None:
        get_redis().set(self._state(job_id), "open", nx=True, ex=ttl_sec)

    def claim(self, job_id: str, response: Mapping[str, Any]) -> bool:
        raw = json.dumps(_snapshot(response), ensure_ascii=False, separators=(",", ":"))
        result = get_redis().eval(
            _CLAIM,
            3,
            self._state(job_id),
            self._body(job_id),
            self._wake(job_id),
            raw,
        )
        return int(result) == 1

    def read(self, job_id: str) -> dict[str, Any] | None:
        client = get_redis()
        if client.get(self._state(job_id)) != "answered":
            return None
        raw = client.get(self._body(job_id))
        if raw is None:
            return None
        return json.loads(raw)

    def wait(self, job_id: str, timeout_sec: float) -> dict[str, Any] | None:
        found = self.read(job_id)
        if found is not None or timeout_sec <= 0:
            return found
        get_redis().blpop([self._wake(job_id)], timeout=timeout_sec)
        return self.read(job_id)

    def close(self, job_id: str) -> None:
        get_redis().eval(_CLOSE, 2, self._state(job_id), self._wake(job_id))

    def _state(self, job_id: str) -> str:
        return f"{_PREFIX}{job_id}"

    def _body(self, job_id: str) -> str:
        return f"{_PREFIX}{job_id}:body"

    def _wake(self, job_id: str) -> str:
        return f"{_PREFIX}{job_id}:wake"


_memory: MemoryInboundResponseStore | None = None
_lock = threading.Lock()


def get_inbound_response_store() -> InboundResponseStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryInboundResponseStore()
            return _memory
    return RedisInboundResponseStore()


def reset_inbound_response_store() -> None:
    global _memory
    with _lock:
        _memory = None
