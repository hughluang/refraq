"""Bind the live Inventory read to management test fixtures."""

from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.mirrors import fleet, service
from backend.metadata.mirrors.diagnostic_store import DiagnosticStore
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.sources.store import get_source_store


def inventory_dependencies():
    mirror_store = service._storage()
    return dict(
        store=DiagnosticStore(memory=isinstance(mirror_store, MemoryMirrorStore), transaction=mirror_store.transaction),
        mirror_store=mirror_store,
        source_store=get_source_store(),
        catalog_store=get_catalog_store(),
    )


def inventory(**query):
    return fleet.inventory(**inventory_dependencies(), **query)
