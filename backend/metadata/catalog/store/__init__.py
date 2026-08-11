"""Catalog persistence package — Protocol, factory, and public re-exports."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Any, Protocol

from backend.core.config import get_settings
from backend.metadata.catalog.fk_join_sync import PROTECTED_JOIN_ORIGINS
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
    new_object_id,
)
from backend.metadata.catalog.store.memory import MemoryCatalogStore
from backend.metadata.catalog.store.sql import SqlCatalogStore
from backend.metadata.catalog.structure_apply import apply_structure_snapshot
from backend.metadata.errors import CatalogObjectNotFound

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

    def apply_structure_plan(
        self,
        *,
        source_id: str,
        job_id: str,
        objects: list[CatalogObjectRecord],
        schema_scope: str | None,
        fail_safe_threshold: float,
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
    "CatalogStore",
    "MemoryCatalogStore",
    "SqlCatalogStore",
    "PROTECTED_JOIN_ORIGINS",
    "apply_structure_snapshot",
    "get_catalog_store",
    "reset_catalog_store",
    "require_object",
    "new_object_id",
    "new_column_id",
    "new_join_id",
    "new_fk_id",
    "new_index_id",
]
