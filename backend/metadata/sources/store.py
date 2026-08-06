"""Source and Connection store ports/adapters."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.core.secrets import decrypt_secret, encrypt_secret
from backend.metadata.errors import (
    ConnectionEngineUnsupported,
    ConnectionNotFound,
    SourceConnectionExists,
    SourceConnectionKindInvalid,
    SourceKeyDuplicate,
    SourceKindUnsupported,
    SourceNotFound,
    SourceValidationError,
)

SUPPORTED_KINDS = frozenset({"database"})
SUPPORTED_ENGINES = frozenset({"postgresql", "mssql", "oracle"})


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
    created_at: datetime
    updated_at: datetime


@dataclass
class ConnectionRecord:
    id: str
    source_id: str
    name: str
    engine: str
    host: str
    port: int
    status: str
    secret_ciphertext: str | None
    secret_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def has_secret(self) -> bool:
        return bool(self.secret_ciphertext)


def new_source_id() -> str:
    return f"src_{uuid.uuid4().hex[:12]}"


def new_connection_id() -> str:
    return f"conn_{uuid.uuid4().hex[:12]}"


def encode_secret_payload(secret: dict[str, str]) -> str:
    return encrypt_secret(json.dumps(secret, separators=(",", ":")))


def decode_secret_payload(ciphertext: str) -> dict[str, Any]:
    return json.loads(decrypt_secret(ciphertext))


class SourceStore(Protocol):
    def list_sources(self) -> list[SourceRecord]: ...

    def get_source(self, source_id: str) -> SourceRecord | None: ...

    def get_source_by_key(self, key: str) -> SourceRecord | None: ...

    def create_source(self, record: SourceRecord) -> SourceRecord: ...

    def save_source(self, record: SourceRecord) -> SourceRecord: ...

    def get_connection(self, connection_id: str) -> ConnectionRecord | None: ...

    def get_connection_for_source(self, source_id: str) -> ConnectionRecord | None: ...

    def create_connection(self, record: ConnectionRecord) -> ConnectionRecord: ...

    def save_connection(self, record: ConnectionRecord) -> ConnectionRecord: ...


class MemorySourceStore:
    def __init__(self) -> None:
        self._sources: dict[str, SourceRecord] = {}
        self._by_key: dict[str, str] = {}
        self._connections: dict[str, ConnectionRecord] = {}
        self._by_source: dict[str, str] = {}
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

    def get_connection(self, connection_id: str) -> ConnectionRecord | None:
        with self._lock:
            return self._connections.get(connection_id)

    def get_connection_for_source(self, source_id: str) -> ConnectionRecord | None:
        with self._lock:
            conn_id = self._by_source.get(source_id)
            return self._connections.get(conn_id) if conn_id else None

    def create_connection(self, record: ConnectionRecord) -> ConnectionRecord:
        with self._lock:
            if record.source_id in self._by_source:
                raise SourceConnectionExists()
            self._connections[record.id] = record
            self._by_source[record.source_id] = record.id
            return record

    def save_connection(self, record: ConnectionRecord) -> ConnectionRecord:
        with self._lock:
            if record.id not in self._connections:
                raise ConnectionNotFound()
            self._connections[record.id] = record
            return record


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
            row.updated_at = record.updated_at
            try:
                session.flush()
            except IntegrityError as exc:
                raise SourceKeyDuplicate() from exc
            return _row_to_source(row)

    def get_connection(self, connection_id: str) -> ConnectionRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import ConnectionRow

        with session_scope() as session:
            row = session.get(ConnectionRow, connection_id)
            return _row_to_connection(row) if row else None

    def get_connection_for_source(self, source_id: str) -> ConnectionRecord | None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import ConnectionRow

        with session_scope() as session:
            row = session.scalars(
                select(ConnectionRow).where(ConnectionRow.source_id == source_id)
            ).first()
            return _row_to_connection(row) if row else None

    def create_connection(self, record: ConnectionRecord) -> ConnectionRecord:
        from sqlalchemy.exc import IntegrityError

        from backend.core.db import session_scope
        from backend.metadata.models import ConnectionRow

        with session_scope() as session:
            row = ConnectionRow(
                id=record.id,
                source_id=record.source_id,
                name=record.name,
                engine=record.engine,
                host=record.host,
                port=record.port,
                status=record.status,
                secret_ciphertext=record.secret_ciphertext,
                secret_updated_at=record.secret_updated_at,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                raise SourceConnectionExists() from exc
            return _row_to_connection(row)

    def save_connection(self, record: ConnectionRecord) -> ConnectionRecord:
        from backend.core.db import session_scope
        from backend.metadata.models import ConnectionRow

        with session_scope() as session:
            row = session.get(ConnectionRow, record.id)
            if row is None:
                raise ConnectionNotFound()
            row.name = record.name
            row.engine = record.engine
            row.host = record.host
            row.port = record.port
            row.status = record.status
            row.secret_ciphertext = record.secret_ciphertext
            row.secret_updated_at = record.secret_updated_at
            row.updated_at = record.updated_at
            session.flush()
            return _row_to_connection(row)


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
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_connection(row: object) -> ConnectionRecord:
    from backend.metadata.models import ConnectionRow

    assert isinstance(row, ConnectionRow)
    return ConnectionRecord(
        id=row.id,
        source_id=row.source_id,
        name=row.name,
        engine=row.engine,
        host=row.host,
        port=row.port,
        status=row.status,
        secret_ciphertext=row.secret_ciphertext,
        secret_updated_at=row.secret_updated_at,
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
) -> SourceRecord:
    if kind not in SUPPORTED_KINDS:
        raise SourceKindUnsupported()
    if kind == "database" and not database_name:
        raise SourceValidationError("database_name is required for database Sources")
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
    updated.updated_at = datetime.utcnow()
    return store.save_source(updated)


def create_connection(
    *,
    source_id: str,
    name: str,
    engine: str,
    host: str,
    port: int,
    secret: dict[str, str],
) -> ConnectionRecord:
    store = get_source_store()
    source = store.get_source(source_id)
    if source is None:
        raise SourceNotFound()
    if source.kind != "database":
        raise SourceConnectionKindInvalid()
    if engine not in SUPPORTED_ENGINES:
        raise ConnectionEngineUnsupported()
    if store.get_connection_for_source(source_id) is not None:
        raise SourceConnectionExists()
    now = datetime.utcnow()
    record = ConnectionRecord(
        id=new_connection_id(),
        source_id=source_id,
        name=name,
        engine=engine,
        host=host,
        port=port,
        status="active",
        secret_ciphertext=encode_secret_payload(secret),
        secret_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    return store.create_connection(record)


def update_connection(
    connection_id: str,
    *,
    name: str | None = None,
    engine: str | None = None,
    host: str | None = None,
    port: int | None = None,
    status: str | None = None,
) -> ConnectionRecord:
    store = get_source_store()
    existing = store.get_connection(connection_id)
    if existing is None:
        raise ConnectionNotFound()
    updated = replace(existing)
    if name is not None:
        updated.name = name
    if engine is not None:
        if engine not in SUPPORTED_ENGINES:
            raise ConnectionEngineUnsupported()
        updated.engine = engine
    if host is not None:
        updated.host = host
    if port is not None:
        updated.port = port
    if status is not None:
        if status not in {"active", "disabled"}:
            raise SourceValidationError("Invalid status")
        updated.status = status
    updated.updated_at = datetime.utcnow()
    return store.save_connection(updated)


def rotate_connection_secret(connection_id: str, secret: dict[str, str]) -> ConnectionRecord:
    store = get_source_store()
    existing = store.get_connection(connection_id)
    if existing is None:
        raise ConnectionNotFound()
    now = datetime.utcnow()
    updated = replace(
        existing,
        secret_ciphertext=encode_secret_payload(secret),
        secret_updated_at=now,
        updated_at=now,
    )
    return store.save_connection(updated)
