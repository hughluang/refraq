"""Catalog object/column store and replace writer."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.metadata.errors import CatalogObjectNotFound
from backend.metadata.locators import format_column_locator, format_object_locator

# Sentinel: field omitted from patch (distinct from explicit None).
UNSET: Any = object()

class CatalogWriteAborted(Exception):
    """Raised when fail-safe or incomplete collect prevents catalog mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message




@dataclass
class CatalogColumnRecord:
    id: str
    object_id: str
    locator_key: str
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    is_present: bool
    default_value: str | None
    comment: str | None
    business_name: str | None
    business_description: str | None
    column_semantics: dict[str, Any] | None
    enum_catalog: list[dict[str, Any]] | None
    semantic_source: str | None
    field_kind: str
    created_at: datetime
    updated_at: datetime


@dataclass
class CatalogForeignKeyRecord:
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]
    id: str | None = None
    is_present: bool = True


@dataclass
class CatalogIndexRecord:
    name: str
    columns: list[str]
    is_unique: bool
    id: str | None = None
    is_present: bool = True


@dataclass
class CatalogObjectRecord:
    id: str
    source_id: str
    locator_key: str
    object_type: str
    schema_name: str
    name: str
    ddl: str | None
    comment: str | None
    primary_key: list[str] | None
    is_present: bool
    business_name: str | None
    business_description: str | None
    object_category: str | None
    grain_description: str | None
    business_primary_key: list[str] | None
    time_semantics: dict[str, Any] | None
    status_semantics: dict[str, Any] | None
    relation_summary: dict[str, Any] | None
    business_domain: str | None
    evidence_summary: list[str] | None
    confidence: float | None
    open_questions: list[str] | None
    semantic_source: str | None
    business_semantics_ready: bool
    semantics_updated_at: datetime | None
    last_structure_job_id: str | None
    collected_at: datetime | None
    created_at: datetime
    updated_at: datetime
    columns: list[CatalogColumnRecord] = field(default_factory=list)
    foreign_keys: list[CatalogForeignKeyRecord] = field(default_factory=list)
    indexes: list[CatalogIndexRecord] = field(default_factory=list)


@dataclass
class CatalogJoinRecord:
    id: str
    from_column_id: str
    to_column_id: str
    evidence: str
    join_kind: str
    join_expression: str | None
    origin: str
    created_by_user_id: str | None
    created_at: datetime


def new_object_id() -> str:
    return f"obj_{uuid.uuid4().hex[:12]}"


def new_column_id() -> str:
    return f"col_{uuid.uuid4().hex[:12]}"


def new_join_id() -> str:
    return f"join_{uuid.uuid4().hex[:12]}"


def new_fk_id() -> str:
    return f"fk_{uuid.uuid4().hex[:12]}"


def new_index_id() -> str:
    return f"idx_{uuid.uuid4().hex[:12]}"


_PROTECTED_JOIN_ORIGINS = frozenset({"human", "mcp"})


def _dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _loads_json(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


def _search_rank(
    query: str,
    *,
    locator_key: str,
    name: str,
    schema_name: str | None = None,
    business_name: str | None = None,
    business_description: str | None = None,
) -> int | None:
    """Portable ranking: exact → prefix → name/locator/schema substring → business."""
    q = query.lower().strip()
    if not q:
        return None
    loc = (locator_key or "").lower()
    nm = (name or "").lower()
    schema = (schema_name or "").lower()
    bn = (business_name or "").lower()
    bd = (business_description or "").lower()
    if loc == q or nm == q:
        return 0
    if loc.startswith(q) or nm.startswith(q) or (schema and schema.startswith(q)):
        return 1
    if q in nm or q in loc or (schema and q in schema):
        return 2
    if (bn and q in bn) or (bd and q in bd):
        return 3
    return None


def _merge_fk_snapshot(
    existing: list[CatalogForeignKeyRecord],
    incoming: list[CatalogForeignKeyRecord],
) -> list[CatalogForeignKeyRecord]:
    by_name = {fk.name: fk for fk in existing}
    seen: set[str] = set()
    out: list[CatalogForeignKeyRecord] = []
    for fk in incoming:
        seen.add(fk.name)
        prev = by_name.get(fk.name)
        if prev is None:
            out.append(
                CatalogForeignKeyRecord(
                    id=new_fk_id(),
                    name=fk.name,
                    columns=list(fk.columns),
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns=list(fk.ref_columns),
                    is_present=True,
                )
            )
        else:
            out.append(
                replace(
                    prev,
                    columns=list(fk.columns),
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns=list(fk.ref_columns),
                    is_present=True,
                )
            )
    for name, prev in by_name.items():
        if name not in seen:
            out.append(replace(prev, is_present=False))
    return out


def _merge_index_snapshot(
    existing: list[CatalogIndexRecord],
    incoming: list[CatalogIndexRecord],
) -> list[CatalogIndexRecord]:
    by_name = {idx.name: idx for idx in existing}
    seen: set[str] = set()
    out: list[CatalogIndexRecord] = []
    for idx in incoming:
        seen.add(idx.name)
        prev = by_name.get(idx.name)
        if prev is None:
            out.append(
                CatalogIndexRecord(
                    id=new_index_id(),
                    name=idx.name,
                    columns=list(idx.columns),
                    is_unique=idx.is_unique,
                    is_present=True,
                )
            )
        else:
            out.append(
                replace(
                    prev,
                    columns=list(idx.columns),
                    is_unique=idx.is_unique,
                    is_present=True,
                )
            )
    for name, prev in by_name.items():
        if name not in seen:
            out.append(replace(prev, is_present=False))
    return out


def _paginate(
    items: list[Any], *, limit: int | None, offset: int
) -> list[Any]:
    start = max(0, offset)
    if limit is None:
        return items[start:]
    return items[start : start + max(0, limit)]


class CatalogStore(Protocol):
    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
        object_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]: ...

    def search_objects(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]: ...

    def search_columns(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogColumnRecord], int]: ...

    def get_object(self, object_id: str) -> CatalogObjectRecord | None: ...

    def get_object_by_locator(self, locator_key: str) -> CatalogObjectRecord | None: ...

    def get_column(self, column_id: str) -> CatalogColumnRecord | None: ...

    def get_column_by_locator(self, locator_key: str) -> CatalogColumnRecord | None: ...

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]: ...

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> None: ...

    def delete_objects_for_source(self, source_id: str) -> None: ...

    def patch_object_semantics(
        self,
        object_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        object_category: Any = UNSET,
        grain_description: Any = UNSET,
        business_primary_key: Any = UNSET,
        time_semantics: Any = UNSET,
        status_semantics: Any = UNSET,
        relation_summary: Any = UNSET,
        business_domain: Any = UNSET,
        evidence_summary: Any = UNSET,
        confidence: Any = UNSET,
        open_questions: Any = UNSET,
        semantic_source: Any = UNSET,
        business_semantics_ready: Any = UNSET,
    ) -> CatalogObjectRecord | None: ...

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        column_semantics: Any = UNSET,
        enum_catalog: Any = UNSET,
        semantic_source: Any = UNSET,
        field_kind: Any = UNSET,
    ) -> CatalogColumnRecord | None: ...

    def get_join(self, join_id: str) -> CatalogJoinRecord | None: ...

    def list_joins_for_object(self, object_id: str) -> list[CatalogJoinRecord]: ...

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]: ...

    def upsert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
        join_kind: str = "INNER",
        join_expression: str | None = None,
        origin: str = "human",
    ) -> CatalogJoinRecord: ...

    def delete_join(self, join_id: str) -> bool: ...

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int: ...


