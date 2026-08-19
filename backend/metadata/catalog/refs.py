"""Catalog locator/id resolution helpers (internal)."""

from __future__ import annotations

from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    get_catalog_store,
)
from backend.metadata.errors import (
    CatalogColumnNotFound,
    CatalogJoinNotFound,
    CatalogObjectNotFound,
    SourceNotFound,
)
from backend.metadata.sources.store import SourceRecord, get_source_store


def require_column(column_id: str) -> CatalogColumnRecord:
    record = get_catalog_store().get_column(column_id)
    if record is None:
        raise CatalogColumnNotFound()
    return record


def require_join(join_id: str) -> CatalogJoinRecord:
    record = get_catalog_store().get_join(join_id)
    if record is None:
        raise CatalogJoinNotFound()
    return record


def resolve_source_ref(ref: str) -> SourceRecord:
    """Resolve Source by id or locator_key."""
    store = get_source_store()
    record = store.get_source(ref) or store.get_source_by_locator(ref)
    if record is None:
        raise SourceNotFound()
    return record


def resolve_object_ref(ref: str) -> CatalogObjectRecord:
    store = get_catalog_store()
    record = store.get_object(ref) or store.get_object_by_locator(ref)
    if record is None:
        raise CatalogObjectNotFound()
    return record


def resolve_column_ref(ref: str) -> CatalogColumnRecord:
    store = get_catalog_store()
    record = store.get_column(ref) or store.get_column_by_locator(ref)
    if record is None:
        raise CatalogColumnNotFound()
    return record
