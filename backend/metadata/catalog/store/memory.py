"""In-memory CatalogStore persistence adapter."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.metadata.catalog.fk_join_sync import (
    _PROTECTED_JOIN_ORIGINS,
    _fk_edges_for_object,
    _merge_fk_snapshot,
    _merge_index_snapshot,
)
from backend.metadata.catalog.identity import (
    _incoming_covers_existing,
    _match_existing_for_incoming,
    _recompute_column_locator,
    _recompute_object_locator,
)
from backend.metadata.catalog.records import (
    UNSET,
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    new_column_id,
    new_fk_id,
    new_index_id,
    new_join_id,
)
from backend.metadata.catalog.search_rank import _paginate, _search_rank

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
        business_domain_id: Any = UNSET,
        evidence_summary: Any = UNSET,
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
                "business_domain_id": business_domain_id,
                "evidence_summary": evidence_summary,
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
            if business_domain_id is not UNSET:
                from backend.metadata.business_domains.store import (
                    MemoryBusinessDomainStore,
                    get_business_domain_store,
                )

                store = get_business_domain_store()
                if isinstance(store, MemoryBusinessDomainStore):
                    store.set_object_ref(object_id, updated.business_domain_id)
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



