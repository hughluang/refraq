"""Source store ports/adapters (encrypted access blob on Source)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.errors import SourceKeyDuplicate, SourceNotFound
from backend.metadata.locators import format_source_locator
from backend.metadata.models import SourceRow


SUPPORTED_KINDS = frozenset({"database"})

@dataclass
class SourceRecord:
    id: str
    key: str
    locator_key: str
    name: str
    kind: str
    status: str
    description: str | None
    database_name: str | None
    schema_filter: str | None
    engine: str | None
    access_ciphertext: str | None
    access_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def has_access(self) -> bool:
        return bool(self.access_ciphertext)

def new_source_id() -> str:
    return f"src_{uuid.uuid4().hex[:12]}"

def ensure_source_locator(record: SourceRecord) -> SourceRecord:
    """Recompute locator_key from key/engine/kind."""
    locator = format_source_locator(
        engine=record.engine, kind=record.kind, key=record.key
    )
    if record.locator_key == locator:
        return record
    return replace(record, locator_key=locator)

class SourceStore(Protocol):
    def list_sources(self) -> list[SourceRecord]: ...
    def get_source(self, source_id: str) -> SourceRecord | None: ...

    def get_source_by_key(self, key: str) -> SourceRecord | None: ...
    def get_source_by_locator(self, locator_key: str) -> SourceRecord | None: ...

    def create_source(self, record: SourceRecord) -> SourceRecord: ...
    def save_source(self, record: SourceRecord) -> SourceRecord: ...

    def delete_source(self, source_id: str) -> bool: ...

class MemorySourceStore:
    def __init__(self) -> None:
        self._sources: dict[str, SourceRecord] = {}
        self._by_key: dict[str, str] = {}
        self._by_locator: dict[str, str] = {}
        self._lock = threading.Lock()

    def list_sources(self) -> list[SourceRecord]:
        with self._lock:
            return sorted(
                self._sources.values(),
                key=lambda r: (r.key, r.id),
            )

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self._lock:
            return self._sources.get(source_id)

    def get_source_by_key(self, key: str) -> SourceRecord | None:
        with self._lock:
            source_id = self._by_key.get(key)
            return self._sources.get(source_id) if source_id else None

    def get_source_by_locator(self, locator_key: str) -> SourceRecord | None:
        with self._lock:
            source_id = self._by_locator.get(locator_key)
            return self._sources.get(source_id) if source_id else None

    def create_source(self, record: SourceRecord) -> SourceRecord:
        record = ensure_source_locator(record)
        with self._lock:
            if record.key in self._by_key:
                raise SourceKeyDuplicate()
            if record.locator_key in self._by_locator:
                raise SourceKeyDuplicate()
            self._sources[record.id] = record
            self._by_key[record.key] = record.id
            self._by_locator[record.locator_key] = record.id
            return record

    def save_source(self, record: SourceRecord) -> SourceRecord:
        record = ensure_source_locator(record)
        with self._lock:
            existing = self._sources.get(record.id)
            if existing is None:
                raise SourceNotFound()
            if existing.key != record.key:
                if record.key in self._by_key and self._by_key[record.key] != record.id:
                    raise SourceKeyDuplicate()
                del self._by_key[existing.key]
                self._by_key[record.key] = record.id
            if existing.locator_key != record.locator_key:
                if (
                    record.locator_key in self._by_locator
                    and self._by_locator[record.locator_key] != record.id
                ):
                    raise SourceKeyDuplicate()
                del self._by_locator[existing.locator_key]
                self._by_locator[record.locator_key] = record.id
            self._sources[record.id] = record
            return record

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            existing = self._sources.pop(source_id, None)
            if existing is None:
                return False
            if self._by_key.get(existing.key) == source_id:
                del self._by_key[existing.key]
            if self._by_locator.get(existing.locator_key) == source_id:
                del self._by_locator[existing.locator_key]
            return True

class SqlSourceStore:
    def list_sources(self) -> list[SourceRecord]:
        with session_scope() as session:
            rows = session.scalars(select(SourceRow).order_by(SourceRow.key)).all()
            return [_row_to_source(r) for r in rows]

    def get_source(self, source_id: str) -> SourceRecord | None:
        with session_scope() as session:
            row = session.get(SourceRow, source_id)
            return _row_to_source(row) if row else None

    def get_source_by_key(self, key: str) -> SourceRecord | None:
        with session_scope() as session:
            row = session.scalars(
                select(SourceRow).where(SourceRow.key == key)
            ).first()
            return _row_to_source(row) if row else None

    def get_source_by_locator(self, locator_key: str) -> SourceRecord | None:
        with session_scope() as session:
            row = session.scalars(
                select(SourceRow).where(SourceRow.locator_key == locator_key)
            ).first()
            return _row_to_source(row) if row else None

    def create_source(self, record: SourceRecord) -> SourceRecord:
        record = ensure_source_locator(record)
        with session_scope() as session:
            row = SourceRow(
                id=record.id,
                key=record.key,
                locator_key=record.locator_key,
                name=record.name,
                kind=record.kind,
                status=record.status,
                description=record.description,
                database_name=record.database_name,
                schema_filter=record.schema_filter,
                engine=record.engine,
                access_ciphertext=record.access_ciphertext,
                access_updated_at=record.access_updated_at,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                raise SourceKeyDuplicate() from exc
            return _row_to_source(row)

    def save_source(self, record: SourceRecord) -> SourceRecord:
        record = ensure_source_locator(record)
        with session_scope() as session:
            row = session.get(SourceRow, record.id)
            if row is None:
                raise SourceNotFound()
            row.key = record.key
            row.locator_key = record.locator_key
            row.name = record.name
            row.kind = record.kind
            row.status = record.status
            row.description = record.description
            row.database_name = record.database_name
            row.schema_filter = record.schema_filter
            row.engine = record.engine
            row.access_ciphertext = record.access_ciphertext
            row.access_updated_at = record.access_updated_at
            row.updated_at = record.updated_at
            try:
                session.flush()
            except IntegrityError as exc:
                raise SourceKeyDuplicate() from exc
            return _row_to_source(row)

    def delete_source(self, source_id: str) -> bool:
        with session_scope() as session:
            row = session.get(SourceRow, source_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

def _row_to_source(row: object) -> SourceRecord:
    assert isinstance(row, SourceRow)
    return SourceRecord(
        id=row.id,
        key=row.key,
        locator_key=row.locator_key,
        name=row.name,
        kind=row.kind,
        status=row.status,
        description=row.description,
        database_name=row.database_name,
        schema_filter=row.schema_filter,
        engine=row.engine,
        access_ciphertext=row.access_ciphertext,
        access_updated_at=row.access_updated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

_memory_singleton: MemorySourceStore | None = None
_memory_lock = threading.Lock()

@lru_cache
def get_source_store() -> MemorySourceStore | SqlSourceStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemorySourceStore()
            return _memory_singleton
    return SqlSourceStore()

def reset_source_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_source_store.cache_clear()