# view ↔ materialized_view may be the same physical object across connector versions.
_VIEW_TYPE_TRANSITION = frozenset({"view", "materialized_view"})


def _natural_key(
    schema_name: str, name: str, object_type: str
) -> tuple[str, str, str]:
    return (schema_name, name, object_type)


def _is_view_type_transition(a: str, b: str) -> bool:
    return (
        a != b
        and a in _VIEW_TYPE_TRANSITION
        and b in _VIEW_TYPE_TRANSITION
    )


def _incoming_covers_existing(
    *,
    existing_schema: str,
    existing_name: str,
    existing_type: str,
    incoming_keys: dict[tuple[str, str, str], Any],
) -> bool:
    """True when an incoming object claims this existing identity (exact or type transition)."""
    exact = _natural_key(existing_schema, existing_name, existing_type)
    if exact in incoming_keys:
        return True
    if existing_type not in _VIEW_TYPE_TRANSITION:
        return False
    for (schema, name, otype) in incoming_keys:
        if (
            schema == existing_schema
            and name == existing_name
            and _is_view_type_transition(existing_type, otype)
        ):
            return True
    return False


def _match_existing_for_incoming(
    *,
    schema_name: str,
    name: str,
    object_type: str,
    existing_by_key: dict[tuple[str, str, str], Any],
) -> Any | None:
    exact = _natural_key(schema_name, name, object_type)
    match = existing_by_key.get(exact)
    if match is not None:
        return match
    if object_type not in _VIEW_TYPE_TRANSITION:
        return None
    candidates = [
        row
        for (schema, n, otype), row in existing_by_key.items()
        if schema == schema_name
        and n == name
        and _is_view_type_transition(otype, object_type)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise CatalogWriteAborted(
            "JOB_STRUCTURE_IDENTITY_AMBIGUOUS",
            f"Ambiguous view/materialized_view identity for "
            f"{schema_name}.{name}",
        )
    return None


def _recompute_object_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
) -> str:
    return format_object_locator(
        engine=engine,
        kind=kind,
        source_key=source_key,
        schema_name=schema_name,
        object_type=object_type,
        name=name,
    )


def _recompute_column_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
    column_name: str,
    field_kind: str,
) -> str:
    return format_column_locator(
        engine=engine,
        kind=kind,
        source_key=source_key,
        schema_name=schema_name,
        object_type=object_type,
        name=name,
        column_name=column_name,
        field_kind=field_kind or "column",
    )


def _present_table_candidates(
    objects: list[CatalogObjectRecord],
    *,
    source_id: str,
    ref_schema: str,
    ref_table: str,
) -> list[CatalogObjectRecord]:
    return [
        o
        for o in objects
        if o.source_id == source_id
        and o.is_present
        and o.schema_name == ref_schema
        and o.name == ref_table
        and o.object_type == "table"
    ]


def _fk_edges_for_object(
    obj: CatalogObjectRecord,
    *,
    present_objects: list[CatalogObjectRecord],
) -> list[tuple[str, str, str, str]]:
    """Resolve present FK edges; each item is (from_id, to_id, evidence, expression)."""
    edges: list[tuple[str, str, str, str]] = []
    col_by_name = {c.name: c for c in obj.columns if c.is_present}
    for fk in obj.foreign_keys:
        if not fk.is_present:
            continue
        if len(fk.columns) != len(fk.ref_columns):
            raise CatalogWriteAborted(
                "JOB_FK_COLUMN_MISMATCH",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} has unequal "
                f"local/ref column counts",
            )
        refs = _present_table_candidates(
            present_objects,
            source_id=obj.source_id,
            ref_schema=fk.ref_schema,
            ref_table=fk.ref_table,
        )
        if not refs:
            raise CatalogWriteAborted(
                "JOB_FK_UNRESOLVED",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} references "
                f"missing table {fk.ref_schema}.{fk.ref_table}",
            )
        if len(refs) > 1:
            raise CatalogWriteAborted(
                "JOB_FK_AMBIGUOUS",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} matches multiple "
                f"tables named {fk.ref_schema}.{fk.ref_table}",
            )
        ref_obj = refs[0]
        ref_cols = {c.name: c for c in ref_obj.columns if c.is_present}
        for from_name, to_name in zip(fk.columns, fk.ref_columns, strict=True):
            from_col = col_by_name.get(from_name)
            to_col = ref_cols.get(to_name)
            if from_col is None or to_col is None:
                raise CatalogWriteAborted(
                    "JOB_FK_UNRESOLVED",
                    f"FK {fk.name} on {obj.schema_name}.{obj.name} cannot resolve "
                    f"columns {from_name}->{to_name}",
                )
            evidence = f"FK {fk.name}"
            expression = f"{from_col.name} = {to_col.name}"
            edges.append((from_col.id, to_col.id, evidence, expression))
    return edges


