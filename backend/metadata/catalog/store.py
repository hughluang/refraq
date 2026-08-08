"""Catalog object/column store and replace writer."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.metadata.errors import CatalogObjectNotFound

# Sentinel: field omitted from patch (distinct from explicit None).
UNSET: Any = object()


@dataclass
class CatalogColumnRecord:
    id: str
    object_id: str
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    is_present: bool
    business_name: str | None
    business_description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class CatalogObjectRecord:
    id: str
    source_id: str
    object_type: str
    schema_name: str
    name: str
    ddl: str | None
    is_present: bool
    business_name: str | None
    business_description: str | None
    last_structure_job_id: str | None
    collected_at: datetime | None
    created_at: datetime
    updated_at: datetime
    columns: list[CatalogColumnRecord] = field(default_factory=list)


@dataclass
class CatalogJoinRecord:
    id: str
    from_column_id: str
    to_column_id: str
    evidence: str
    created_by_user_id: str | None
    created_at: datetime


def new_object_id() -> str:
    return f"obj_{uuid.uuid4().hex[:12]}"


def new_column_id() -> str:
    return f"col_{uuid.uuid4().hex[:12]}"


def new_join_id() -> str:
    return f"join_{uuid.uuid4().hex[:12]}"


class CatalogStore(Protocol):
    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
    ) -> list[CatalogObjectRecord]: ...

    def get_object(self, object_id: str) -> CatalogObjectRecord | None: ...

    def get_column(self, column_id: str) -> CatalogColumnRecord | None: ...

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]: ...

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
    ) -> None: ...

    def delete_objects_for_source(self, source_id: str) -> None: ...

    def patch_object_semantics(
        self,
        object_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogObjectRecord | None: ...

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogColumnRecord | None: ...

    def get_join(self, join_id: str) -> CatalogJoinRecord | None: ...

    def list_joins_for_object(self, object_id: str) -> list[CatalogJoinRecord]: ...

    def upsert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
    ) -> CatalogJoinRecord: ...

    def delete_join(self, join_id: str) -> bool: ...


class MemoryCatalogStore:
    def __init__(self) -> None:
        self._objects: dict[str, CatalogObjectRecord] = {}
        self._joins: dict[str, CatalogJoinRecord] = {}
        self._join_by_pair: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
    ) -> list[CatalogObjectRecord]:
        with self._lock:
            items = [o for o in self._objects.values() if o.source_id == source_id]
            if not include_absent:
                items = [o for o in items if o.is_present]
            if name_search:
                q = name_search.lower()
                items = [
                    o
                    for o in items
                    if q in o.name.lower() or q in o.schema_name.lower()
                ]
            return sorted(items, key=lambda o: (o.schema_name, o.name, o.object_type))

    def get_object(self, object_id: str) -> CatalogObjectRecord | None:
        with self._lock:
            return self._objects.get(object_id)

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        with self._lock:
            for obj in self._objects.values():
                for col in obj.columns:
                    if col.id == column_id:
                        return col
            return None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        return self.list_objects(source_id, include_absent=False)

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
    ) -> None:
        now = datetime.utcnow()
        with self._lock:
            incoming_keys = {
                (o.schema_name, o.name, o.object_type): o for o in objects
            }
            existing = [
                o for o in self._objects.values() if o.source_id == source_id
            ]
            for old in existing:
                if schema_scope is not None and old.schema_name != schema_scope:
                    continue
                key = (old.schema_name, old.name, old.object_type)
                if key not in incoming_keys:
                    updated = replace(
                        old,
                        is_present=False,
                        updated_at=now,
                        last_structure_job_id=job_id,
                    )
                    updated.columns = [
                        replace(c, is_present=False, updated_at=now)
                        for c in old.columns
                    ]
                    self._objects[old.id] = updated

            for key, incoming in incoming_keys.items():
                match = next(
                    (
                        o
                        for o in existing
                        if (o.schema_name, o.name, o.object_type) == key
                    ),
                    None,
                )
                if match is None:
                    self._objects[incoming.id] = incoming
                    continue
                # Preserve identity and semantics
                col_by_name = {c.name: c for c in match.columns}
                new_cols: list[CatalogColumnRecord] = []
                seen_cols: set[str] = set()
                for col in incoming.columns:
                    seen_cols.add(col.name)
                    prev = col_by_name.get(col.name)
                    if prev is None:
                        new_cols.append(
                            replace(col, object_id=match.id, id=new_column_id())
                        )
                    else:
                        new_cols.append(
                            replace(
                                prev,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                is_present=True,
                                updated_at=now,
                                # business_* preserved
                            )
                        )
                for name, prev in col_by_name.items():
                    if name not in seen_cols:
                        new_cols.append(
                            replace(prev, is_present=False, updated_at=now)
                        )
                self._objects[match.id] = replace(
                    match,
                    ddl=incoming.ddl,
                    is_present=True,
                    last_structure_job_id=job_id,
                    collected_at=now,
                    updated_at=now,
                    columns=sorted(new_cols, key=lambda c: c.ordinal),
                    # business_* preserved on match
                )

    def delete_objects_for_source(self, source_id: str) -> None:
        with self._lock:
            col_ids: set[str] = set()
            to_drop = [
                oid
                for oid, obj in self._objects.items()
                if obj.source_id == source_id
            ]
            for oid in to_drop:
                for col in self._objects[oid].columns:
                    col_ids.add(col.id)
                del self._objects[oid]
            stale_joins = [
                jid
                for jid, join in self._joins.items()
                if join.from_column_id in col_ids or join.to_column_id in col_ids
            ]
            for jid in stale_joins:
                join = self._joins.pop(jid)
                self._join_by_pair.pop(
                    (join.from_column_id, join.to_column_id), None
                )

    def patch_object_semantics(
        self,
        object_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogObjectRecord | None:
        with self._lock:
            obj = self._objects.get(object_id)
            if obj is None:
                return None
            kwargs: dict[str, Any] = {"updated_at": datetime.utcnow()}
            if business_name is not UNSET:
                kwargs["business_name"] = business_name
            if business_description is not UNSET:
                kwargs["business_description"] = business_description
            updated = replace(obj, **kwargs)
            self._objects[object_id] = updated
            return updated

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogColumnRecord | None:
        with self._lock:
            for oid, obj in self._objects.items():
                for idx, col in enumerate(obj.columns):
                    if col.id != column_id:
                        continue
                    kwargs: dict[str, Any] = {"updated_at": datetime.utcnow()}
                    if business_name is not UNSET:
                        kwargs["business_name"] = business_name
                    if business_description is not UNSET:
                        kwargs["business_description"] = business_description
                    new_col = replace(col, **kwargs)
                    cols = list(obj.columns)
                    cols[idx] = new_col
                    self._objects[oid] = replace(obj, columns=cols, updated_at=datetime.utcnow())
                    return new_col
            return None

    def get_join(self, join_id: str) -> CatalogJoinRecord | None:
        with self._lock:
            return self._joins.get(join_id)

    def list_joins_for_object(self, object_id: str) -> list[CatalogJoinRecord]:
        with self._lock:
            obj = self._objects.get(object_id)
            if obj is None:
                return []
            col_ids = {c.id for c in obj.columns}
            items = [
                j
                for j in self._joins.values()
                if j.from_column_id in col_ids or j.to_column_id in col_ids
            ]
            return sorted(items, key=lambda j: j.created_at)

    def upsert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
    ) -> CatalogJoinRecord:
        pair = (from_column_id, to_column_id)
        with self._lock:
            existing_id = self._join_by_pair.get(pair)
            if existing_id is not None:
                prev = self._joins[existing_id]
                updated = replace(prev, evidence=evidence)
                self._joins[existing_id] = updated
                return updated
            record = CatalogJoinRecord(
                id=new_join_id(),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                created_by_user_id=created_by_user_id,
                created_at=datetime.utcnow(),
            )
            self._joins[record.id] = record
            self._join_by_pair[pair] = record.id
            return record

    def delete_join(self, join_id: str) -> bool:
        with self._lock:
            join = self._joins.pop(join_id, None)
            if join is None:
                return False
            self._join_by_pair.pop((join.from_column_id, join.to_column_id), None)
            return True


class SqlCatalogStore:
    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
    ) -> list[CatalogObjectRecord]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            stmt = (
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == source_id)
                .options(selectinload(CatalogObjectRow.columns))
                .order_by(
                    CatalogObjectRow.schema_name,
                    CatalogObjectRow.name,
                    CatalogObjectRow.object_type,
                )
            )
            if not include_absent:
                stmt = stmt.where(CatalogObjectRow.is_present.is_(True))
            rows = session.scalars(stmt).all()
            records = [_row_to_object(r) for r in rows]
            if name_search:
                q = name_search.lower()
                records = [
                    o
                    for o in records
                    if q in o.name.lower() or q in o.schema_name.lower()
                ]
            return records

    def get_object(self, object_id: str) -> CatalogObjectRecord | None:
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            return _row_to_object(row) if row else None

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            return _row_to_column(row) if row else None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        return self.list_objects(source_id, include_absent=False)

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
    ) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow, CatalogObjectRow

        now = datetime.utcnow()
        incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in objects}

        with session_scope() as session:
            stmt = (
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == source_id)
                .options(selectinload(CatalogObjectRow.columns))
            )
            if schema_scope is not None:
                stmt = stmt.where(CatalogObjectRow.schema_name == schema_scope)
            existing_rows = list(session.scalars(stmt).all())
            existing_by_key = {
                (r.schema_name, r.name, r.object_type): r for r in existing_rows
            }

            for key, row in existing_by_key.items():
                if key not in incoming_keys:
                    row.is_present = False
                    row.last_structure_job_id = job_id
                    row.updated_at = now
                    for col in row.columns:
                        col.is_present = False
                        col.updated_at = now

            for key, incoming in incoming_keys.items():
                row = existing_by_key.get(key)
                if row is None:
                    obj = CatalogObjectRow(
                        id=incoming.id,
                        source_id=source_id,
                        object_type=incoming.object_type,
                        schema_name=incoming.schema_name,
                        name=incoming.name,
                        ddl=incoming.ddl,
                        is_present=True,
                        business_name=None,
                        business_description=None,
                        last_structure_job_id=job_id,
                        collected_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(obj)
                    for col in incoming.columns:
                        session.add(
                            CatalogColumnRow(
                                id=col.id,
                                object_id=incoming.id,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    continue

                row.ddl = incoming.ddl
                row.is_present = True
                row.last_structure_job_id = job_id
                row.collected_at = now
                row.updated_at = now
                # never touch business_name / business_description

                col_by_name = {c.name: c for c in row.columns}
                seen: set[str] = set()
                for col in incoming.columns:
                    seen.add(col.name)
                    prev = col_by_name.get(col.name)
                    if prev is None:
                        session.add(
                            CatalogColumnRow(
                                id=new_column_id(),
                                object_id=row.id,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    else:
                        prev.ordinal = col.ordinal
                        prev.data_type = col.data_type
                        prev.nullable = col.nullable
                        prev.is_present = True
                        prev.updated_at = now
                for name, prev in col_by_name.items():
                    if name not in seen:
                        prev.is_present = False
                        prev.updated_at = now
            session.flush()

    def delete_objects_for_source(self, source_id: str) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(CatalogObjectRow.source_id == source_id)
                    .options(selectinload(CatalogObjectRow.columns))
                ).all()
            )
            for row in rows:
                session.delete(row)
            session.flush()

    def patch_object_semantics(
        self,
        object_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogObjectRecord | None:
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.get(
                CatalogObjectRow,
                object_id,
                options=(selectinload(CatalogObjectRow.columns),),
            )
            if row is None:
                return None
            if business_name is not UNSET:
                row.business_name = business_name
            if business_description is not UNSET:
                row.business_description = business_description
            row.updated_at = datetime.utcnow()
            session.flush()
            return _row_to_object(row)

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
    ) -> CatalogColumnRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            if row is None:
                return None
            if business_name is not UNSET:
                row.business_name = business_name
            if business_description is not UNSET:
                row.business_description = business_description
            row.updated_at = datetime.utcnow()
            session.flush()
            return _row_to_column(row)

    def get_join(self, join_id: str) -> CatalogJoinRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            return _row_to_join(row) if row else None

    def list_joins_for_object(self, object_id: str) -> list[CatalogJoinRecord]:
        from sqlalchemy import or_, select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow, CatalogJoinRow

        with session_scope() as session:
            col_ids = list(
                session.scalars(
                    select(CatalogColumnRow.id).where(
                        CatalogColumnRow.object_id == object_id
                    )
                ).all()
            )
            if not col_ids:
                # still valid empty if object exists without columns
                return []
            rows = list(
                session.scalars(
                    select(CatalogJoinRow)
                    .where(
                        or_(
                            CatalogJoinRow.from_column_id.in_(col_ids),
                            CatalogJoinRow.to_column_id.in_(col_ids),
                        )
                    )
                    .order_by(CatalogJoinRow.created_at)
                ).all()
            )
            return [_row_to_join(r) for r in rows]

    def upsert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
    ) -> CatalogJoinRecord:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        now = datetime.utcnow()
        with session_scope() as session:
            # Prefer PG atomic upsert; fall back to select-then-write.
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                stmt = (
                    insert(CatalogJoinRow)
                    .values(
                        id=new_join_id(),
                        from_column_id=from_column_id,
                        to_column_id=to_column_id,
                        evidence=evidence,
                        created_by_user_id=created_by_user_id,
                        created_at=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_catalog_joins_from_to",
                        set_={"evidence": evidence},
                    )
                    .returning(CatalogJoinRow)
                )
                row = session.scalars(stmt).one()
                session.flush()
                return _row_to_join(row)

            existing = session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.from_column_id == from_column_id,
                    CatalogJoinRow.to_column_id == to_column_id,
                )
            ).first()
            if existing is not None:
                existing.evidence = evidence
                session.flush()
                return _row_to_join(existing)
            row = CatalogJoinRow(
                id=new_join_id(),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                created_by_user_id=created_by_user_id,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return _row_to_join(row)

    def delete_join(self, join_id: str) -> bool:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        with session_scope() as session:
            row = session.get(CatalogJoinRow, join_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


def _row_to_column(row: object) -> CatalogColumnRecord:
    from backend.metadata.models import CatalogColumnRow

    assert isinstance(row, CatalogColumnRow)
    return CatalogColumnRecord(
        id=row.id,
        object_id=row.object_id,
        name=row.name,
        ordinal=row.ordinal,
        data_type=row.data_type,
        nullable=row.nullable,
        is_present=row.is_present,
        business_name=row.business_name,
        business_description=row.business_description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_join(row: object) -> CatalogJoinRecord:
    from backend.metadata.models import CatalogJoinRow

    assert isinstance(row, CatalogJoinRow)
    return CatalogJoinRecord(
        id=row.id,
        from_column_id=row.from_column_id,
        to_column_id=row.to_column_id,
        evidence=row.evidence,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


def _row_to_object(row: object) -> CatalogObjectRecord:
    from backend.metadata.models import CatalogObjectRow

    assert isinstance(row, CatalogObjectRow)
    columns = [
        _row_to_column(c) for c in sorted(row.columns, key=lambda x: x.ordinal)
    ]
    return CatalogObjectRecord(
        id=row.id,
        source_id=row.source_id,
        object_type=row.object_type,
        schema_name=row.schema_name,
        name=row.name,
        ddl=row.ddl,
        is_present=row.is_present,
        business_name=row.business_name,
        business_description=row.business_description,
        last_structure_job_id=row.last_structure_job_id,
        collected_at=row.collected_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        columns=columns,
    )


_memory_singleton: MemoryCatalogStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_catalog_store() -> MemoryCatalogStore | SqlCatalogStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryCatalogStore()
            return _memory_singleton
    return SqlCatalogStore()


def reset_catalog_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_catalog_store.cache_clear()


class CatalogWriteAborted(Exception):
    """Raised when fail-safe or incomplete collect prevents catalog mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def apply_structure_snapshot(
    *,
    source_id: str,
    job_id: str,
    collected: list[CatalogObjectRecord],
    schema_scope: str | None,
    fail_safe_threshold: float,
) -> None:
    """Commit structure upsert/absent only after a complete successful collect.

    Fail-safe: if the fraction of currently-present in-scope objects that would
    become absent exceeds the threshold, abort without writes.
    """
    store = get_catalog_store()
    present = store.list_present_for_source(source_id)
    in_scope_present = [
        o
        for o in present
        if schema_scope is None or o.schema_name == schema_scope
    ]
    incoming_keys = {(o.schema_name, o.name, o.object_type) for o in collected}
    would_absent = [
        o
        for o in in_scope_present
        if (o.schema_name, o.name, o.object_type) not in incoming_keys
    ]
    if in_scope_present:
        ratio = len(would_absent) / len(in_scope_present)
        if ratio > fail_safe_threshold:
            raise CatalogWriteAborted(
                "JOB_FAIL_SAFE",
                f"Absent ratio {ratio:.2f} exceeds fail-safe threshold "
                f"{fail_safe_threshold:.2f}",
            )
    store.replace_structure_snapshot(
        source_id=source_id,
        job_id=job_id,
        objects=collected,
        schema_scope=schema_scope,
    )


def require_object(object_id: str) -> CatalogObjectRecord:
    record = get_catalog_store().get_object(object_id)
    if record is None:
        raise CatalogObjectNotFound()
    return record
