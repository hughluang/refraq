"""Catalog persistence package — Protocol, factory, and public re-exports."""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.metadata.catalog.join_pair import Inserted, Occupied
from backend.metadata.catalog.records import (
    UNSET,
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    new_column_id,
    new_fk_id,
    new_index_id,
    new_join_id,
    new_join_change_id,
    new_object_id,
)
from backend.metadata.catalog.store.memory import MemoryCatalogStore
from backend.metadata.catalog.store.sql import SqlCatalogStore
from backend.metadata.catalog.structure_merge import StructureRefreshPlan
from backend.metadata.errors import CatalogObjectNotFound
from backend.metadata.join_detection_jobs.reconcile import JoinDetectionPlan


class StructureWrite(Protocol):
    """Locked catalog write unit: load baseline, persist plan (no merge)."""

    @property
    def session(self) -> Session | None: ...

    def load_baseline(
        self,
    ) -> tuple[list[CatalogObjectRecord], list[CatalogJoinRecord]]: ...

    def persist_plan(self, plan: StructureRefreshPlan) -> None: ...

    def persist_join_detection_plan(self, plan: JoinDetectionPlan) -> int: ...


class CatalogReadStore(Protocol):
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

    def count_objects_for_domain(self, domain_id: str) -> int: ...


class CatalogSemanticsStore(Protocol):
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


class CatalogJoinStore(Protocol):
    def get_join(self, join_id: str) -> CatalogJoinRecord | None: ...

    def get_join_by_pair(
        self,
        from_column_id: str,
        to_column_id: str,
    ) -> CatalogJoinRecord | None: ...

    def list_joins_for_object(
        self, object_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[CatalogJoinRecord], int]: ...

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]: ...

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
    ) -> Inserted | Occupied: ...

    def update_join(
        self,
        join_id: str,
        *,
        evidence: str,
        join_kind: str,
        join_expression: str | None,
        actor_user_id: str | None,
    ) -> CatalogJoinRecord | None: ...

    def set_join_rejection(
        self,
        join_id: str,
        *,
        rejected_at: datetime | None,
        rejected_by_user_id: str | None,
        actor_user_id: str | None = None,
    ) -> CatalogJoinRecord | None: ...

    def delete_join(self, join_id: str) -> bool: ...

    def list_join_changes(
        self,
        *,
        from_column_id: str,
        to_column_id: str,
    ) -> list[Any]: ...


class CatalogStructureStore(Protocol):
    def catalog_write(
        self, source_id: str
    ) -> AbstractContextManager[StructureWrite]: ...

    def delete_objects_for_source(self, source_id: str) -> None: ...

    def recompute_locators_for_source(
        self,
        source_id: str,
        *,
        engine: str | None,
        kind: str,
        source_key: str,
    ) -> int: ...


class CatalogGraphStore(Protocol):
    """BFS Join Path needs: object/column getters, present list, all joins."""

    def get_object(self, object_id: str) -> CatalogObjectRecord | None: ...

    def get_column(self, column_id: str) -> CatalogColumnRecord | None: ...

    def list_present_for_source(self, source_id: str) -> list[CatalogObjectRecord]: ...

    def list_all_joins_for_source(self, source_id: str) -> list[CatalogJoinRecord]: ...


class CatalogStore(
    CatalogReadStore,
    CatalogSemanticsStore,
    CatalogJoinStore,
    CatalogStructureStore,
    Protocol,
):
    """Full catalog persistence (union of narrow protocols)."""


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


def require_object(object_id: str) -> CatalogObjectRecord:
    record = get_catalog_store().get_object(object_id)
    if record is None:
        raise CatalogObjectNotFound()
    return record


__all__ = [
    "UNSET",
    "CatalogWriteAborted",
    "CatalogColumnRecord",
    "CatalogForeignKeyRecord",
    "CatalogIndexRecord",
    "CatalogObjectRecord",
    "CatalogJoinRecord",
    "CatalogReadStore",
    "CatalogSemanticsStore",
    "CatalogJoinStore",
    "CatalogStructureStore",
    "CatalogGraphStore",
    "CatalogStore",
    "StructureWrite",
    "MemoryCatalogStore",
    "SqlCatalogStore",
    "get_catalog_store",
    "reset_catalog_store",
    "require_object",
    "new_object_id",
    "new_column_id",
    "new_join_id",
    "new_join_change_id",
    "new_fk_id",
    "new_index_id",
]
