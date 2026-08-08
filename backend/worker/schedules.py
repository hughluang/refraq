"""Scheduled Task seed and repository helpers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from backend.core.config import get_settings


@dataclass
class ScheduledTaskRecord:
    id: str
    key: str
    name: str
    enabled: bool
    interval_seconds: int | None
    cron: str | None
    task_name: str
    args_json: list = field(default_factory=list)
    kwargs_json: dict = field(default_factory=dict)
    system: bool = False
    last_run_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class MemoryScheduleStore:
    def __init__(self) -> None:
        self._by_key: dict[str, ScheduledTaskRecord] = {}
        self._lock = threading.Lock()

    def upsert(self, record: ScheduledTaskRecord) -> ScheduledTaskRecord:
        with self._lock:
            self._by_key[record.key] = record
            return record

    def get_by_key(self, key: str) -> ScheduledTaskRecord | None:
        with self._lock:
            return self._by_key.get(key)

    def list_enabled(self) -> list[ScheduledTaskRecord]:
        with self._lock:
            return [r for r in self._by_key.values() if r.enabled]

    def touch_last_run(self, key: str, when: datetime) -> None:
        with self._lock:
            record = self._by_key.get(key)
            if record is not None:
                record.last_run_at = when
                record.updated_at = when


class SqlScheduleStore:
    def upsert(self, record: ScheduledTaskRecord) -> ScheduledTaskRecord:
        from backend.core.db import session_scope
        from backend.worker.models import ScheduledTaskRow

        from sqlalchemy import select

        with session_scope() as session:
            row = session.get(ScheduledTaskRow, record.id)
            if row is None:
                row = session.scalar(
                    select(ScheduledTaskRow).where(ScheduledTaskRow.key == record.key)
                )
            if row is None:
                row = ScheduledTaskRow(id=record.id)
                session.add(row)
            row.key = record.key
            row.name = record.name
            row.enabled = record.enabled
            row.interval_seconds = record.interval_seconds
            row.cron = record.cron
            row.task_name = record.task_name
            row.args_json = list(record.args_json)
            row.kwargs_json = dict(record.kwargs_json)
            row.system = record.system
            row.last_run_at = record.last_run_at
            row.created_at = record.created_at
            row.updated_at = record.updated_at
            session.flush()
            return _row_to_schedule(row)

    def get_by_key(self, key: str) -> ScheduledTaskRecord | None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.worker.models import ScheduledTaskRow

        with session_scope() as session:
            row = session.scalar(
                select(ScheduledTaskRow).where(ScheduledTaskRow.key == key)
            )
            return _row_to_schedule(row) if row else None

    def list_enabled(self) -> list[ScheduledTaskRecord]:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.worker.models import ScheduledTaskRow

        with session_scope() as session:
            rows = session.scalars(
                select(ScheduledTaskRow).where(ScheduledTaskRow.enabled.is_(True))
            ).all()
            return [_row_to_schedule(row) for row in rows]

    def touch_last_run(self, key: str, when: datetime) -> None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.worker.models import ScheduledTaskRow

        with session_scope() as session:
            row = session.scalar(
                select(ScheduledTaskRow).where(ScheduledTaskRow.key == key)
            )
            if row is not None:
                row.last_run_at = when
                row.updated_at = when


def _row_to_schedule(row: object) -> ScheduledTaskRecord:
    from backend.worker.models import ScheduledTaskRow

    assert isinstance(row, ScheduledTaskRow)
    return ScheduledTaskRecord(
        id=row.id,
        key=row.key,
        name=row.name,
        enabled=row.enabled,
        interval_seconds=row.interval_seconds,
        cron=row.cron,
        task_name=row.task_name,
        args_json=list(row.args_json or []),
        kwargs_json=dict(row.kwargs_json or {}),
        system=row.system,
        last_run_at=row.last_run_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory_singleton: MemoryScheduleStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_schedule_store() -> MemoryScheduleStore | SqlScheduleStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryScheduleStore()
            return _memory_singleton
    return SqlScheduleStore()


def reset_schedule_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_schedule_store.cache_clear()
