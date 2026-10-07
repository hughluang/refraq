"""Business Entity store ports and adapters."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import ColumnElement, and_, exists, false, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.entity.errors import (
    EntityNotFound,
    EntityTableNameDup,
    EntityVersionIdConflict,
    EntityVersionNotFound,
)
from backend.entity.lifecycle import PUBLISHED, EntityListStatus, entity_list_status
from backend.entity.models import BusinessEntityRow, EntityVersionRow
from backend.entity.records import (
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_from_dict,
    attribute_to_stored,
)

__all__ = [
    "EntityStore",
    "MemoryEntityStore",
    "SqlEntityStore",
    "get_entity_store",
    "reset_entity_store",
]


class EntityStore(Protocol):
    def list_entities(
        self,
        *,
        q: str | None,
        statuses: frozenset[EntityListStatus] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BusinessEntityRecord], int]: ...

    def get_entity(self, entity_id: str) -> BusinessEntityRecord | None: ...

    def get_entity_by_table_name(
        self, table_name: str
    ) -> BusinessEntityRecord | None: ...

    def list_all_entities(self) -> list[BusinessEntityRecord]: ...

    def create_entity(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]: ...

    def save_entity(self, entity: BusinessEntityRecord) -> BusinessEntityRecord: ...

    def save_entity_and_version(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]: ...

    def delete_entity(self, entity_id: str) -> bool: ...

    def list_versions(
        self, entity_id: str, *, limit: int, offset: int
    ) -> tuple[list[EntityVersionRecord], int]: ...

    def list_all_versions(self, entity_id: str) -> list[EntityVersionRecord]: ...

    def get_version(self, version_id: str) -> EntityVersionRecord | None: ...

    def current_version(self, entity_id: str) -> EntityVersionRecord | None: ...

    def create_version(self, version: EntityVersionRecord) -> EntityVersionRecord: ...

    def save_version(self, version: EntityVersionRecord) -> EntityVersionRecord: ...


class MemoryEntityStore:
    def __init__(self) -> None:
        self._entities: dict[str, BusinessEntityRecord] = {}
        self._by_table_name: dict[str, str] = {}
        self._versions: dict[str, EntityVersionRecord] = {}
        self._lock = threading.Lock()

    def list_entities(
        self,
        *,
        q: str | None,
        statuses: frozenset[EntityListStatus] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BusinessEntityRecord], int]:
        with self._lock:
            items = list(self._entities.values())
            versions = list(self._versions.values())
        if q and q.strip():
            needle = q.strip().lower()
            items = [
                item
                for item in items
                if needle in item.table_name.lower() or needle in item.name.lower()
            ]
        if statuses is not None:
            by_entity: dict[str, list[EntityVersionRecord]] = {}
            for version in versions:
                by_entity.setdefault(version.entity_id, []).append(version)
            items = [
                item
                for item in items
                if entity_list_status(item, by_entity.get(item.id, [])) in statuses
            ]
        items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def get_entity(self, entity_id: str) -> BusinessEntityRecord | None:
        with self._lock:
            return self._entities.get(entity_id)

    def get_entity_by_table_name(
        self, table_name: str
    ) -> BusinessEntityRecord | None:
        with self._lock:
            entity_id = self._by_table_name.get(table_name)
            if entity_id is None:
                return None
            return self._entities.get(entity_id)

    def list_all_entities(self) -> list[BusinessEntityRecord]:
        with self._lock:
            return list(self._entities.values())

    def create_entity(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]:
        with self._lock:
            if entity.table_name in self._by_table_name:
                raise EntityTableNameDup()
            if version.id in self._versions:
                raise EntityVersionIdConflict()
            self._entities[entity.id] = entity
            self._by_table_name[entity.table_name] = entity.id
            self._versions[version.id] = version
            return entity, version

    def save_entity(self, entity: BusinessEntityRecord) -> BusinessEntityRecord:
        with self._lock:
            existing = self._entities.get(entity.id)
            if existing is None:
                raise EntityNotFound()
            self._entities[entity.id] = entity
            return entity

    def save_entity_and_version(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]:
        with self._lock:
            if entity.id not in self._entities:
                raise EntityNotFound()
            if version.id not in self._versions:
                raise EntityVersionNotFound()
            self._entities[entity.id] = entity
            self._versions[version.id] = version
            return entity, version

    def delete_entity(self, entity_id: str) -> bool:
        with self._lock:
            existing = self._entities.pop(entity_id, None)
            if existing is None:
                return False
            if self._by_table_name.get(existing.table_name) == entity_id:
                del self._by_table_name[existing.table_name]
            version_ids = [
                version_id
                for version_id, version in self._versions.items()
                if version.entity_id == entity_id
            ]
            for version_id in version_ids:
                del self._versions[version_id]
            return True

    def list_versions(
        self, entity_id: str, *, limit: int, offset: int
    ) -> tuple[list[EntityVersionRecord], int]:
        items = self.list_all_versions(entity_id)
        return items[offset : offset + limit], len(items)

    def list_all_versions(self, entity_id: str) -> list[EntityVersionRecord]:
        with self._lock:
            items = [
                version
                for version in self._versions.values()
                if version.entity_id == entity_id
            ]
        items.sort(key=lambda item: (item.version, item.id), reverse=True)
        return items

    def get_version(self, version_id: str) -> EntityVersionRecord | None:
        with self._lock:
            return self._versions.get(version_id)

    def current_version(self, entity_id: str) -> EntityVersionRecord | None:
        items = self.list_all_versions(entity_id)
        return items[0] if items else None

    def create_version(self, version: EntityVersionRecord) -> EntityVersionRecord:
        with self._lock:
            if version.entity_id not in self._entities:
                raise EntityNotFound()
            if version.id in self._versions:
                raise EntityVersionIdConflict()
            self._versions[version.id] = version
            return version

    def save_version(self, version: EntityVersionRecord) -> EntityVersionRecord:
        with self._lock:
            if version.id not in self._versions:
                raise EntityVersionNotFound()
            self._versions[version.id] = version
            return version


def _entity_status_filter(
    statuses: frozenset[EntityListStatus],
) -> ColumnElement[bool]:
    """SQL form of entity_list_status. An empty set matches nothing."""
    if not statuses:
        return false()
    published = exists(
        select(EntityVersionRow.id).where(
            EntityVersionRow.entity_id == BusinessEntityRow.id,
            EntityVersionRow.publish_status == PUBLISHED,
        )
    )
    not_deprecated = BusinessEntityRow.deprecated_at.is_(None)
    clauses = []
    if "deprecated" in statuses:
        clauses.append(BusinessEntityRow.deprecated_at.is_not(None))
    if "serving" in statuses:
        clauses.append(and_(not_deprecated, published))
    if "not_serving" in statuses:
        clauses.append(and_(not_deprecated, not_(published)))
    return or_(*clauses)


class SqlEntityStore:
    def list_entities(
        self,
        *,
        q: str | None,
        statuses: frozenset[EntityListStatus] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[BusinessEntityRecord], int]:
        with session_scope() as session:
            stmt = select(BusinessEntityRow)
            count_stmt = select(func.count()).select_from(BusinessEntityRow)
            if q and q.strip():
                needle = f"%{_escape_like_literal(q.strip())}%"
                filt = or_(
                    BusinessEntityRow.table_name.ilike(needle, escape="\\"),
                    BusinessEntityRow.name.ilike(needle, escape="\\"),
                )
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)
            if statuses is not None:
                status_filt = _entity_status_filter(statuses)
                stmt = stmt.where(status_filt)
                count_stmt = count_stmt.where(status_filt)
            total = int(session.execute(count_stmt).scalar_one())
            rows = (
                session.execute(
                    stmt.order_by(
                        BusinessEntityRow.created_at.desc(),
                        BusinessEntityRow.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_entity_from_row(row) for row in rows], total

    def get_entity(self, entity_id: str) -> BusinessEntityRecord | None:
        with session_scope() as session:
            row = session.get(BusinessEntityRow, entity_id)
            return _entity_from_row(row) if row else None

    def get_entity_by_table_name(
        self, table_name: str
    ) -> BusinessEntityRecord | None:
        with session_scope() as session:
            row = session.execute(
                select(BusinessEntityRow).where(
                    BusinessEntityRow.table_name == table_name
                )
            ).scalar_one_or_none()
            return _entity_from_row(row) if row else None

    def list_all_entities(self) -> list[BusinessEntityRecord]:
        with session_scope() as session:
            rows = session.execute(select(BusinessEntityRow)).scalars().all()
            return [_entity_from_row(row) for row in rows]

    def create_entity(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]:
        with session_scope() as session:
            _flush_entity_rows(
                session,
                (_entity_to_row(entity), _version_to_row(version)),
            )
            return entity, version

    def save_entity(self, entity: BusinessEntityRecord) -> BusinessEntityRecord:
        with session_scope() as session:
            row = session.get(BusinessEntityRow, entity.id)
            if row is None:
                raise EntityNotFound()
            _write_entity_row(row, entity)
            session.flush()
            return _entity_from_row(row)

    def save_entity_and_version(
        self,
        entity: BusinessEntityRecord,
        version: EntityVersionRecord,
    ) -> tuple[BusinessEntityRecord, EntityVersionRecord]:
        with session_scope() as session:
            entity_row = session.get(BusinessEntityRow, entity.id)
            if entity_row is None:
                raise EntityNotFound()
            version_row = session.get(EntityVersionRow, version.id)
            if version_row is None:
                raise EntityVersionNotFound()
            _write_entity_row(entity_row, entity)
            _write_version_row(version_row, version)
            session.flush()
            return _entity_from_row(entity_row), _version_from_row(version_row)

    def delete_entity(self, entity_id: str) -> bool:
        with session_scope() as session:
            row = session.get(BusinessEntityRow, entity_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

    def list_versions(
        self, entity_id: str, *, limit: int, offset: int
    ) -> tuple[list[EntityVersionRecord], int]:
        with session_scope() as session:
            filt = EntityVersionRow.entity_id == entity_id
            total = int(
                session.execute(
                    select(func.count()).select_from(EntityVersionRow).where(filt)
                ).scalar_one()
            )
            rows = (
                session.execute(
                    select(EntityVersionRow)
                    .where(filt)
                    .order_by(EntityVersionRow.version.desc(), EntityVersionRow.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_version_from_row(row) for row in rows], total

    def list_all_versions(self, entity_id: str) -> list[EntityVersionRecord]:
        with session_scope() as session:
            rows = (
                session.execute(
                    select(EntityVersionRow)
                    .where(EntityVersionRow.entity_id == entity_id)
                    .order_by(EntityVersionRow.version.desc(), EntityVersionRow.id.desc())
                )
                .scalars()
                .all()
            )
            return [_version_from_row(row) for row in rows]

    def get_version(self, version_id: str) -> EntityVersionRecord | None:
        with session_scope() as session:
            row = session.get(EntityVersionRow, version_id)
            return _version_from_row(row) if row else None

    def current_version(self, entity_id: str) -> EntityVersionRecord | None:
        with session_scope() as session:
            row = session.execute(
                select(EntityVersionRow)
                .where(EntityVersionRow.entity_id == entity_id)
                .order_by(EntityVersionRow.version.desc(), EntityVersionRow.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            return _version_from_row(row) if row else None

    def create_version(self, version: EntityVersionRecord) -> EntityVersionRecord:
        with session_scope() as session:
            if session.get(BusinessEntityRow, version.entity_id) is None:
                raise EntityNotFound()
            _flush_entity_rows(session, (_version_to_row(version),))
            return version

    def save_version(self, version: EntityVersionRecord) -> EntityVersionRecord:
        with session_scope() as session:
            row = session.get(EntityVersionRow, version.id)
            if row is None:
                raise EntityVersionNotFound()
            _write_version_row(row, version)
            session.flush()
            return _version_from_row(row)


def _write_entity_row(row: BusinessEntityRow, entity: BusinessEntityRecord) -> None:
    row.name = entity.name
    row.description = entity.description
    row.deprecated_at = entity.deprecated_at
    row.updated_at = entity.updated_at


def _write_version_row(row: EntityVersionRow, version: EntityVersionRecord) -> None:
    row.attributes = [attribute_to_stored(attr) for attr in version.attributes]
    row.materialized_attributes = list(version.materialized_attributes)
    row.publish_status = version.publish_status
    row.latest_reconcile_job_id = version.latest_reconcile_job_id
    row.dictionary_snapshots = dict(version.dictionary_snapshots)
    row.reference_snapshots = dict(version.reference_snapshots)
    row.updated_at = version.updated_at


_TABLE_NAME_UNIQUE = "uq_business_entities_table_name"
_VERSION_ID_PK = "entity_versions_pkey"


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _pgcode(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    return code if isinstance(code, str) and code else None


def _constraint_name(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if isinstance(name, str) and name:
        return name
    name = getattr(orig, "constraint_name", None)
    return name if isinstance(name, str) and name else None


def _is_version_id_conflict(exc: BaseException) -> bool:
    """True only for the entity_versions primary key."""
    if _pgcode(exc) != "23505":
        return False
    return _constraint_name(exc) == _VERSION_ID_PK


def _is_entity_table_name_dup(exc: BaseException) -> bool:
    """True only for the business-entity table_name unique constraint."""
    if _pgcode(exc) != "23505":
        return False
    name = _constraint_name(exc)
    if name is None:
        return True
    return name == _TABLE_NAME_UNIQUE


def _flush_entity_rows(
    session: Session,
    rows: tuple[BusinessEntityRow | EntityVersionRow, ...],
) -> None:
    for row in rows:
        session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        if _is_entity_table_name_dup(exc):
            raise EntityTableNameDup() from exc
        if _is_version_id_conflict(exc):
            raise EntityVersionIdConflict() from exc
        raise


def _entity_from_row(row: BusinessEntityRow) -> BusinessEntityRecord:
    return BusinessEntityRecord(
        id=row.id,
        table_name=row.table_name,
        name=row.name,
        description=row.description,
        deprecated_at=row.deprecated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _entity_to_row(record: BusinessEntityRecord) -> BusinessEntityRow:
    return BusinessEntityRow(
        id=record.id,
        table_name=record.table_name,
        name=record.name,
        description=record.description,
        deprecated_at=record.deprecated_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _version_from_row(row: EntityVersionRow) -> EntityVersionRecord:
    return EntityVersionRecord(
        id=row.id,
        entity_id=row.entity_id,
        version=int(row.version),
        attributes=[attribute_from_dict(item) for item in row.attributes],
        materialized_attributes=[dict(item) for item in row.materialized_attributes],
        publish_status=str(row.publish_status),
        latest_reconcile_job_id=row.latest_reconcile_job_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        dictionary_snapshots=_snapshots_from_row(row.dictionary_snapshots),
        reference_snapshots=_snapshots_from_row(row.reference_snapshots),
    )


def _version_to_row(record: EntityVersionRecord) -> EntityVersionRow:
    return EntityVersionRow(
        id=record.id,
        entity_id=record.entity_id,
        version=record.version,
        attributes=[attribute_to_stored(attr) for attr in record.attributes],
        materialized_attributes=list(record.materialized_attributes),
        publish_status=record.publish_status,
        latest_reconcile_job_id=record.latest_reconcile_job_id,
        dictionary_snapshots=dict(record.dictionary_snapshots),
        reference_snapshots=dict(record.reference_snapshots),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _snapshots_from_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {str(key): dict(value) for key, value in raw.items()}


_memory_singleton: MemoryEntityStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_entity_store() -> MemoryEntityStore | SqlEntityStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryEntityStore()
            return _memory_singleton
    return SqlEntityStore()


def reset_entity_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_entity_store.cache_clear()
