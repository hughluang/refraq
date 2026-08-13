"""In-memory CatalogStore persistence adapter."""

from __future__ import annotations

from backend.core.time import utc_now
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from backend.metadata.business_domains.store import (
    MemoryBusinessDomainStore,
    get_business_domain_store,
)
from backend.metadata.catalog.identity import _recompute_column_locator, _recompute_object_locator
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    UNSET,
    new_join_id,
)
from backend.metadata.catalog.search_rank import _paginate, _search_rank
from backend.metadata.catalog.structure_merge import StructureRefreshPlan


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

    def run_structure_refresh(
        self,
        source_id: str,
        build_plan: Callable[
            [list[CatalogObjectRecord], list[CatalogJoinRecord], datetime],
            StructureRefreshPlan,
        ],
    ) -> None:
        """Atomic load → build_plan → persist (zero merge/origin rules)."""
        with self._lock:
            objects_backup = dict(self._objects)
            joins_backup = dict(self._joins)
            join_by_pair_backup = dict(self._join_by_pair)
            try:
                existing = [
                    o for o in self._objects.values() if o.source_id == source_id
                ]
                col_ids = {c.id for o in existing for c in o.columns}
                existing_joins = [
                    j
                    for j in self._joins.values()
                    if j.from_column_id in col_ids or j.to_column_id in col_ids
                ]
                now = utc_now()
                plan = build_plan(existing, existing_joins, now)
                self._persist_structure_plan_unlocked(plan, now=now)
            except CatalogWriteAborted:
                self._objects = objects_backup
                self._joins = joins_backup
                self._join_by_pair = join_by_pair_backup
                raise

    def _persist_structure_plan_unlocked(
        self,
        plan: StructureRefreshPlan,
        *,
        now: datetime,
    ) -> None:
        for obj in plan.objects:
            self._objects[obj.id] = obj
        for jid in plan.delete_join_ids:
            join = self._joins.pop(jid, None)
            if join is not None:
                self._join_by_pair.pop(
                    (join.from_column_id, join.to_column_id), None
                )
        for upsert in plan.upsert_joins:
            pair = (upsert.from_column_id, upsert.to_column_id)
            existing_id = self._join_by_pair.get(pair)
            if existing_id is not None:
                prev = self._joins[existing_id]
                self._joins[existing_id] = replace(
                    prev,
                    evidence=upsert.evidence,
                    join_kind=upsert.join_kind,
                    join_expression=upsert.join_expression,
                    origin=upsert.origin,
                )
            else:
                record = CatalogJoinRecord(
                    id=new_join_id(),
                    from_column_id=upsert.from_column_id,
                    to_column_id=upsert.to_column_id,
                    evidence=upsert.evidence,
                    join_kind=upsert.join_kind,
                    join_expression=upsert.join_expression,
                    origin=upsert.origin,
                    created_by_user_id=None,
                    created_at=now,
                )
                self._joins[record.id] = record
                self._join_by_pair[pair] = record.id

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
            created_at=utc_now(),
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
            now = utc_now()
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
                    kwargs: dict[str, Any] = {"updated_at": utc_now()}
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
                        obj, columns=cols, updated_at=utc_now()
                    )
                    return new_col
            return None

    def get_join(self, join_id: str) -> CatalogJoinRecord | None:
        with self._lock:
            return self._joins.get(join_id)

    def get_join_by_pair(
        self,
        from_column_id: str,
        to_column_id: str,
    ) -> CatalogJoinRecord | None:
        with self._lock:
            join_id = self._join_by_pair.get((from_column_id, to_column_id))
            if join_id is None:
                return None
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

