"""In-memory CatalogStore persistence adapter."""

from __future__ import annotations

from backend.core.time import utc_now
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterator

from backend.core.pagination import apply_offset_page
from backend.metadata.catalog.identity import (
    _recompute_column_locator,
    _recompute_object_locator,
)
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    UNSET,
)
from backend.metadata.catalog.join_changes import (
    CatalogJoinChangeRecord,
    join_change_for_amend,
    join_change_for_rejection_toggle,
)
from backend.metadata.catalog.list_query import (
    list_object_projection,
    list_object_sort_key,
    object_matches_list_filters,
)
from backend.metadata.catalog.search_rank import _paginate, _search_rank, rank_and_page
from backend.metadata.catalog.structure_merge import StructureRefreshPlan
from backend.metadata.catalog.join_pair import Inserted, Occupied, apply_insert_join
from backend.metadata.catalog.structure_persist import (
    apply_join_detection_plan,
    apply_structure_plan,
)
from backend.metadata.join_detection_jobs.reconcile import JoinDetectionPlan


class _MemoryStructureWrite:
    def __init__(self, store: MemoryCatalogStore, source_id: str) -> None:
        self._store = store
        self._source_id = source_id

    @property
    def session(self) -> None:
        return None

    def load_baseline(
        self,
    ) -> tuple[list[CatalogObjectRecord], list[CatalogJoinRecord]]:
        existing = [
            o for o in self._store._objects.values() if o.source_id == self._source_id
        ]
        col_ids = {c.id for o in existing for c in o.columns}
        existing_joins = [
            j
            for j in self._store._joins.values()
            if j.from_column_id in col_ids or j.to_column_id in col_ids
        ]
        return existing, existing_joins

    def persist_plan(self, plan: StructureRefreshPlan) -> None:
        apply_structure_plan(_MemoryPersistPort(self._store), plan, now=utc_now())

    def persist_join_detection_plan(self, plan: JoinDetectionPlan) -> int:
        return apply_join_detection_plan(
            _MemoryPersistPort(self._store), plan, now=utc_now()
        )


class _MemoryPersistPort:
    def __init__(self, store: MemoryCatalogStore) -> None:
        self._store = store

    def get_join_by_pair(
        self, from_column_id: str, to_column_id: str
    ) -> CatalogJoinRecord | None:
        join_id = self._store._join_by_pair.get((from_column_id, to_column_id))
        if join_id is None:
            return None
        return self._store._joins[join_id]

    def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
        pair = (record.from_column_id, record.to_column_id)
        if pair in self._store._join_by_pair:
            return None
        self._store._joins[record.id] = record
        self._store._join_by_pair[pair] = record.id
        return record

    def append_join_change(self, change: CatalogJoinChangeRecord) -> None:
        self._store._join_changes.append(change)

    def put_object(self, obj: CatalogObjectRecord) -> None:
        self._store._objects[obj.id] = obj

    def stamp_objects(self, plan: StructureRefreshPlan) -> None:
        for oid in plan.stamp_object_ids:
            obj = self._store._objects[oid]
            self._store._objects[oid] = replace(
                obj,
                collected_at=plan.collected_at,
                last_structure_job_id=plan.last_structure_job_id,
            )


