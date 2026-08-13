"""Structure Diff store ports/adapters (Source-owned, Job-associated)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.models import StructureDiffRow


__all__ = [
    "StructureDiffRecord",
    "get_structure_diff_store",
    "new_structure_diff_id",
    "reset_structure_diff_store",
]


@dataclass
class StructureDiffRecord:
    id: str
    source_id: str
    job_id: str
    diff_class: str
    counts: dict[str, int]
    changes: list[dict[str, Any]]
    created_at: datetime


def new_structure_diff_id() -> str:
    return f"sdiff_{uuid.uuid4().hex[:12]}"


class StructureDiffStore(Protocol):
    def create(self, record: StructureDiffRecord) -> StructureDiffRecord: ...

    def get(self, diff_id: str) -> StructureDiffRecord | None: ...

    def list_for_source(
        self, source_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[StructureDiffRecord], int]: ...

    def delete_for_source(self, source_id: str) -> None: ...


class MemoryStructureDiffStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StructureDiffRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: StructureDiffRecord) -> StructureDiffRecord:
        with self._lock:
            self._by_id[record.id] = record
            return record

    def get(self, diff_id: str) -> StructureDiffRecord | None:
        with self._lock:
            return self._by_id.get(diff_id)

    def list_for_source(
        self, source_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[StructureDiffRecord], int]:
        with self._lock:
            items = [
                r for r in self._by_id.values() if r.source_id == source_id
            ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def delete_for_source(self, source_id: str) -> None:
        with self._lock:
            drop = [i for i, r in self._by_id.items() if r.source_id == source_id]
            for i in drop:
                del self._by_id[i]


class SqlStructureDiffStore:
    def create(self, record: StructureDiffRecord) -> StructureDiffRecord:
        with session_scope() as session:
            row = StructureDiffRow(
                id=record.id,
                source_id=record.source_id,
                job_id=record.job_id,
                diff_class=record.diff_class,
                counts=dict(record.counts),
                changes=list(record.changes),
                created_at=record.created_at,
            )
            session.add(row)
            session.flush()
            return _row_to_diff(row)

    def get(self, diff_id: str) -> StructureDiffRecord | None:
        with session_scope() as session:
            row = session.get(StructureDiffRow, diff_id)
            return _row_to_diff(row) if row else None

    def list_for_source(
        self, source_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[StructureDiffRecord], int]:
        with session_scope() as session:
            base = select(StructureDiffRow).where(
                StructureDiffRow.source_id == source_id
            )
            total = len(session.scalars(base).all())
            stmt = (
                base.order_by(StructureDiffRow.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            items = [_row_to_diff(r) for r in session.scalars(stmt).all()]
            return items, total

    def delete_for_source(self, source_id: str) -> None:
        with session_scope() as session:
            rows = session.scalars(
                select(StructureDiffRow).where(
                    StructureDiffRow.source_id == source_id
                )
            ).all()
            for row in rows:
                session.delete(row)


def _row_to_diff(row: StructureDiffRow) -> StructureDiffRecord:
    return StructureDiffRecord(
        id=row.id,
        source_id=row.source_id,
        job_id=row.job_id,
        diff_class=row.diff_class,
        counts=dict(row.counts or {}),
        changes=list(row.changes or []),
        created_at=row.created_at,
    )


_memory_singleton: MemoryStructureDiffStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_structure_diff_store() -> MemoryStructureDiffStore | SqlStructureDiffStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryStructureDiffStore()
            return _memory_singleton
    return SqlStructureDiffStore()


def reset_structure_diff_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_structure_diff_store.cache_clear()
