"""Source store ports/adapters (encrypted access blob on Source)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.metadata.errors import (
    SourceAccessRequired,
    SourceKeyDuplicate,
    SourceKindUnsupported,
    SourceNotDisabled,
    SourceNotFound,
    SourceValidationError,
)
from backend.metadata.sources.access import (
    SUPPORTED_ENGINES,
    decrypt_access_blob,
    encrypt_access_blob,
    validate_access,
)

SUPPORTED_KINDS = frozenset({"database"})


@dataclass
class SourceRecord:
    id: str
    key: str
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


class SourceStore(Protocol):
    def list_sources(self) -> list[SourceRecord]: ...

    def get_source(self, source_id: str) -> SourceRecord | None: ...

    def get_source_by_key(self, key: str) -> SourceRecord | None: ...

    def create_source(self, record: SourceRecord) -> SourceRecord: ...

    def save_source(self, record: SourceRecord) -> SourceRecord: ...

    def delete_source(self, source_id: str) -> bool: ...


class MemorySourceStore:
    def __init__(self) -> None:
        self._sources: dict[str, SourceRecord] = {}
        self._by_key: dict[str, str] = {}
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

    def create_source(self, record: SourceRecord) -> SourceRecord:
        with self._lock:
            if record.key in self._by_key:
                raise SourceKeyDuplicate()
            self._sources[record.id] = record
            self._by_key[record.key] = record.id
            return record

    def save_source(self, record: SourceRecord) -> SourceRecord:
        with self._lock:
            existing = self._sources.get(record.id)
            if existing is None:
                raise SourceNotFound()
            if existing.key != record.key:
                if record.key in self._by_key and self._by_key[record.key] != record.id:
                    raise SourceKeyDuplicate()
                del self._by_key[existing.key]
                self._by_key[record.key] = record.id
            self._sources[record.id] = record
            return record

    def delete_source(self, source_id: str) -> bool:
        with self._lock:
            existing = self._sources.pop(source_id, None)
            if existing is None:
                return False
            if self._by_key.get(existing.key) == source_id:
                del self._by_key[existing.key]
            return True


class SqlSourceStore:
    def list_sources(self) -> list[SourceRecord]:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            rows = session.scalars(select(SourceRow).order_by(SourceRow.key)).all()
            return [_row_to_source(r) for r in rows]

    def get_source(self, source_id: str) -> SourceRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            row = session.get(SourceRow, source_id)
            return _row_to_source(row) if row else None

    def get_source_by_key(self, key: str) -> SourceRecord | None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            row = session.scalars(
                select(SourceRow).where(SourceRow.key == key)
            ).first()
            return _row_to_source(row) if row else None

    def create_source(self, record: SourceRecord) -> SourceRecord:
        from sqlalchemy.exc import IntegrityError

        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            row = SourceRow(
                id=record.id,
                key=record.key,
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
        from sqlalchemy.exc import IntegrityError

        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            row = session.get(SourceRow, record.id)
            if row is None:
                raise SourceNotFound()
            row.key = record.key
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
        from backend.core.db import session_scope
        from backend.metadata.models import SourceRow

        with session_scope() as session:
            row = session.get(SourceRow, source_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


def _row_to_source(row: object) -> SourceRecord:
    from backend.metadata.models import SourceRow

    assert isinstance(row, SourceRow)
    return SourceRecord(
        id=row.id,
        key=row.key,
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


def create_source(
    *,
    key: str,
    name: str,
    kind: str,
    description: str | None,
    database_name: str | None,
    schema_filter: str | None,
    engine: str | None,
    access: dict[str, Any] | None,
) -> SourceRecord:
    if kind not in SUPPORTED_KINDS:
        raise SourceKindUnsupported()
    ciphertext: str | None = None
    access_updated_at: datetime | None = None
    if kind == "database":
        if not database_name:
            raise SourceValidationError("database_name is required for database Sources")
        if not engine or access is None:
            raise SourceAccessRequired()
        access = validate_access(engine, access)
        ciphertext = encrypt_access_blob(access)
        access_updated_at = datetime.utcnow()
    now = datetime.utcnow()
    record = SourceRecord(
        id=new_source_id(),
        key=key,
        name=name,
        kind=kind,
        status="active",
        description=description,
        database_name=database_name,
        schema_filter=schema_filter,
        engine=engine,
        access_ciphertext=ciphertext,
        access_updated_at=access_updated_at,
        created_at=now,
        updated_at=now,
    )
    return get_source_store().create_source(record)


def update_source(
    source_id: str,
    *,
    name: str | None = None,
    description: str | None | object = ...,
    status: str | None = None,
    database_name: str | None = None,
    schema_filter: str | None | object = ...,
    engine: str | None = None,
    access: dict[str, Any] | None | object = ...,
) -> SourceRecord:
    store = get_source_store()
    existing = store.get_source(source_id)
    if existing is None:
        raise SourceNotFound()
    updated = replace(existing)
    if name is not None:
        updated.name = name
    if description is not ...:
        updated.description = description  # type: ignore[assignment]
    if status is not None:
        if status not in {"active", "disabled"}:
            raise SourceValidationError("Invalid status")
        updated.status = status
    if database_name is not None:
        updated.database_name = database_name
    if schema_filter is not ...:
        updated.schema_filter = schema_filter  # type: ignore[assignment]
    if engine is not None:
        if engine not in SUPPORTED_ENGINES:
            from backend.metadata.errors import SourceEngineUnsupported

            raise SourceEngineUnsupported()
        updated.engine = engine
    if access is not ...:
        eng = engine if engine is not None else updated.engine
        if eng is None:
            raise SourceAccessRequired()
        validated = validate_access(eng, access)  # type: ignore[arg-type]
        updated.access_ciphertext = encrypt_access_blob(validated)
        updated.access_updated_at = datetime.utcnow()
    elif engine is not None and updated.access_ciphertext:
        # Re-validate existing blob against new engine (usually requires full replace)
        existing_access = decrypt_access_blob(updated.access_ciphertext)
        validated = validate_access(engine, existing_access)
        updated.access_ciphertext = encrypt_access_blob(validated)
        updated.access_updated_at = datetime.utcnow()
    updated.updated_at = datetime.utcnow()
    return store.save_source(updated)


def delete_source(source_id: str) -> SourceRecord:
    store = get_source_store()
    existing = store.get_source(source_id)
    if existing is None:
        raise SourceNotFound()
    if existing.status != "disabled":
        raise SourceNotDisabled()
    from backend.metadata.catalog.store import get_catalog_store

    get_catalog_store().delete_objects_for_source(source_id)
    if not store.delete_source(source_id):
        raise SourceNotFound()
    return existing
