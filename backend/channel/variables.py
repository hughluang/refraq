"""Site-wide Global Variable store.

Expired values are absent. set-if-absent and compare-and-set are one statement
on PostgreSQL and one lock on the memory store.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.channel.models import ChannelVariableRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

__all__ = [
    "VALUE_MAX_BYTES",
    "VariableRecord",
    "VariableResult",
    "get_variable_store",
    "valid_name",
    "value_size",
]

VALUE_MAX_BYTES = 64 * 1024
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass
class VariableRecord:
    name: str
    value: Any
    expires_at: datetime | None
    updated_at: datetime


@dataclass
class VariableResult:
    name: str
    found: bool
    value: Any
    applied: bool
    expires_at: datetime | None


def valid_name(name: str) -> bool:
    return bool(_NAME.fullmatch(name))


def value_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


class MemoryVariableStore:
    def __init__(self) -> None:
        self._rows: dict[str, VariableRecord] = {}
        self._lock = threading.Lock()

    def apply(
        self,
        *,
        operation: str,
        name: str,
        value: Any = None,
        expected: Any = None,
        ttl_sec: int | None = None,
        now: datetime | None = None,
    ) -> VariableResult:
        moment = now or utc_now()
        with self._lock:
            return self._apply(
                operation=operation,
                name=name,
                value=value,
                expected=expected,
                ttl_sec=ttl_sec,
                now=moment,
            )

    def list_live(
        self, *, limit: int, offset: int, now: datetime | None = None
    ) -> tuple[list[VariableRecord], int]:
        moment = now or utc_now()
        with self._lock:
            live = [
                row
                for row in self._rows.values()
                if row.expires_at is None or row.expires_at > moment
            ]
            live.sort(key=lambda row: row.name)
            return live[offset : offset + limit], len(live)

    def delete(self, name: str, *, now: datetime | None = None) -> bool:
        moment = now or utc_now()
        with self._lock:
            row = self._live(name, moment)
            if row is None:
                self._rows.pop(name, None)
                return False
            del self._rows[name]
            return True

    def _apply(
        self,
        *,
        operation: str,
        name: str,
        value: Any,
        expected: Any,
        ttl_sec: int | None,
        now: datetime,
    ) -> VariableResult:
        current = self._live(name, now)
        if operation == "get":
            return _result(name, current, applied=False)
        if operation == "delete":
            self._rows.pop(name, None)
            return VariableResult(name, False, None, current is not None, None)
        expires = _expires(now, ttl_sec)
        if operation == "set":
            saved = VariableRecord(name, value, expires, now)
            self._rows[name] = saved
            return _result(name, saved, applied=True)
        if operation == "set_if_absent":
            if current is not None:
                return _result(name, current, applied=False)
            saved = VariableRecord(name, value, expires, now)
            self._rows[name] = saved
            return _result(name, saved, applied=True)
        if operation == "compare_and_set":
            if current is None or current.value != expected:
                return _result(name, current, applied=False)
            saved = VariableRecord(name, value, expires, now)
            self._rows[name] = saved
            return _result(name, saved, applied=True)
        raise ValueError(f"unknown variable operation {operation}")

    def _live(self, name: str, now: datetime) -> VariableRecord | None:
        row = self._rows.get(name)
        if row is None:
            return None
        if row.expires_at is not None and row.expires_at <= now:
            return None
        return row


class SqlVariableStore:
    def apply(
        self,
        *,
        operation: str,
        name: str,
        value: Any = None,
        expected: Any = None,
        ttl_sec: int | None = None,
        now: datetime | None = None,
    ) -> VariableResult:
        moment = now or utc_now()
        with session_scope() as session:
            return _sql_apply(
                session,
                operation=operation,
                name=name,
                value=value,
                expected=expected,
                ttl_sec=ttl_sec,
                now=moment,
            )

    def list_live(
        self, *, limit: int, offset: int, now: datetime | None = None
    ) -> tuple[list[VariableRecord], int]:
        moment = now or utc_now()
        with session_scope() as session:
            total = session.scalar(
                text(
                    "SELECT count(*) FROM channel_variables "
                    "WHERE expires_at IS NULL OR expires_at > :now"
                ),
                {"now": moment},
            )
            rows = session.execute(
                text(
                    "SELECT name, value, expires_at, updated_at FROM channel_variables "
                    "WHERE expires_at IS NULL OR expires_at > :now "
                    "ORDER BY name LIMIT :limit OFFSET :offset"
                ),
                {"now": moment, "limit": limit, "offset": offset},
            ).all()
            return [
                VariableRecord(row.name, row.value, row.expires_at, row.updated_at)
                for row in rows
            ], int(total or 0)

    def delete(self, name: str, *, now: datetime | None = None) -> bool:
        moment = now or utc_now()
        with session_scope() as session:
            result = session.execute(
                text(
                    "DELETE FROM channel_variables WHERE name = :name "
                    "AND (expires_at IS NULL OR expires_at > :now)"
                ),
                {"name": name, "now": moment},
            )
            return bool(result.rowcount)


def _sql_apply(
    session: Session,
    *,
    operation: str,
    name: str,
    value: Any,
    expected: Any,
    ttl_sec: int | None,
    now: datetime,
) -> VariableResult:
    if operation == "get":
        return _result(name, _live_row(session, name, now), applied=False)
    if operation == "delete":
        current = _live_row(session, name, now)
        session.execute(text("DELETE FROM channel_variables WHERE name = :name"), {"name": name})
        return VariableResult(name, False, None, current is not None, None)
    expires = _expires(now, ttl_sec)
    payload = json.dumps(value)
    if operation == "set":
        session.execute(
            text(
                "INSERT INTO channel_variables (name, value, expires_at, updated_at) "
                "VALUES (:name, CAST(:value AS jsonb), :expires, :now) "
                "ON CONFLICT (name) DO UPDATE SET "
                "value = EXCLUDED.value, expires_at = EXCLUDED.expires_at, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {"name": name, "value": payload, "expires": expires, "now": now},
        )
        return _result(name, _live_row(session, name, now), applied=True)
    if operation == "set_if_absent":
        updated = session.execute(
            text(
                "INSERT INTO channel_variables (name, value, expires_at, updated_at) "
                "VALUES (:name, CAST(:value AS jsonb), :expires, :now) "
                "ON CONFLICT (name) DO UPDATE SET "
                "value = EXCLUDED.value, expires_at = EXCLUDED.expires_at, "
                "updated_at = EXCLUDED.updated_at "
                "WHERE channel_variables.expires_at IS NOT NULL "
                "AND channel_variables.expires_at <= :now "
                "RETURNING name"
            ),
            {"name": name, "value": payload, "expires": expires, "now": now},
        ).first()
        current = _live_row(session, name, now)
        return _result(name, current, applied=updated is not None)
    if operation == "compare_and_set":
        updated = session.execute(
            text(
                "UPDATE channel_variables SET value = CAST(:value AS jsonb), "
                "expires_at = :expires, updated_at = :now "
                "WHERE name = :name AND value = CAST(:expected AS jsonb) "
                "AND (expires_at IS NULL OR expires_at > :now) "
                "RETURNING name"
            ),
            {
                "name": name,
                "value": payload,
                "expected": json.dumps(expected),
                "expires": expires,
                "now": now,
            },
        ).first()
        return _result(name, _live_row(session, name, now), applied=updated is not None)
    raise ValueError(f"unknown variable operation {operation}")


def _live_row(session: Session, name: str, now: datetime) -> VariableRecord | None:
    row = session.get(ChannelVariableRow, name)
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None
    return VariableRecord(row.name, row.value, row.expires_at, row.updated_at)


def _expires(now: datetime, ttl_sec: int | None) -> datetime | None:
    if ttl_sec is None:
        return None
    return now + timedelta(seconds=ttl_sec)


def _result(name: str, row: VariableRecord | None, *, applied: bool) -> VariableResult:
    if row is None:
        return VariableResult(name, False, None, applied, None)
    return VariableResult(name, True, row.value, applied, row.expires_at)


_memory: MemoryVariableStore | None = None
_lock = threading.Lock()


@lru_cache
def get_variable_store() -> MemoryVariableStore | SqlVariableStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryVariableStore()
            return _memory
    return SqlVariableStore()