def _validate_present_fk_graph(present_objects: list[CatalogObjectRecord]) -> None:
    for obj in present_objects:
        _fk_edges_for_object(obj, present_objects=present_objects)


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
        object_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
        with self._lock:
            items = [o for o in self._objects.values() if o.source_id == source_id]
            if not include_absent:
                items = [o for o in items if o.is_present]
            if object_type is not None:
                items = [o for o in items if o.object_type == object_type]
            if name_search:
                q = name_search.lower()
                items = [
                    o
                    for o in items
                    if q in o.name.lower() or q in o.schema_name.lower()
                ]
            items = sorted(items, key=lambda o: (o.schema_name, o.name, o.object_type))
            total = len(items)
            return _paginate(items, limit=limit, offset=offset), total

    def search_objects(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
        with self._lock:
            ranked: list[tuple[int, CatalogObjectRecord]] = []
            for obj in self._objects.values():
                if source_id is not None and obj.source_id != source_id:
                    continue
                if object_type is not None and obj.object_type != object_type:
                    continue
                if not include_absent and not obj.is_present:
                    continue
                rank = _search_rank(
                    query,
                    locator_key=obj.locator_key,
                    name=obj.name,
                    schema_name=obj.schema_name,
                    business_name=obj.business_name,
                    business_description=obj.business_description,
                )
                if rank is None:
                    continue
                ranked.append((rank, obj))
            ranked.sort(key=lambda t: (t[0], t[1].schema_name, t[1].name, t[1].id))
            total = len(ranked)
            page = [o for _, o in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

    def search_columns(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogColumnRecord], int]:
        with self._lock:
            ranked: list[tuple[int, CatalogColumnRecord]] = []
            for obj in self._objects.values():
                if source_id is not None and obj.source_id != source_id:
                    continue
                if object_type is not None and obj.object_type != object_type:
                    continue
                for col in obj.columns:
                    if not include_absent and not col.is_present:
                        continue
                    rank = _search_rank(
                        query,
                        locator_key=col.locator_key,
                        name=col.name,
                        business_name=col.business_name,
                        business_description=col.business_description,
                    )
                    if rank is None:
                        continue
                    ranked.append((rank, col))
            ranked.sort(key=lambda t: (t[0], t[1].name, t[1].id))
            total = len(ranked)
            page = [c for _, c in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

    def get_object(self, object_id: str) -> CatalogObjectRecord | None:
        with self._lock:
            return self._objects.get(object_id)

    def get_object_by_locator(self, locator_key: str) -> CatalogObjectRecord | None:
        with self._lock:
            for obj in self._objects.values():
                if obj.locator_key == locator_key:
                    return obj
            return None

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        with self._lock:
            for obj in self._objects.values():
                for col in obj.columns:
                    if col.id == column_id:
                        return col
            return None

    def get_column_by_locator(self, locator_key: str) -> CatalogColumnRecord | None:
        with self._lock:
            for obj in self._objects.values():
                for col in obj.columns:
                    if col.locator_key == locator_key:
                        return col
            return None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        items, _ = self.list_objects(source_id, include_absent=False)
        return items

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> None:
        now = datetime.utcnow()
        with self._lock:
            objects_backup = dict(self._objects)
            joins_backup = dict(self._joins)
            join_by_pair_backup = dict(self._join_by_pair)
            try:
                self._replace_structure_snapshot_unlocked(
                    source_id=source_id,
                    job_id=job_id,
                    objects=objects,
                    schema_scope=schema_scope,
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    now=now,
                )
            except CatalogWriteAborted:
                self._objects = objects_backup
                self._joins = joins_backup
                self._join_by_pair = join_by_pair_backup
                raise

    def _replace_structure_snapshot_unlocked(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        engine: str | None,
        kind: str,
        source_key: str,
        now: datetime,
    ) -> None:
        incoming_keys = {
        (o.schema_name, o.name, o.object_type): o for o in objects
        }
        existing = [
            o for o in self._objects.values() if o.source_id == source_id
        ]
        existing_by_key = {
            (o.schema_name, o.name, o.object_type): o for o in existing
        }
        for old in existing:
            if schema_scope is not None and old.schema_name != schema_scope:
                continue
            if _incoming_covers_existing(
                existing_schema=old.schema_name,
                existing_name=old.name,
                existing_type=old.object_type,
                incoming_keys=incoming_keys,
            ):
                continue
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
            updated.foreign_keys = [
                replace(fk, is_present=False) for fk in old.foreign_keys
            ]
            updated.indexes = [
                replace(idx, is_present=False) for idx in old.indexes
            ]
            self._objects[old.id] = updated
            self._tombstone_fk_joins_unlocked(updated)

        for key, incoming in incoming_keys.items():
            match = _match_existing_for_incoming(
                schema_name=incoming.schema_name,
                name=incoming.name,
                object_type=incoming.object_type,
                existing_by_key=existing_by_key,
            )
            obj_locator = _recompute_object_locator(
                engine=engine,
                kind=kind,
                source_key=source_key,
                schema_name=incoming.schema_name,
                object_type=incoming.object_type,
                name=incoming.name,
            )
            if match is None:
                cols = []
                for col in incoming.columns:
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=incoming.schema_name,
                        object_type=incoming.object_type,
                        name=incoming.name,
                        column_name=col.name,
                        field_kind=col.field_kind,
                    )
                    cols.append(
                        replace(
                            col,
                            locator_key=col_locator,
                            object_id=incoming.id,
                        )
                    )
                fks = [
                    replace(fk, id=fk.id or new_fk_id(), is_present=True)
                    for fk in incoming.foreign_keys
                ]
                idxs = [
                    replace(idx, id=idx.id or new_index_id(), is_present=True)
                    for idx in incoming.indexes
                ]
                self._objects[incoming.id] = replace(
                    incoming,
                    locator_key=obj_locator,
                    columns=cols,
                    foreign_keys=fks,
                    indexes=idxs,
                )
                continue
            # Preserve identity and semantics; refresh structure + locators
            col_by_name = {c.name: c for c in match.columns}
            new_cols: list[CatalogColumnRecord] = []
            seen_cols: set[str] = set()
            for col in incoming.columns:
                seen_cols.add(col.name)
                col_locator = _recompute_column_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=incoming.schema_name,
                    object_type=incoming.object_type,
                    name=incoming.name,
                    column_name=col.name,
                    field_kind=col.field_kind,
                )
                prev = col_by_name.get(col.name)
                if prev is None:
                    new_cols.append(
                        replace(
                            col,
                            object_id=match.id,
                            id=new_column_id(),
                            locator_key=col_locator,
                        )
                    )
                else:
                    new_cols.append(
                        replace(
                            prev,
                            locator_key=col_locator,
                            ordinal=col.ordinal,
                            data_type=col.data_type,
                            nullable=col.nullable,
                            default_value=col.default_value,
                            comment=col.comment,
                            field_kind=col.field_kind or prev.field_kind,
                            is_present=True,
                            updated_at=now,
                            # business_* and semantics preserved
                        )
                    )
            for name, prev in col_by_name.items():
                if name not in seen_cols:
                    new_cols.append(
                        replace(prev, is_present=False, updated_at=now)
                    )
            fks = _merge_fk_snapshot(match.foreign_keys, incoming.foreign_keys)
            idxs = _merge_index_snapshot(match.indexes, incoming.indexes)
            updated = replace(
                match,
                locator_key=obj_locator,
                object_type=incoming.object_type,
                ddl=incoming.ddl,
                comment=incoming.comment,
                primary_key=incoming.primary_key,
                is_present=True,
                last_structure_job_id=job_id,
                collected_at=now,
                updated_at=now,
                columns=sorted(new_cols, key=lambda c: c.ordinal),
                foreign_keys=fks,
                indexes=idxs,
                # semantics preserved on match
            )
            self._objects[match.id] = updated
            self._tombstone_fk_joins_unlocked(updated)

        # Sync FK joins after all objects are present (refs may be new).
        self._sync_fk_joins_for_source_unlocked(source_id)

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int:
        changed = 0
        with self._lock:
            for obj in list(self._objects.values()):
                if obj.source_id != source_id:
                    continue
                obj_locator = _recompute_object_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=obj.schema_name,
                    object_type=obj.object_type,
                    name=obj.name,
                )
                new_cols: list[CatalogColumnRecord] = []
                cols_changed = False
                for col in obj.columns:
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=obj.schema_name,
                        object_type=obj.object_type,
                        name=obj.name,
                        column_name=col.name,
                        field_kind=col.field_kind,
                    )
                    if col.locator_key != col_locator:
                        cols_changed = True
                        changed += 1
                        new_cols.append(replace(col, locator_key=col_locator))
                    else:
                        new_cols.append(col)
                if obj.locator_key != obj_locator or cols_changed:
                    if obj.locator_key != obj_locator:
                        changed += 1
                    self._objects[obj.id] = replace(
                        obj, locator_key=obj_locator, columns=new_cols
                    )
        return changed

    def _tombstone_fk_joins_unlocked(self, obj: CatalogObjectRecord) -> None:
        """Remove foreign_key-origin joins whose from-column belongs to this object."""
        obj_col_ids = {c.id for c in obj.columns}
        stale = [
            jid
            for jid, join in self._joins.items()
            if join.origin == "foreign_key" and join.from_column_id in obj_col_ids
        ]
        for jid in stale:
            join = self._joins.pop(jid)
            self._join_by_pair.pop((join.from_column_id, join.to_column_id), None)

    def _sync_fk_joins_for_source_unlocked(self, source_id: str) -> None:
        present = [
            o
            for o in self._objects.values()
            if o.source_id == source_id and o.is_present
        ]
        expected: dict[tuple[str, str], tuple[str, str]] = {}
        for obj in present:
            for from_id, to_id, evidence, expression in _fk_edges_for_object(
                obj, present_objects=present
            ):
                expected[(from_id, to_id)] = (evidence, expression)

        source_col_ids = {
            c.id
            for o in self._objects.values()
            if o.source_id == source_id
            for c in o.columns
        }
        stale = [
            jid
            for jid, join in self._joins.items()
            if join.origin == "foreign_key"
            and join.from_column_id in source_col_ids
            and (join.from_column_id, join.to_column_id) not in expected
        ]
        for jid in stale:
            join = self._joins.pop(jid)
            self._join_by_pair.pop((join.from_column_id, join.to_column_id), None)

        for (from_id, to_id), (evidence, expression) in expected.items():
            self._upsert_join_unlocked(
                from_column_id=from_id,
                to_column_id=to_id,
                evidence=evidence,
                created_by_user_id=None,
                join_kind="INNER",
                join_expression=expression,
                origin="foreign_key",
            )

    def _upsert_join_unlocked(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
        join_kind: str = "INNER",
        join_expression: str | None = None,
        origin: str = "human",
    ) -> CatalogJoinRecord:
        pair = (from_column_id, to_column_id)
        existing_id = self._join_by_pair.get(pair)
        if existing_id is not None:
            prev = self._joins[existing_id]
            if origin == "foreign_key" and prev.origin in _PROTECTED_JOIN_ORIGINS:
                return prev
            updated = replace(
                prev,
                evidence=evidence,
                join_kind=join_kind,
                join_expression=join_expression,
                origin=origin,
            )
            self._joins[existing_id] = updated
            return updated
        record = CatalogJoinRecord(
            id=new_join_id(),
            from_column_id=from_column_id,
            to_column_id=to_column_id,
            evidence=evidence,
            join_kind=join_kind,
            join_expression=join_expression,
            origin=origin,
            created_by_user_id=created_by_user_id,
            created_at=datetime.utcnow(),
        )
        self._joins[record.id] = record
        self._join_by_pair[pair] = record.id
        return record

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
        object_category: Any = UNSET,
        grain_description: Any = UNSET,
        business_primary_key: Any = UNSET,
        time_semantics: Any = UNSET,
        status_semantics: Any = UNSET,
        relation_summary: Any = UNSET,
        business_domain: Any = UNSET,
        evidence_summary: Any = UNSET,
        confidence: Any = UNSET,
        open_questions: Any = UNSET,
        semantic_source: Any = UNSET,
        business_semantics_ready: Any = UNSET,
    ) -> CatalogObjectRecord | None:
        with self._lock:
            obj = self._objects.get(object_id)
            if obj is None:
                return None
            now = datetime.utcnow()
            kwargs: dict[str, Any] = {
                "updated_at": now,
                "semantics_updated_at": now,
            }
            local = {
                "business_name": business_name,
                "business_description": business_description,
                "object_category": object_category,
                "grain_description": grain_description,
                "business_primary_key": business_primary_key,
                "time_semantics": time_semantics,
                "status_semantics": status_semantics,
                "relation_summary": relation_summary,
                "business_domain": business_domain,
                "evidence_summary": evidence_summary,
                "confidence": confidence,
                "open_questions": open_questions,
                "semantic_source": semantic_source,
                "business_semantics_ready": business_semantics_ready,
            }
            changed = False
            for key, value in local.items():
                if value is not UNSET:
                    kwargs[key] = value
                    changed = True
            if not changed:
                kwargs.pop("semantics_updated_at", None)
            updated = replace(obj, **kwargs)
            self._objects[object_id] = updated
            return updated

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        column_semantics: Any = UNSET,
        enum_catalog: Any = UNSET,
        semantic_source: Any = UNSET,
        field_kind: Any = UNSET,
    ) -> CatalogColumnRecord | None:
        with self._lock:
            for oid, obj in self._objects.items():
                for idx, col in enumerate(obj.columns):
                    if col.id != column_id:
                        continue
                    kwargs: dict[str, Any] = {"updated_at": datetime.utcnow()}
                    local = {
                        "business_name": business_name,
                        "business_description": business_description,
                        "column_semantics": column_semantics,
                        "enum_catalog": enum_catalog,
                        "semantic_source": semantic_source,
                        "field_kind": field_kind,
                    }
                    for key, value in local.items():
                        if value is not UNSET:
                            kwargs[key] = value
                    new_col = replace(col, **kwargs)
                    cols = list(obj.columns)
                    cols[idx] = new_col
                    self._objects[oid] = replace(
                        obj, columns=cols, updated_at=datetime.utcnow()
                    )
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

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]:
        with self._lock:
            col_ids: set[str] = set()
            for obj in self._objects.values():
                if obj.source_id != source_id:
                    continue
                for col in obj.columns:
                    col_ids.add(col.id)
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
        join_kind: str = "INNER",
        join_expression: str | None = None,
        origin: str = "human",
    ) -> CatalogJoinRecord:
        with self._lock:
            return self._upsert_join_unlocked(
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                created_by_user_id=created_by_user_id,
                join_kind=join_kind,
                join_expression=join_expression,
                origin=origin,
            )

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
        object_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
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
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            rows = session.scalars(stmt).all()
            records = [_row_to_object(r) for r in rows]
            if name_search:
                q = name_search.lower()
                records = [
                    o
                    for o in records
                    if q in o.name.lower() or q in o.schema_name.lower()
                ]
            total = len(records)
            return _paginate(records, limit=limit, offset=offset), total

    def search_objects(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            stmt = select(CatalogObjectRow).options(
                selectinload(CatalogObjectRow.columns)
            )
            if source_id is not None:
                stmt = stmt.where(CatalogObjectRow.source_id == source_id)
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            if not include_absent:
                stmt = stmt.where(CatalogObjectRow.is_present.is_(True))
            rows = session.scalars(stmt).all()
            ranked: list[tuple[int, CatalogObjectRecord]] = []
            for row in rows:
                obj = _row_to_object(row)
                rank = _search_rank(
                    query,
                    locator_key=obj.locator_key,
                    name=obj.name,
                    schema_name=obj.schema_name,
                    business_name=obj.business_name,
                    business_description=obj.business_description,
                )
                if rank is None:
                    continue
                ranked.append((rank, obj))
            ranked.sort(key=lambda t: (t[0], t[1].schema_name, t[1].name, t[1].id))
            total = len(ranked)
            page = [o for _, o in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

    def search_columns(
        self,
        query: str,
        *,
        source_id: str | None = None,
        object_type: str | None = None,
        include_absent: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogColumnRecord], int]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            stmt = select(CatalogObjectRow).options(
                selectinload(CatalogObjectRow.columns)
            )
            if source_id is not None:
                stmt = stmt.where(CatalogObjectRow.source_id == source_id)
            if object_type is not None:
                stmt = stmt.where(CatalogObjectRow.object_type == object_type)
            rows = session.scalars(stmt).all()
            ranked: list[tuple[int, CatalogColumnRecord]] = []
            for row in rows:
                obj = _row_to_object(row)
                for col in obj.columns:
                    if not include_absent and not col.is_present:
                        continue
                    rank = _search_rank(
                        query,
                        locator_key=col.locator_key,
                        name=col.name,
                        business_name=col.business_name,
                        business_description=col.business_description,
                    )
                    if rank is None:
                        continue
                    ranked.append((rank, col))
            ranked.sort(key=lambda t: (t[0], t[1].name, t[1].id))
            total = len(ranked)
            page = [c for _, c in _paginate(ranked, limit=limit, offset=offset)]
            return page, total

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

    def get_object_by_locator(self, locator_key: str) -> CatalogObjectRecord | None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        with session_scope() as session:
            row = session.scalars(
                select(CatalogObjectRow)
                .where(CatalogObjectRow.locator_key == locator_key)
                .options(selectinload(CatalogObjectRow.columns))
            ).first()
            return _row_to_object(row) if row else None

    def get_column(self, column_id: str) -> CatalogColumnRecord | None:
        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.get(CatalogColumnRow, column_id)
            return _row_to_column(row) if row else None

    def get_column_by_locator(self, locator_key: str) -> CatalogColumnRecord | None:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogColumnRow

        with session_scope() as session:
            row = session.scalars(
                select(CatalogColumnRow).where(
                    CatalogColumnRow.locator_key == locator_key
                )
            ).first()
            return _row_to_column(row) if row else None

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]:
        items, _ = self.list_objects(source_id, include_absent=False)
        return items

    def replace_structure_snapshot(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import (
            CatalogColumnRow,
            CatalogForeignKeyRow,
            CatalogIndexRow,
            CatalogObjectRow,
        )

        now = datetime.utcnow()
        incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in objects}

        with session_scope() as session:
            stmt = (
                select(CatalogObjectRow)
                .where(CatalogObjectRow.source_id == source_id)
                .options(
                    selectinload(CatalogObjectRow.columns),
                    selectinload(CatalogObjectRow.foreign_keys),
                    selectinload(CatalogObjectRow.indexes),
                )
            )
            if schema_scope is not None:
                stmt = stmt.where(CatalogObjectRow.schema_name == schema_scope)
            existing_rows = list(session.scalars(stmt).all())
            existing_by_key = {
                (r.schema_name, r.name, r.object_type): r for r in existing_rows
            }

            for key, row in list(existing_by_key.items()):
                if _incoming_covers_existing(
                    existing_schema=row.schema_name,
                    existing_name=row.name,
                    existing_type=row.object_type,
                    incoming_keys=incoming_keys,
                ):
                    continue
                row.is_present = False
                row.last_structure_job_id = job_id
                row.updated_at = now
                for col in row.columns:
                    col.is_present = False
                    col.updated_at = now
                for fk in row.foreign_keys:
                    fk.is_present = False
                    fk.updated_at = now
                for idx in row.indexes:
                    idx.is_present = False
                    idx.updated_at = now
                _sql_tombstone_fk_joins(session, row)

            touched_object_ids: list[str] = []
            for key, incoming in incoming_keys.items():
                obj_locator = _recompute_object_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=incoming.schema_name,
                    object_type=incoming.object_type,
                    name=incoming.name,
                )
                row = _match_existing_for_incoming(
                    schema_name=incoming.schema_name,
                    name=incoming.name,
                    object_type=incoming.object_type,
                    existing_by_key=existing_by_key,
                )
                if row is None:
                    obj = CatalogObjectRow(
                        id=incoming.id,
                        source_id=source_id,
                        locator_key=obj_locator,
                        object_type=incoming.object_type,
                        schema_name=incoming.schema_name,
                        name=incoming.name,
                        ddl=incoming.ddl,
                        comment=incoming.comment,
                        primary_key_json=_dumps_json(incoming.primary_key),
                        is_present=True,
                        business_name=None,
                        business_description=None,
                        object_category=None,
                        grain_description=None,
                        business_primary_key_json=None,
                        time_semantics_json=None,
                        status_semantics_json=None,
                        relation_summary_json=None,
                        business_domain=None,
                        evidence_summary_json=None,
                        confidence=None,
                        open_questions_json=None,
                        semantic_source=None,
                        business_semantics_ready=False,
                        semantics_updated_at=None,
                        last_structure_job_id=job_id,
                        collected_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(obj)
                    for col in incoming.columns:
                        col_locator = _recompute_column_locator(
                            engine=engine,
                            kind=kind,
                            source_key=source_key,
                            schema_name=incoming.schema_name,
                            object_type=incoming.object_type,
                            name=incoming.name,
                            column_name=col.name,
                            field_kind=col.field_kind,
                        )
                        session.add(
                            CatalogColumnRow(
                                id=col.id,
                                object_id=incoming.id,
                                locator_key=col_locator,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                default_value=col.default_value,
                                comment=col.comment,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                column_semantics_json=None,
                                enum_catalog_json=None,
                                semantic_source=None,
                                field_kind=col.field_kind or "column",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    for fk in incoming.foreign_keys:
                        session.add(
                            CatalogForeignKeyRow(
                                id=new_fk_id(),
                                object_id=incoming.id,
                                name=fk.name,
                                columns_json=_dumps_json(fk.columns) or "[]",
                                ref_schema=fk.ref_schema,
                                ref_table=fk.ref_table,
                                ref_columns_json=_dumps_json(fk.ref_columns) or "[]",
                                is_present=True,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    for idx in incoming.indexes:
                        session.add(
                            CatalogIndexRow(
                                id=new_index_id(),
                                object_id=incoming.id,
                                name=idx.name,
                                columns_json=_dumps_json(idx.columns) or "[]",
                                is_unique=idx.is_unique,
                                is_present=True,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    touched_object_ids.append(incoming.id)
                    continue

                row.locator_key = obj_locator
                row.object_type = incoming.object_type
                row.ddl = incoming.ddl
                row.comment = incoming.comment
                row.primary_key_json = _dumps_json(incoming.primary_key)
                row.is_present = True
                row.last_structure_job_id = job_id
                row.collected_at = now
                row.updated_at = now
                # never touch semantics fields

                col_by_name = {c.name: c for c in row.columns}
                seen: set[str] = set()
                for col in incoming.columns:
                    seen.add(col.name)
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=incoming.schema_name,
                        object_type=incoming.object_type,
                        name=incoming.name,
                        column_name=col.name,
                        field_kind=col.field_kind,
                    )
                    prev = col_by_name.get(col.name)
                    if prev is None:
                        session.add(
                            CatalogColumnRow(
                                id=new_column_id(),
                                object_id=row.id,
                                locator_key=col_locator,
                                name=col.name,
                                ordinal=col.ordinal,
                                data_type=col.data_type,
                                nullable=col.nullable,
                                default_value=col.default_value,
                                comment=col.comment,
                                is_present=True,
                                business_name=None,
                                business_description=None,
                                column_semantics_json=None,
                                enum_catalog_json=None,
                                semantic_source=None,
                                field_kind=col.field_kind or "column",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    else:
                        prev.locator_key = col_locator
                        prev.ordinal = col.ordinal
                        prev.data_type = col.data_type
                        prev.nullable = col.nullable
                        prev.default_value = col.default_value
                        prev.comment = col.comment
                        prev.field_kind = col.field_kind or prev.field_kind
                        prev.is_present = True
                        prev.updated_at = now
                for name, prev in col_by_name.items():
                    if name not in seen:
                        prev.is_present = False
                        prev.updated_at = now

                _sql_upsert_fks(session, row, incoming.foreign_keys, now=now)
                _sql_upsert_indexes(session, row, incoming.indexes, now=now)
                _sql_tombstone_fk_joins(session, row)
                touched_object_ids.append(row.id)

            session.flush()

            # Sync FK joins for the whole Source after structure is present.
            _sql_sync_fk_joins_for_source(session, source_id=source_id, now=now)
            session.flush()

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogObjectRow

        changed = 0
        with session_scope() as session:
            rows = list(
                session.scalars(
                    select(CatalogObjectRow)
                    .where(CatalogObjectRow.source_id == source_id)
                    .options(selectinload(CatalogObjectRow.columns))
                ).all()
            )
            for row in rows:
                obj_locator = _recompute_object_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=row.schema_name,
                    object_type=row.object_type,
                    name=row.name,
                )
                if row.locator_key != obj_locator:
                    row.locator_key = obj_locator
                    changed += 1
                for col in row.columns:
                    col_locator = _recompute_column_locator(
                        engine=engine,
                        kind=kind,
                        source_key=source_key,
                        schema_name=row.schema_name,
                        object_type=row.object_type,
                        name=row.name,
                        column_name=col.name,
                        field_kind=col.field_kind or "column",
                    )
                    if col.locator_key != col_locator:
                        col.locator_key = col_locator
                        changed += 1
            session.flush()
        return changed

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
        object_category: Any = UNSET,
        grain_description: Any = UNSET,
        business_primary_key: Any = UNSET,
        time_semantics: Any = UNSET,
        status_semantics: Any = UNSET,
        relation_summary: Any = UNSET,
        business_domain: Any = UNSET,
        evidence_summary: Any = UNSET,
        confidence: Any = UNSET,
        open_questions: Any = UNSET,
        semantic_source: Any = UNSET,
        business_semantics_ready: Any = UNSET,
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
            now = datetime.utcnow()
            changed = False
            if business_name is not UNSET:
                row.business_name = business_name
                changed = True
            if business_description is not UNSET:
                row.business_description = business_description
                changed = True
            if object_category is not UNSET:
                row.object_category = object_category
                changed = True
            if grain_description is not UNSET:
                row.grain_description = grain_description
                changed = True
            if business_primary_key is not UNSET:
                row.business_primary_key_json = _dumps_json(business_primary_key)
                changed = True
            if time_semantics is not UNSET:
                row.time_semantics_json = _dumps_json(time_semantics)
                changed = True
            if status_semantics is not UNSET:
                row.status_semantics_json = _dumps_json(status_semantics)
                changed = True
            if relation_summary is not UNSET:
                row.relation_summary_json = _dumps_json(relation_summary)
                changed = True
            if business_domain is not UNSET:
                row.business_domain = business_domain
                changed = True
            if evidence_summary is not UNSET:
                row.evidence_summary_json = _dumps_json(evidence_summary)
                changed = True
            if confidence is not UNSET:
                row.confidence = confidence
                changed = True
            if open_questions is not UNSET:
                row.open_questions_json = _dumps_json(open_questions)
                changed = True
            if semantic_source is not UNSET:
                row.semantic_source = semantic_source
                changed = True
            if business_semantics_ready is not UNSET:
                row.business_semantics_ready = business_semantics_ready
                changed = True
            row.updated_at = now
            if changed:
                row.semantics_updated_at = now
            session.flush()
            return _row_to_object(row)

    def patch_column_semantics(
        self,
        column_id: str,
        *,
        business_name: Any = UNSET,
        business_description: Any = UNSET,
        column_semantics: Any = UNSET,
        enum_catalog: Any = UNSET,
        semantic_source: Any = UNSET,
        field_kind: Any = UNSET,
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
            if column_semantics is not UNSET:
                row.column_semantics_json = _dumps_json(column_semantics)
            if enum_catalog is not UNSET:
                row.enum_catalog_json = _dumps_json(enum_catalog)
            if semantic_source is not UNSET:
                row.semantic_source = semantic_source
            if field_kind is not UNSET:
                row.field_kind = field_kind
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

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]:
        from sqlalchemy import or_, select

        from backend.core.db import session_scope
        from backend.metadata.models import (
            CatalogColumnRow,
            CatalogJoinRow,
            CatalogObjectRow,
        )

        with session_scope() as session:
            col_ids = list(
                session.scalars(
                    select(CatalogColumnRow.id)
                    .join(
                        CatalogObjectRow,
                        CatalogColumnRow.object_id == CatalogObjectRow.id,
                    )
                    .where(CatalogObjectRow.source_id == source_id)
                ).all()
            )
            if not col_ids:
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
        join_kind: str = "INNER",
        join_expression: str | None = None,
        origin: str = "human",
    ) -> CatalogJoinRecord:
        from sqlalchemy import select

        from backend.core.db import session_scope
        from backend.metadata.models import CatalogJoinRow

        now = datetime.utcnow()
        with session_scope() as session:
            existing = session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.from_column_id == from_column_id,
                    CatalogJoinRow.to_column_id == to_column_id,
                )
            ).first()
            if existing is not None:
                if origin == "foreign_key" and existing.origin in _PROTECTED_JOIN_ORIGINS:
                    return _row_to_join(existing)
                existing.evidence = evidence
                existing.join_kind = join_kind
                existing.join_expression = join_expression
                existing.origin = origin
                session.flush()
                return _row_to_join(existing)
            row = CatalogJoinRow(
                id=new_join_id(),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                join_kind=join_kind,
                join_expression=join_expression,
                origin=origin,
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


def _sql_upsert_fks(
    session: Any,
    row: Any,
    incoming: list[CatalogForeignKeyRecord],
    *,
    now: datetime,
) -> None:
    from backend.metadata.models import CatalogForeignKeyRow

    by_name = {fk.name: fk for fk in row.foreign_keys}
    seen: set[str] = set()
    for fk in incoming:
        seen.add(fk.name)
        prev = by_name.get(fk.name)
        if prev is None:
            session.add(
                CatalogForeignKeyRow(
                    id=new_fk_id(),
                    object_id=row.id,
                    name=fk.name,
                    columns_json=_dumps_json(fk.columns) or "[]",
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns_json=_dumps_json(fk.ref_columns) or "[]",
                    is_present=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.columns_json = _dumps_json(fk.columns) or "[]"
            prev.ref_schema = fk.ref_schema
            prev.ref_table = fk.ref_table
            prev.ref_columns_json = _dumps_json(fk.ref_columns) or "[]"
            prev.is_present = True
            prev.updated_at = now
    for name, prev in by_name.items():
        if name not in seen:
            prev.is_present = False
            prev.updated_at = now


def _sql_upsert_indexes(
    session: Any,
    row: Any,
    incoming: list[CatalogIndexRecord],
    *,
    now: datetime,
) -> None:
    from backend.metadata.models import CatalogIndexRow

    by_name = {idx.name: idx for idx in row.indexes}
    seen: set[str] = set()
    for idx in incoming:
        seen.add(idx.name)
        prev = by_name.get(idx.name)
        if prev is None:
            session.add(
                CatalogIndexRow(
                    id=new_index_id(),
                    object_id=row.id,
                    name=idx.name,
                    columns_json=_dumps_json(idx.columns) or "[]",
                    is_unique=idx.is_unique,
                    is_present=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            prev.columns_json = _dumps_json(idx.columns) or "[]"
            prev.is_unique = idx.is_unique
            prev.is_present = True
            prev.updated_at = now
    for name, prev in by_name.items():
        if name not in seen:
            prev.is_present = False
            prev.updated_at = now


def _sql_tombstone_fk_joins(session: Any, row: Any) -> None:
    """Remove foreign_key-origin joins whose from-column belongs to this object."""
    from sqlalchemy import select

    from backend.metadata.models import CatalogJoinRow

    col_ids = [c.id for c in row.columns]
    if not col_ids:
        return
    joins = list(
        session.scalars(
            select(CatalogJoinRow).where(
                CatalogJoinRow.origin == "foreign_key",
                CatalogJoinRow.from_column_id.in_(col_ids),
            )
        ).all()
    )
    for join in joins:
        session.delete(join)


def _sql_sync_fk_joins_for_source(
    session: Any, *, source_id: str, now: datetime
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from backend.metadata.models import CatalogJoinRow, CatalogObjectRow

    rows = list(
        session.scalars(
            select(CatalogObjectRow)
            .where(CatalogObjectRow.source_id == source_id)
            .options(
                selectinload(CatalogObjectRow.columns),
                selectinload(CatalogObjectRow.foreign_keys),
            )
        ).all()
    )
    present_records = [_row_to_object(r) for r in rows if r.is_present]
    expected: dict[tuple[str, str], tuple[str, str]] = {}
    for obj in present_records:
        for from_id, to_id, evidence, expression in _fk_edges_for_object(
            obj, present_objects=present_records
        ):
            expected[(from_id, to_id)] = (evidence, expression)

    source_col_ids = {c.id for r in rows for c in r.columns}
    if source_col_ids:
        joins = list(
            session.scalars(
                select(CatalogJoinRow).where(
                    CatalogJoinRow.origin == "foreign_key",
                    CatalogJoinRow.from_column_id.in_(source_col_ids),
                )
            ).all()
        )
        for join in joins:
            if (join.from_column_id, join.to_column_id) not in expected:
                session.delete(join)

    for (from_id, to_id), (evidence, expression) in expected.items():
        existing = session.scalars(
            select(CatalogJoinRow).where(
                CatalogJoinRow.from_column_id == from_id,
                CatalogJoinRow.to_column_id == to_id,
            )
        ).first()
        if existing is not None:
            if existing.origin in _PROTECTED_JOIN_ORIGINS:
                continue
            existing.evidence = evidence
            existing.join_kind = "INNER"
            existing.join_expression = expression
            existing.origin = "foreign_key"
        else:
            session.add(
                CatalogJoinRow(
                    id=new_join_id(),
                    from_column_id=from_id,
                    to_column_id=to_id,
                    evidence=evidence,
                    join_kind="INNER",
                    join_expression=expression,
                    origin="foreign_key",
                    created_by_user_id=None,
                    created_at=now,
                )
            )


def _row_to_column(row: object) -> CatalogColumnRecord:
    from backend.metadata.models import CatalogColumnRow

    assert isinstance(row, CatalogColumnRow)
    return CatalogColumnRecord(
        id=row.id,
        object_id=row.object_id,
        locator_key=row.locator_key,
        name=row.name,
        ordinal=row.ordinal,
        data_type=row.data_type,
        nullable=row.nullable,
        is_present=row.is_present,
        default_value=row.default_value,
        comment=row.comment,
        business_name=row.business_name,
        business_description=row.business_description,
        column_semantics=_loads_json(row.column_semantics_json),
        enum_catalog=_loads_json(row.enum_catalog_json),
        semantic_source=row.semantic_source,
        field_kind=row.field_kind,
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
        join_kind=row.join_kind,
        join_expression=row.join_expression,
        origin=row.origin,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


def _row_to_object(row: object) -> CatalogObjectRecord:
    from backend.metadata.models import CatalogObjectRow

    assert isinstance(row, CatalogObjectRow)
    columns = [
        _row_to_column(c) for c in sorted(row.columns, key=lambda x: x.ordinal)
    ]
    foreign_keys = [
        CatalogForeignKeyRecord(
            id=fk.id,
            name=fk.name,
            columns=_loads_json(fk.columns_json) or [],
            ref_schema=fk.ref_schema,
            ref_table=fk.ref_table,
            ref_columns=_loads_json(fk.ref_columns_json) or [],
            is_present=fk.is_present,
        )
        for fk in getattr(row, "foreign_keys", []) or []
    ]
    indexes = [
        CatalogIndexRecord(
            id=idx.id,
            name=idx.name,
            columns=_loads_json(idx.columns_json) or [],
            is_unique=idx.is_unique,
            is_present=idx.is_present,
        )
        for idx in getattr(row, "indexes", []) or []
    ]
    return CatalogObjectRecord(
        id=row.id,
        source_id=row.source_id,
        locator_key=row.locator_key,
        object_type=row.object_type,
        schema_name=row.schema_name,
        name=row.name,
        ddl=row.ddl,
        comment=row.comment,
        primary_key=_loads_json(row.primary_key_json),
        is_present=row.is_present,
        business_name=row.business_name,
        business_description=row.business_description,
        object_category=row.object_category,
        grain_description=row.grain_description,
        business_primary_key=_loads_json(row.business_primary_key_json),
        time_semantics=_loads_json(row.time_semantics_json),
        status_semantics=_loads_json(row.status_semantics_json),
        relation_summary=_loads_json(row.relation_summary_json),
        business_domain=row.business_domain,
        evidence_summary=_loads_json(row.evidence_summary_json),
        confidence=row.confidence,
        open_questions=_loads_json(row.open_questions_json),
        semantic_source=row.semantic_source,
        business_semantics_ready=row.business_semantics_ready,
        semantics_updated_at=row.semantics_updated_at,
        last_structure_job_id=row.last_structure_job_id,
        collected_at=row.collected_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        columns=columns,
        foreign_keys=foreign_keys,
        indexes=indexes,
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



def apply_structure_snapshot(
    *,
    source_id: str,
    job_id: str,
    collected: list[CatalogObjectRecord],
    schema_scope: str | None,
    fail_safe_threshold: float,
    engine: str | None,
    kind: str,
    source_key: str,
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
    incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in collected}
    would_absent = [
        o
        for o in in_scope_present
        if not _incoming_covers_existing(
            existing_schema=o.schema_name,
            existing_name=o.name,
            existing_type=o.object_type,
            incoming_keys=incoming_keys,
        )
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
        engine=engine,
        kind=kind,
        source_key=source_key,
    )


def require_object(object_id: str) -> CatalogObjectRecord:
    record = get_catalog_store().get_object(object_id)
    if record is None:
        raise CatalogObjectNotFound()
    return record
