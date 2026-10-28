"""Site-wide and channel-owned variable store.

Expired values are absent. set-if-absent and compare-and-set are one statement
on PostgreSQL and one lock on the memory store. Both namespaces share that
operation branch. A run value is not stored here.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now

__all__ = [
    "VALUE_MAX_BYTES",
    "VariableRecord",
    "VariableResult",
    "apply_records",
    "get_variable_store",
    "valid_name",
    "value_size",
]

VALUE_MAX_BYTES = 64 * 1024
_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class _Namespace:
    table: str
    insert_columns: str
    insert_values: str
    conflict: str
    where: str


_SITE = _Namespace(
    table="channel_variables",
    insert_columns="name, value, expires_at, updated_at",
    insert_values=":name, CAST(:value AS jsonb), :expires, :now",
    conflict="name",
    where="name = :name",
)
_CHANNEL = _Namespace(
    table="channel_owned_variables",
    insert_columns="channel_id, name, value, expires_at, updated_at",
    insert_values=":channel_id, :name, CAST(:value AS jsonb), :expires, :now",
    conflict="channel_id, name",
    where="channel_id = :channel_id AND name = :name",
)


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


def apply_records(
    rows: MutableMapping[str, VariableRecord],
    *,
    operation: str,
    name: str,
    value: Any = None,
    expected: Any = None,
    ttl_sec: int | None = None,
    now: datetime | None = None,
) -> VariableResult:
    moment = now or utc_now()
    current = _live_record(rows.get(name), moment)
    if operation == "get":
        return _result(name, current, applied=False)
    if operation == "delete":
        rows.pop(name, None)
        return VariableResult(name, False, None, current is not None, None)
    expires = _expires(moment, ttl_sec)
    if operation == "set":
        saved = VariableRecord(name, value, expires, moment)
        rows[name] = saved
        return _result(name, saved, applied=True)
    if operation == "set_if_absent":
        if current is not None:
            return _result(name, current, applied=False)
        saved = VariableRecord(name, value, expires, moment)
        rows[name] = saved
        return _result(name, saved, applied=True)
    if operation == "compare_and_set":
        if current is None or current.value != expected:
            return _result(name, current, applied=False)
        saved = VariableRecord(name, value, expires, moment)
        rows[name] = saved
        return _result(name, saved, applied=True)
    raise ValueError(f"unknown variable operation {operation}")


class MemoryVariableStore:
    def __init__(self) -> None:
        self._site: dict[str, VariableRecord] = {}
        self._channels: dict[str, dict[str, VariableRecord]] = {}
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
        channel_id: str | None = None,
    ) -> VariableResult:
        moment = now or utc_now()
        with self._lock:
            return apply_records(
                self._bag(channel_id),
                operation=operation,
                name=name,
                value=value,
                expected=expected,
                ttl_sec=ttl_sec,
                now=moment,
            )

    def list_live(
        self,
        *,
        limit: int,
        offset: int,
        now: datetime | None = None,
        channel_id: str | None = None,
    ) -> tuple[list[VariableRecord], int]:
        moment = now or utc_now()
        with self._lock:
            bag = (
                self._site
                if channel_id is None
                else self._channels.get(channel_id, {})
            )
            live = [
                row
                for row in bag.values()
                if row.expires_at is None or row.expires_at > moment
            ]
            live.sort(key=lambda row: row.name)
            return live[offset : offset + limit], len(live)

    def delete(
        self,
        name: str,
        *,
        now: datetime | None = None,
        channel_id: str | None = None,
    ) -> bool:
        moment = now or utc_now()
        with self._lock:
            bag = self._site if channel_id is None else self._channels.get(channel_id, {})
            row = _live_record(bag.get(name), moment)
            if row is None:
                bag.pop(name, None)
                return False
            del bag[name]
            return True

    def delete_for_channel(self, channel_id: str) -> None:
        with self._lock:
            self._channels.pop(channel_id, None)

    def _bag(self, channel_id: str | None) -> dict[str, VariableRecord]:
        if channel_id is None:
            return self._site
        return self._channels.setdefault(channel_id, {})


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
        channel_id: str | None = None,
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
                channel_id=channel_id,
            )

    def list_live(
        self,
        *,
        limit: int,
        offset: int,
        now: datetime | None = None,
        channel_id: str | None = None,
    ) -> tuple[list[VariableRecord], int]:
        moment = now or utc_now()
        namespace = _CHANNEL if channel_id is not None else _SITE
        where = "expires_at IS NULL OR expires_at > :now"
        count_params: dict[str, Any] = {"now": moment}
        select_params: dict[str, Any] = {
            "now": moment,
            "limit": limit,
            "offset": offset,
        }
        if channel_id is not None:
            where = f"channel_id = :channel_id AND ({where})"
            count_params["channel_id"] = channel_id
            select_params["channel_id"] = channel_id
        with session_scope() as session:
            total = session.scalar(
                text(f"SELECT count(*) FROM {namespace.table} WHERE {where}"),
                count_params,
            )
            rows = session.execute(
                text(
                    f"SELECT name, value, expires_at, updated_at FROM {namespace.table} "
                    f"WHERE {where} ORDER BY name LIMIT :limit OFFSET :offset"
                ),
                select_params,
            ).all()
            return [
                VariableRecord(row.name, row.value, row.expires_at, row.updated_at)
                for row in rows
            ], int(total or 0)

    def delete(
        self,
        name: str,
        *,
        now: datetime | None = None,
        channel_id: str | None = None,
    ) -> bool:
        moment = now or utc_now()
        namespace, identity = _namespace(channel_id, name)
        params = {**identity, "now": moment}
        with session_scope() as session:
            result = session.execute(
                text(
                    f"DELETE FROM {namespace.table} WHERE {namespace.where} "
                    "AND (expires_at IS NULL OR expires_at > :now)"
                ),
                params,
            )
            return bool(result.rowcount)

    def delete_for_channel(self, channel_id: str) -> None:
        with session_scope() as session:
            session.execute(
                text(
                    "DELETE FROM channel_owned_variables WHERE channel_id = :channel_id"
                ),
                {"channel_id": channel_id},
            )


def _namespace(channel_id: str | None, name: str) -> tuple[_Namespace, dict[str, Any]]:
    if channel_id is None:
        return _SITE, {"name": name}
    return _CHANNEL, {"channel_id": channel_id, "name": name}


def _sql_apply(
    session: Session,
    *,
    operation: str,
    name: str,
    value: Any,
    expected: Any,
    ttl_sec: int | None,
    now: datetime,
    channel_id: str | None,
) -> VariableResult:
    namespace, identity = _namespace(channel_id, name)
    if operation == "get":
        return _result(name, _live_sql(session, namespace, identity, now), applied=False)
    if operation == "delete":
        current = _live_sql(session, namespace, identity, now)
        session.execute(
            text(f"DELETE FROM {namespace.table} WHERE {namespace.where}"),
            identity,
        )
        return VariableResult(name, False, None, current is not None, None)
    expires = _expires(now, ttl_sec)
    payload = json.dumps(value)
    params = {**identity, "value": payload, "expires": expires, "now": now}
    if operation == "set":
        session.execute(
            text(
                f"INSERT INTO {namespace.table} ({namespace.insert_columns}) "
                f"VALUES ({namespace.insert_values}) "
                f"ON CONFLICT ({namespace.conflict}) DO UPDATE SET "
                "value = EXCLUDED.value, expires_at = EXCLUDED.expires_at, "
                "updated_at = EXCLUDED.updated_at"
            ),
            params,
        )
        return _result(name, _live_sql(session, namespace, identity, now), applied=True)
    if operation == "set_if_absent":
        updated = session.execute(
            text(
                f"INSERT INTO {namespace.table} ({namespace.insert_columns}) "
                f"VALUES ({namespace.insert_values}) "
                f"ON CONFLICT ({namespace.conflict}) DO UPDATE SET "
                "value = EXCLUDED.value, expires_at = EXCLUDED.expires_at, "
                "updated_at = EXCLUDED.updated_at "
                f"WHERE {namespace.table}.expires_at IS NOT NULL "
                f"AND {namespace.table}.expires_at <= :now "
                "RETURNING name"
            ),
            params,
        ).first()
        current = _live_sql(session, namespace, identity, now)
        return _result(name, current, applied=updated is not None)
    if operation == "compare_and_set":
        updated = session.execute(
            text(
                f"UPDATE {namespace.table} SET value = CAST(:value AS jsonb), "
                "expires_at = :expires, updated_at = :now "
                f"WHERE {namespace.where} AND value = CAST(:expected AS jsonb) "
                "AND (expires_at IS NULL OR expires_at > :now) "
                "RETURNING name"
            ),
            {**params, "expected": json.dumps(expected)},
        ).first()
        return _result(
            name,
            _live_sql(session, namespace, identity, now),
            applied=updated is not None,
        )
    raise ValueError(f"unknown variable operation {operation}")


def _live_sql(
    session: Session,
    namespace: _Namespace,
    identity: dict[str, Any],
    now: datetime,
) -> VariableRecord | None:
    row = session.execute(
        text(
            f"SELECT name, value, expires_at, updated_at FROM {namespace.table} "
            f"WHERE {namespace.where}"
        ),
        identity,
    ).first()
    if row is None:
        return None
    return _live_record(
        VariableRecord(row.name, row.value, row.expires_at, row.updated_at),
        now,
    )


def _live_record(row: VariableRecord | None, now: datetime) -> VariableRecord | None:
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None
    return row


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
