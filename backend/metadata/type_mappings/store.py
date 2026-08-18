"""Type Mapping store ports/adapters."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.errors import TypeMappingNotFound
from backend.metadata.models import TypeMappingRow


__all__ = [
    "TypeMappingRecord",
    "TypeMappingStore",
    "MemoryTypeMappingStore",
    "SqlTypeMappingStore",
    "get_type_mapping_store",
    "new_type_mapping_id",
    "reset_type_mapping_store",
]


@dataclass
class TypeMappingRecord:
    id: str
    engine: str
    native_type: str
    normalized_type: str
    origin: str
    created_at: datetime
    updated_at: datetime


def new_type_mapping_id() -> str:
    return f"tm_{uuid.uuid4().hex[:12]}"


class TypeMappingStore(Protocol):
    def list_mappings(
        self,
        *,
        q: str | None = None,
        engine: str | None = None,
        origin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TypeMappingRecord], int]: ...

    def get(self, mapping_id: str) -> TypeMappingRecord | None: ...

    def get_by_key(self, engine: str, native_type: str) -> TypeMappingRecord | None: ...

    def list_for_engine(self, engine: str) -> list[TypeMappingRecord]: ...

    def create(self, record: TypeMappingRecord) -> TypeMappingRecord: ...

    def insert_if_absent(self, record: TypeMappingRecord) -> TypeMappingRecord: ...

    def save(self, record: TypeMappingRecord) -> TypeMappingRecord: ...


class MemoryTypeMappingStore:
    def __init__(self) -> None:
        self._rows: dict[str, TypeMappingRecord] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def list_mappings(
        self,
        *,
        q: str | None = None,
        engine: str | None = None,
        origin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TypeMappingRecord], int]:
        with self._lock:
            items = list(self._rows.values())
        if engine:
            items = [r for r in items if r.engine == engine]
        if origin:
            items = [r for r in items if r.origin == origin]
        if q and q.strip():
            needle = q.strip().lower()
            items = [
                r
                for r in items
                if needle in r.native_type
                or needle in r.engine
                or needle in r.normalized_type
            ]
        items.sort(key=lambda r: (r.engine, r.native_type, r.id))
        total = len(items)
        return items[offset : offset + limit], total

    def get(self, mapping_id: str) -> TypeMappingRecord | None:
        with self._lock:
            return self._rows.get(mapping_id)

    def get_by_key(self, engine: str, native_type: str) -> TypeMappingRecord | None:
        with self._lock:
            mapping_id = self._by_key.get((engine, native_type))
            return self._rows.get(mapping_id) if mapping_id else None

    def list_for_engine(self, engine: str) -> list[TypeMappingRecord]:
        with self._lock:
            return [
                row
                for row in self._rows.values()
                if row.engine == engine
            ]

    def create(self, record: TypeMappingRecord) -> TypeMappingRecord:
        with self._lock:
            key = (record.engine, record.native_type)
            if key in self._by_key:
                raise IntegrityError("uq_type_mappings_engine_native", orig=None, params=None)
            self._rows[record.id] = record
            self._by_key[key] = record.id
            return record

    def insert_if_absent(self, record: TypeMappingRecord) -> TypeMappingRecord:
        with self._lock:
            key = (record.engine, record.native_type)
            existing_id = self._by_key.get(key)
            if existing_id is not None:
                return self._rows[existing_id]
            self._rows[record.id] = record
            self._by_key[key] = record.id
            return record

    def save(self, record: TypeMappingRecord) -> TypeMappingRecord:
        with self._lock:
            existing = self._rows.get(record.id)
            if existing is None:
                raise TypeMappingNotFound()
            old_key = (existing.engine, existing.native_type)
            new_key = (record.engine, record.native_type)
            if old_key != new_key:
                if new_key in self._by_key:
                    raise IntegrityError(
                        "uq_type_mappings_engine_native", orig=None, params=None
                    )
                if self._by_key.get(old_key) == record.id:
                    del self._by_key[old_key]
                self._by_key[new_key] = record.id
            self._rows[record.id] = record
            return record


class SqlTypeMappingStore:
    def list_mappings(
        self,
        *,
        q: str | None = None,
        engine: str | None = None,
        origin: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[TypeMappingRecord], int]:
        with session_scope() as session:
            stmt = select(TypeMappingRow)
            count_stmt = select(func.count()).select_from(TypeMappingRow)
            if engine:
                stmt = stmt.where(TypeMappingRow.engine == engine)
                count_stmt = count_stmt.where(TypeMappingRow.engine == engine)
            if origin:
                stmt = stmt.where(TypeMappingRow.origin == origin)
                count_stmt = count_stmt.where(TypeMappingRow.origin == origin)
            if q and q.strip():
                needle = f"%{q.strip()}%"
                filt = or_(
                    TypeMappingRow.native_type.ilike(needle),
                    TypeMappingRow.engine.ilike(needle),
                    TypeMappingRow.normalized_type.ilike(needle),
                )
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)
            total = int(session.execute(count_stmt).scalar_one())
            rows = (
                session.execute(
                    stmt.order_by(
                        TypeMappingRow.engine,
                        TypeMappingRow.native_type,
                        TypeMappingRow.id,
                    )
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_row_to_record(r) for r in rows], total

    def get(self, mapping_id: str) -> TypeMappingRecord | None:
        with session_scope() as session:
            row = session.get(TypeMappingRow, mapping_id)
            return _row_to_record(row) if row else None

    def get_by_key(self, engine: str, native_type: str) -> TypeMappingRecord | None:
        with session_scope() as session:
            row = session.execute(
                select(TypeMappingRow).where(
                    TypeMappingRow.engine == engine,
                    TypeMappingRow.native_type == native_type,
                )
            ).scalar_one_or_none()
            return _row_to_record(row) if row else None

    def list_for_engine(self, engine: str) -> list[TypeMappingRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(TypeMappingRow).where(TypeMappingRow.engine == engine)
            ).all()
            return [_row_to_record(row) for row in rows]

    def create(self, record: TypeMappingRecord) -> TypeMappingRecord:
        with session_scope() as session:
            session.add(_record_to_row(record))
            try:
                session.flush()
            except IntegrityError:
                raise
            return record

    def insert_if_absent(self, record: TypeMappingRecord) -> TypeMappingRecord:
        try:
            return self.create(record)
        except IntegrityError:
            existing = self.get_by_key(record.engine, record.native_type)
            if existing is None:
                raise
            return existing

    def save(self, record: TypeMappingRecord) -> TypeMappingRecord:
        with session_scope() as session:
            row = session.get(TypeMappingRow, record.id)
            if row is None:
                raise TypeMappingNotFound()
            row.engine = record.engine
            row.native_type = record.native_type
            row.normalized_type = record.normalized_type
            row.origin = record.origin
            row.updated_at = record.updated_at
            session.flush()
            return _row_to_record(row)


def _record_to_row(record: TypeMappingRecord) -> TypeMappingRow:
    return TypeMappingRow(
        id=record.id,
        engine=record.engine,
        native_type=record.native_type,
        normalized_type=record.normalized_type,
        origin=record.origin,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _row_to_record(row: object) -> TypeMappingRecord:
    assert isinstance(row, TypeMappingRow)
    return TypeMappingRecord(
        id=row.id,
        engine=row.engine,
        native_type=row.native_type,
        normalized_type=row.normalized_type,
        origin=row.origin,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory_singleton: MemoryTypeMappingStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_type_mapping_store() -> MemoryTypeMappingStore | SqlTypeMappingStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryTypeMappingStore()
            return _memory_singleton
    return SqlTypeMappingStore()


def reset_type_mapping_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_type_mapping_store.cache_clear()