class MemoryCatalogStore:
    def __init__(self) -> None:
        self._objects: dict[str, CatalogObjectRecord] = {}
        self._joins: dict[str, CatalogJoinRecord] = {}
        self._join_by_pair: dict[tuple[str, str], str] = {}
        self._join_changes: list[CatalogJoinChangeRecord] = []
        self._semantics_changes: list[Any] = []
        self._embeddings: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def list_objects(
        self,
        source_id: str,
        *,
        name_search: str | None = None,
        include_absent: bool = True,
        object_type: str | None = None,
        business_semantics_ready: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[CatalogObjectRecord], int]:
        with self._lock:
            items = [
                o
                for o in self._objects.values()
                if object_matches_list_filters(
                    o,
                    source_id=source_id,
                    name_search=name_search,
                    include_absent=include_absent,
                    object_type=object_type,
                    business_semantics_ready=business_semantics_ready,
                )
            ]
            items.sort(key=list_object_sort_key)
            total = len(items)
            page = _paginate(items, limit=limit, offset=offset)
            return [list_object_projection(o) for o in page], total

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
            candidates = [
                obj
                for obj in self._objects.values()
                if (source_id is None or obj.source_id == source_id)
                and (object_type is None or obj.object_type == object_type)
                and (include_absent or obj.is_present)
            ]
            return rank_and_page(
                candidates,
                rank_of=lambda o: _search_rank(
                    query,
                    locator_key=o.locator_key,
                    name=o.name,
                    schema_name=o.schema_name,
                    business_name=o.business_name,
                    business_description=o.business_description,
                ),
                tiebreak=lambda o: (o.schema_name, o.name, o.id),
                limit=limit,
                offset=offset,
            )

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
            candidates: list[CatalogColumnRecord] = []
            for obj in self._objects.values():
                if source_id is not None and obj.source_id != source_id:
                    continue
                if object_type is not None and obj.object_type != object_type:
                    continue
                for col in obj.columns:
                    if include_absent or col.is_present:
                        candidates.append(col)
            return rank_and_page(
                candidates,
                rank_of=lambda c: _search_rank(
                    query,
                    locator_key=c.locator_key,
                    name=c.name,
                    business_name=c.business_name,
                    business_description=c.business_description,
                ),
                tiebreak=lambda c: (c.name, c.id),
                limit=limit,
                offset=offset,
            )

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
        with self._lock:
            items = [
                o
                for o in self._objects.values()
                if o.source_id == source_id and o.is_present
            ]
            return sorted(items, key=list_object_sort_key)

    def count_objects_for_domain(self, domain_id: str) -> int:
        with self._lock:
            return sum(
                1 for o in self._objects.values() if o.business_domain_id == domain_id
            )

    @contextmanager
    def catalog_write(self, source_id: str) -> Iterator[_MemoryStructureWrite]:
        """Catalog write unit (zero merge/origin rules).

        Same-kind runner serialization is the Kind execution lock (ADR 0032).
        This in-process lock only keeps one persist atomic in memory tests.
        """
        with self._lock:
            objects_backup = dict(self._objects)
            joins_backup = dict(self._joins)
            join_by_pair_backup = dict(self._join_by_pair)
            join_changes_backup = list(self._join_changes)
            semantics_changes_backup = list(self._semantics_changes)
            embeddings_backup = dict(self._embeddings)
            write = _MemoryStructureWrite(self, source_id)
            try:
                yield write
            except Exception:
                self._objects = objects_backup
                self._joins = joins_backup
                self._join_by_pair = join_by_pair_backup
                self._join_changes = join_changes_backup
                self._semantics_changes = semantics_changes_backup
                self._embeddings = embeddings_backup
                raise

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

    def delete_objects_for_source(self, source_id: str) -> None:
        with self._lock:
            col_ids: set[str] = set()
            to_drop = [
                oid for oid, obj in self._objects.items() if obj.source_id == source_id
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
                self._join_by_pair.pop((join.from_column_id, join.to_column_id), None)

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

    def list_joins_for_object(
        self, object_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[CatalogJoinRecord], int]:
        with self._lock:
            obj = self._objects.get(object_id)
            if obj is None:
                return [], 0
            col_ids = {c.id for c in obj.columns}
            items = [
                j
                for j in self._joins.values()
                if j.from_column_id in col_ids or j.to_column_id in col_ids
            ]
            items.sort(key=lambda j: (j.created_at, j.id))
            return apply_offset_page(items, limit=limit, offset=offset)

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

    def write_insert_join(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
        evidence: str,
        created_by_user_id: str | None,
        join_kind: str = "INNER",
        join_expression: str | None = None,
        attester: str,
    ) -> Inserted | Occupied:
        with self._lock:
            return apply_insert_join(
                _MemoryPersistPort(self),
                from_column_id=from_column_id,
                to_column_id=to_column_id,
                evidence=evidence,
                created_by_user_id=created_by_user_id,
                join_kind=join_kind,
                join_expression=join_expression,
                attester=attester,
                now=utc_now(),
            )

    def update_join(
        self,
        join_id: str,
        *,
        evidence: str,
        join_kind: str,
        join_expression: str | None,
        actor_user_id: str | None,
    ) -> CatalogJoinRecord | None:
        with self._lock:
            prev = self._joins.get(join_id)
            if prev is None:
                return None
            updated = replace(
                prev,
                evidence=evidence,
                join_kind=join_kind,
                join_expression=join_expression,
            )
            self._joins[join_id] = updated
            self._join_changes.append(
                join_change_for_amend(
                    from_column_id=updated.from_column_id,
                    to_column_id=updated.to_column_id,
                    created_at=utc_now(),
                    actor_user_id=actor_user_id,
                )
            )
            return updated

    def set_join_rejection(
        self,
        join_id: str,
        *,
        rejected_at: datetime | None,
        rejected_by_user_id: str | None,
        actor_user_id: str | None = None,
    ) -> CatalogJoinRecord | None:
        with self._lock:
            prev = self._joins.get(join_id)
            if prev is None:
                return None
            updated = replace(
                prev,
                rejected_at=rejected_at,
                rejected_by_user_id=rejected_by_user_id,
            )
            self._joins[join_id] = updated
            self._join_changes.append(
                join_change_for_rejection_toggle(
                    from_column_id=updated.from_column_id,
                    to_column_id=updated.to_column_id,
                    created_at=utc_now(),
                    rejected_at=rejected_at,
                    actor_user_id=actor_user_id,
                    rejected_by_user_id=rejected_by_user_id,
                )
            )
            return updated

    def list_join_changes(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
    ) -> list[CatalogJoinChangeRecord]:
        with self._lock:
            return [
                change
                for change in self._join_changes
                if change.from_column_id == from_column_id
                and change.to_column_id == to_column_id
            ]

    def delete_join(self, join_id: str) -> bool:
        with self._lock:
            join = self._joins.pop(join_id, None)
            if join is None:
                return False
            self._join_by_pair.pop((join.from_column_id, join.to_column_id), None)
            return True

    def append_semantics_change(self, change: Any) -> None:
        with self._lock:
            self._semantics_changes.append(change)

    def list_semantics_changes(
        self,
        object_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        with self._lock:
            items = [
                c for c in self._semantics_changes if c.object_id == object_id
            ]
            items.sort(key=lambda c: (c.created_at, c.id), reverse=True)
            return apply_offset_page(items, limit=limit, offset=offset)

    def upsert_embedding(self, record: Any) -> None:
        with self._lock:
            self._embeddings[(record.kind, record.target_id)] = record

    def get_embedding(self, *, kind: str, target_id: str) -> Any | None:
        with self._lock:
            return self._embeddings.get((kind, target_id))

    def list_embeddings(self, *, kind: str) -> list[Any]:
        with self._lock:
            return [r for (k, _tid), r in self._embeddings.items() if k == kind]

    def delete_embeddings(self) -> None:
        with self._lock:
            self._embeddings.clear()
