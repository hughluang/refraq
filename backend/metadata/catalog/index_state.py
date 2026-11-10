"""Catalog-owned index readiness, coverage, and rebuild intent."""

from __future__ import annotations

import threading
from dataclasses import replace
from functools import lru_cache
from typing import Protocol

from backend.admin.model_services.records import CatalogIndexView
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.models import CatalogIndexStateRow

CATALOG_INDEX_ID = "catalog"


class CatalogIndexStore(Protocol):
    def get(self) -> CatalogIndexView: ...

    def save(self, state: CatalogIndexView) -> CatalogIndexView: ...


def _row_to_view(row: CatalogIndexStateRow) -> CatalogIndexView:
    return CatalogIndexView(
        ready=row.ready,
        generation_last_swept=row.generation_last_swept,
        objects_written=row.objects_written,
        columns_written=row.columns_written,
        objects_failed=row.objects_failed,
        columns_failed=row.columns_failed,
        objects_attempted=row.objects_attempted,
        columns_attempted=row.columns_attempted,
        progress=row.progress,
        failure_summary=row.failure_summary,
        rebuild_owed=row.rebuild_owed,
    )


def _apply(row: CatalogIndexStateRow, state: CatalogIndexView) -> None:
    row.ready = state.ready
    row.generation_last_swept = state.generation_last_swept
    row.objects_written = state.objects_written
    row.columns_written = state.columns_written
    row.objects_failed = state.objects_failed
    row.columns_failed = state.columns_failed
    row.objects_attempted = state.objects_attempted
    row.columns_attempted = state.columns_attempted
    row.progress = state.progress
    row.failure_summary = state.failure_summary
    row.rebuild_owed = state.rebuild_owed


class MemoryCatalogIndexStore:
    def __init__(self) -> None:
        self._state = CatalogIndexView()
        self._lock = threading.Lock()

    def get(self) -> CatalogIndexView:
        with self._lock:
            return self._state

    def save(self, state: CatalogIndexView) -> CatalogIndexView:
        with self._lock:
            self._state = state
            return state


class SqlCatalogIndexStore:
    def get(self) -> CatalogIndexView:
        with session_scope() as session:
            row = session.get(CatalogIndexStateRow, CATALOG_INDEX_ID)
            if row is None:
                return CatalogIndexView()
            return _row_to_view(row)

    def save(self, state: CatalogIndexView) -> CatalogIndexView:
        with session_scope() as session:
            row = session.get(CatalogIndexStateRow, CATALOG_INDEX_ID)
            if row is None:
                row = CatalogIndexStateRow(id=CATALOG_INDEX_ID, ready=False)
                _apply(row, state)
                session.add(row)
            else:
                _apply(row, state)
            session.flush()
            return state


_memory: MemoryCatalogIndexStore | None = None
_lock = threading.Lock()


@lru_cache
def get_catalog_index_store() -> CatalogIndexStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryCatalogIndexStore()
            return _memory
    return SqlCatalogIndexStore()


def reset_catalog_index_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_catalog_index_store.cache_clear()


def publish_catalog_index(
    *,
    generation: int,
    objects_written: int = 0,
    columns_written: int = 0,
    objects_failed: int = 0,
    columns_failed: int = 0,
    objects_attempted: int = 0,
    columns_attempted: int = 0,
    progress: str | None = None,
    failure_summary: str | None = None,
) -> CatalogIndexView:
    state = CatalogIndexView(
        ready=True,
        generation_last_swept=generation,
        objects_written=objects_written,
        columns_written=columns_written,
        objects_failed=objects_failed,
        columns_failed=columns_failed,
        objects_attempted=objects_attempted,
        columns_attempted=columns_attempted,
        progress=progress,
        failure_summary=failure_summary,
        rebuild_owed=False,
    )
    return get_catalog_index_store().save(state)


def clear_catalog_index_ready(*, rebuild_owed: bool) -> CatalogIndexView:
    current = get_catalog_index_store().get()
    return get_catalog_index_store().save(
        replace(current, ready=False, rebuild_owed=rebuild_owed)
    )


def note_catalog_index_failure(
    *,
    failure_summary: str,
    objects_written: int = 0,
    columns_written: int = 0,
    objects_failed: int = 0,
    columns_failed: int = 0,
    objects_attempted: int = 0,
    columns_attempted: int = 0,
    progress: str | None = None,
) -> CatalogIndexView:
    """Record a sweep that must not publish ready. Leaves rebuild intent."""
    current = get_catalog_index_store().get()
    return get_catalog_index_store().save(
        replace(
            current,
            objects_written=objects_written,
            columns_written=columns_written,
            objects_failed=objects_failed,
            columns_failed=columns_failed,
            objects_attempted=objects_attempted,
            columns_attempted=columns_attempted,
            progress=progress if progress is not None else failure_summary,
            failure_summary=failure_summary,
        )
    )
