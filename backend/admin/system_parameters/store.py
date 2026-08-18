"""Memory / persistent store for System Parameter rows."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from backend.admin.models import SystemParameterRow
from backend.admin.system_parameters.spec import ParameterValue
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now


@dataclass(slots=True)
class ParameterRecord:
    key: str
    value: ParameterValue
    previous_value: ParameterValue
    source: str
    updated_at: datetime
    updated_by_user_id: str | None


class ParameterStore(Protocol):
    def get(self, key: str) -> ParameterRecord | None: ...

    def upsert(self, record: ParameterRecord) -> None: ...

    def occupy_if_missing(self, record: ParameterRecord) -> bool: ...


class MemoryParameterStore:
    def __init__(self) -> None:
        self._rows: dict[str, ParameterRecord] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> ParameterRecord | None:
        with self._lock:
            return self._rows.get(key)

    def upsert(self, record: ParameterRecord) -> None:
        with self._lock:
            self._rows[record.key] = record

    def occupy_if_missing(self, record: ParameterRecord) -> bool:
        with self._lock:
            if record.key in self._rows:
                return False
            self._rows[record.key] = record
            return True


class SqlParameterStore:
    def get(self, key: str) -> ParameterRecord | None:
        with session_scope() as session:
            row = session.get(SystemParameterRow, key)
            return _row_to_record(row) if row else None

    def upsert(self, record: ParameterRecord) -> None:
        with session_scope() as session:
            row = session.get(SystemParameterRow, record.key)
            if row is None:
                session.add(_record_to_row(record))
            else:
                row.value = record.value
                row.previous_value = record.previous_value
                row.source = record.source
                row.updated_at = record.updated_at
                row.updated_by_user_id = record.updated_by_user_id
            session.flush()

    def occupy_if_missing(self, record: ParameterRecord) -> bool:
        try:
            with session_scope() as session:
                existing = session.get(SystemParameterRow, record.key)
                if existing is not None:
                    return False
                session.add(_record_to_row(record))
                session.flush()
            return True
        except IntegrityError:
            return False


def _row_to_record(row: SystemParameterRow) -> ParameterRecord:
    return ParameterRecord(
        key=row.key,
        value=row.value,  # type: ignore[arg-type]
        previous_value=row.previous_value,  # type: ignore[arg-type]
        source=row.source,
        updated_at=row.updated_at,
        updated_by_user_id=row.updated_by_user_id,
    )


def _record_to_row(record: ParameterRecord) -> SystemParameterRow:
    return SystemParameterRow(
        key=record.key,
        value=record.value,
        previous_value=record.previous_value,
        source=record.source,
        updated_at=record.updated_at,
        updated_by_user_id=record.updated_by_user_id,
    )


_memory_singleton: MemoryParameterStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_parameter_store() -> ParameterStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryParameterStore()
            return _memory_singleton
    return SqlParameterStore()


def reset_parameter_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_parameter_store.cache_clear()


def new_seed_record(key: str, value: ParameterValue) -> ParameterRecord:
    return ParameterRecord(
        key=key,
        value=value,
        previous_value=None,
        source="seed",
        updated_at=utc_now(),
        updated_by_user_id=None,
    )
