"""Dual-clock session records and legacy user-id values."""

from __future__ import annotations

import json
import time

from backend.admin.session_store import (
    SESSION_KEY_PREFIX,
    USER_SESSIONS_KEY_PREFIX,
    MemorySessionStore,
    RedisSessionStore,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float | None]] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        item = self.values.get(key)
        if item is None:
            return None
        value, expires_at = item
        if expires_at is not None and expires_at <= time.time():
            self.values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        expires_at = None if ex is None else time.time() + int(ex)
        self.values[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(str(member))

    def srem(self, key: str, member: str) -> None:
        self.sets.get(key, set()).discard(str(member))

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    def pipeline(self) -> "_FakePipeline":
        return _FakePipeline(self)

    def expires_at(self, key: str) -> float | None:
        item = self.values.get(key)
        if item is None:
            return None
        return item[1]


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple[str, tuple, dict]] = []

    def set(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._ops.append(("set", args, kwargs))
        return self

    def sadd(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._ops.append(("sadd", args, kwargs))
        return self

    def delete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._ops.append(("delete", args, kwargs))
        return self

    def srem(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self._ops.append(("srem", args, kwargs))
        return self

    def execute(self) -> list[object]:
        for name, args, kwargs in self._ops:
            getattr(self._client, name)(*args, **kwargs)
        return []


def _redis_store(monkeypatch) -> tuple[RedisSessionStore, _FakeRedis]:
    fake = _FakeRedis()
    monkeypatch.setattr("backend.admin.session_store.get_redis", lambda: fake)
    return RedisSessionStore(), fake


def test_memory_request_renews_idle_but_not_absolute() -> None:
    store = MemorySessionStore()
    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    entry = store._sessions[sid]
    absolute = entry.absolute_expires_at
    entry.last_activity = time.time() - 5

    assert store.get(sid) == "user_1"
    assert entry.absolute_expires_at == absolute
    assert entry.last_activity > time.time() - 2


def test_memory_idle_expiry_does_not_wait_for_absolute() -> None:
    store = MemorySessionStore()
    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    store._sessions[sid].last_activity = time.time() - 31

    assert store.get(sid) is None


def test_memory_absolute_expiry_ignores_recent_activity() -> None:
    store = MemorySessionStore()
    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    store._sessions[sid].absolute_expires_at = time.time() - 1

    assert store.get(sid) is None


def test_redis_request_renews_idle_but_not_absolute(monkeypatch) -> None:
    store, fake = _redis_store(monkeypatch)
    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    key = f"{SESSION_KEY_PREFIX}{sid}"
    before = json.loads(fake.get(key) or "")
    before["last_activity"] = time.time() - 5
    fake.set(key, json.dumps(before), ex=30)

    assert store.get(sid) == "user_1"
    after = json.loads(fake.get(key) or "")
    assert after["absolute_expires_at"] == before["absolute_expires_at"]
    assert after["last_activity"] > before["last_activity"]


def test_redis_idle_and_absolute_expiry_delete_the_key(monkeypatch) -> None:
    store, fake = _redis_store(monkeypatch)
    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    key = f"{SESSION_KEY_PREFIX}{sid}"
    payload = json.loads(fake.get(key) or "")
    payload["last_activity"] = time.time() - 31
    fake.set(key, json.dumps(payload), ex=100)

    assert store.get(sid) is None
    assert fake.get(key) is None

    sid = store.create("user_1", ttl_seconds=500, idle_seconds=30)
    key = f"{SESSION_KEY_PREFIX}{sid}"
    payload = json.loads(fake.get(key) or "")
    payload["absolute_expires_at"] = time.time() - 1
    fake.set(key, json.dumps(payload), ex=100)
    assert store.get(sid) is None


def test_redis_legacy_get_does_not_renew_ttl(monkeypatch) -> None:
    store, fake = _redis_store(monkeypatch)
    key = f"{SESSION_KEY_PREFIX}old"
    index = f"{USER_SESSIONS_KEY_PREFIX}user_9"
    fake.set(key, "user_9", ex=80)
    fake.sadd(index, "old")
    before = fake.expires_at(key)

    assert store.get("old") == "user_9"
    assert fake.get(key) == "user_9"
    assert fake.expires_at(key) == before


def test_redis_delete_removes_json_session_from_user_index(monkeypatch) -> None:
    store, fake = _redis_store(monkeypatch)
    sid = store.create("user_1", ttl_seconds=100, idle_seconds=30)
    index = f"{USER_SESSIONS_KEY_PREFIX}user_1"

    store.delete(sid)

    assert sid not in fake.smembers(index)
    assert fake.get(f"{SESSION_KEY_PREFIX}{sid}") is None
