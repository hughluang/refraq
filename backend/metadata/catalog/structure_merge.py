"""Pure structure-refresh merge: identity, FK/index/column merge, Join Origin plan."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from backend.metadata.catalog.fk_join_sync import (
    _fk_edges_for_object,
    merge_fk_snapshot,
    merge_index_snapshot,
)
from backend.metadata.catalog.join_origin import (
    STRUCTURE_JOIN_ORIGIN,
    resolve_join_write,
)
from backend.metadata.catalog.identity import (
    _incoming_covers_existing,
    _match_existing_for_incoming,
    _recompute_column_locator,
    _recompute_object_locator,
)
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    new_column_id,
    new_fk_id,
    new_index_id,
)


@dataclass(frozen=True)
class StructureJoinUpsert:
    from_column_id: str
    to_column_id: str
    evidence: str
    join_expression: str
    origin: str = "foreign_key"
    join_kind: str = "INNER"


@dataclass(frozen=True)
class StructureRefreshPlan:
    """Narrow domain plan: records + join ops. No ORM/storage types."""

    source_id: str
    objects: tuple[CatalogObjectRecord, ...]
    delete_join_ids: tuple[str, ...]
    upsert_joins: tuple[StructureJoinUpsert, ...]


def merge_columns_snapshot(
    existing: list[CatalogColumnRecord],
    incoming: list[CatalogColumnRecord],
    *,
    object_id: str,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    object_name: str,
    now: datetime,
) -> list[CatalogColumnRecord]:
    """Merge structural column fields; preserve semantics on matched columns."""
    col_by_name = {c.name: c for c in existing}
    new_cols: list[CatalogColumnRecord] = []
    seen: set[str] = set()
    for col in incoming:
        seen.add(col.name)
        col_locator = _recompute_column_locator(
            engine=engine,
            kind=kind,
            source_key=source_key,
            schema_name=schema_name,
            object_type=object_type,
            name=object_name,
            column_name=col.name,
            field_kind=col.field_kind,
        )
        prev = col_by_name.get(col.name)
        if prev is None:
            new_cols.append(
                replace(
                    col,
                    object_id=object_id,
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
                )
            )
    for name, prev in col_by_name.items():
        if name not in seen:
            new_cols.append(replace(prev, is_present=False, updated_at=now))
    return sorted(new_cols, key=lambda c: c.ordinal)


def build_structure_refresh_plan(
    *,
    source_id: str,
    job_id: str,
    existing_objects: list[CatalogObjectRecord],
    existing_joins: list[CatalogJoinRecord],
    incoming: list[CatalogObjectRecord],
    schema_scope: str | None,
    fail_safe_threshold: float,
    engine: str | None,
    kind: str,
    source_key: str,
    now: datetime,
) -> StructureRefreshPlan:
    """Fail-safe + merge + FK join sync decisions → immutable plan (one present snapshot)."""
    incoming_keys = {
        (o.schema_name, o.name, o.object_type): o for o in incoming
    }
    in_scope_present = [
        o
        for o in existing_objects
        if o.is_present
        and (schema_scope is None or o.schema_name == schema_scope)
    ]
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

    # Working map of objects after refresh (id → record).
    by_id: dict[str, CatalogObjectRecord] = {o.id: o for o in existing_objects}
    existing_by_key = {
        (o.schema_name, o.name, o.object_type): o for o in existing_objects
    }
    touched_ids: set[str] = set()

    for old in existing_objects:
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
            columns=[replace(c, is_present=False, updated_at=now) for c in old.columns],
            foreign_keys=[replace(fk, is_present=False) for fk in old.foreign_keys],
            indexes=[replace(idx, is_present=False) for idx in old.indexes],
        )
        by_id[old.id] = updated
        touched_ids.add(old.id)

    for incoming_obj in incoming_keys.values():
        match = _match_existing_for_incoming(
            schema_name=incoming_obj.schema_name,
            name=incoming_obj.name,
            object_type=incoming_obj.object_type,
            existing_by_key=existing_by_key,
        )
        obj_locator = _recompute_object_locator(
            engine=engine,
            kind=kind,
            source_key=source_key,
            schema_name=incoming_obj.schema_name,
            object_type=incoming_obj.object_type,
            name=incoming_obj.name,
        )
        if match is None:
            cols = []
            for col in incoming_obj.columns:
                col_locator = _recompute_column_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=incoming_obj.schema_name,
                    object_type=incoming_obj.object_type,
                    name=incoming_obj.name,
                    column_name=col.name,
                    field_kind=col.field_kind,
                )
                cols.append(
                    replace(
                        col,
                        locator_key=col_locator,
                        object_id=incoming_obj.id,
                    )
                )
            fks = [
                replace(fk, id=fk.id or new_fk_id(), is_present=True)
                for fk in incoming_obj.foreign_keys
            ]
            idxs = [
                replace(idx, id=idx.id or new_index_id(), is_present=True)
                for idx in incoming_obj.indexes
            ]
            inserted = replace(
                incoming_obj,
                locator_key=obj_locator,
                columns=cols,
                foreign_keys=fks,
                indexes=idxs,
            )
            by_id[incoming_obj.id] = inserted
            touched_ids.add(incoming_obj.id)
            continue

        new_cols = merge_columns_snapshot(
            match.columns,
            incoming_obj.columns,
            object_id=match.id,
            engine=engine,
            kind=kind,
            source_key=source_key,
            schema_name=incoming_obj.schema_name,
            object_type=incoming_obj.object_type,
            object_name=incoming_obj.name,
            now=now,
        )
        fks = merge_fk_snapshot(match.foreign_keys, incoming_obj.foreign_keys)
        idxs = merge_index_snapshot(match.indexes, incoming_obj.indexes)
        updated = replace(
            match,
            locator_key=obj_locator,
            object_type=incoming_obj.object_type,
            ddl=incoming_obj.ddl,
            comment=incoming_obj.comment,
            primary_key=incoming_obj.primary_key,
            is_present=True,
            last_structure_job_id=job_id,
            collected_at=now,
            updated_at=now,
            columns=new_cols,
            foreign_keys=fks,
            indexes=idxs,
        )
        by_id[match.id] = updated
        touched_ids.add(match.id)

    final_objects = list(by_id.values())
    present = [o for o in final_objects if o.is_present and o.source_id == source_id]

    expected: dict[tuple[str, str], tuple[str, str]] = {}
    for obj in present:
        for from_id, to_id, evidence, expression in _fk_edges_for_object(
            obj, present_objects=present
        ):
            expected[(from_id, to_id)] = (evidence, expression)

    source_col_ids = {
        c.id for o in final_objects if o.source_id == source_id for c in o.columns
    }
    joins_by_pair = {
        (j.from_column_id, j.to_column_id): j for j in existing_joins
    }

    delete_ids: list[str] = []
    for join in existing_joins:
        if join.origin != "foreign_key":
            continue
        if join.from_column_id not in source_col_ids:
            continue
        pair = (join.from_column_id, join.to_column_id)
        if pair not in expected:
            delete_ids.append(join.id)

    upserts: list[StructureJoinUpsert] = []
    for (from_id, to_id), (evidence, expression) in expected.items():
        existing = joins_by_pair.get((from_id, to_id))
        existing_origin = existing.origin if existing is not None else None
        if (
            resolve_join_write(
                existing_origin=existing_origin,
                incoming_origin=STRUCTURE_JOIN_ORIGIN,
            )
            == "keep_existing"
        ):
            continue
        upserts.append(
            StructureJoinUpsert(
                from_column_id=from_id,
                to_column_id=to_id,
                evidence=evidence,
                join_expression=expression,
                origin=STRUCTURE_JOIN_ORIGIN,
            )
        )

    return StructureRefreshPlan(
        source_id=source_id,
        objects=tuple(by_id[oid] for oid in touched_ids),
        delete_join_ids=tuple(delete_ids),
        upsert_joins=tuple(upserts),
    )
