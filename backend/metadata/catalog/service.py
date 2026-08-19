"""Current catalog reads and Join Path lookup (HTTP + MCP)."""

from __future__ import annotations

from backend.metadata.catalog.refs import resolve_column_ref, resolve_object_ref
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog.views import (
    ColumnView,
    JoinPathHopView,
    JoinPathLookup,
    JoinPathView,
    ObjectDdlView,
    ObjectView,
    column_view,
    join_view,
    object_view,
)
from backend.metadata.errors import (
    CatalogColumnNotFound,
    CatalogSearchQueryRequired,
    JoinPathUnavailable,
)
from backend.metadata.joins.graph import find_join_paths
from backend.metadata.sources.service import require_source


def _resolve_path_endpoint(
    ref: str,
) -> tuple[str | None, str | None]:
    """Resolve locator/id to (object_id, column_id); column preferred."""
    try:
        col = resolve_column_ref(ref)
        return None, col.id
    except CatalogColumnNotFound:
        pass
    obj = resolve_object_ref(ref)
    return obj.id, None


def list_objects_for_source(
    source_id: str,
    *,
    q: str | None = None,
    object_type: str | None = None,
    include_absent: bool = True,
    business_semantics_ready: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ObjectView], int]:
    require_source(source_id)
    items, total = get_catalog_store().list_objects(
        source_id,
        name_search=q,
        include_absent=include_absent,
        object_type=object_type,
        business_semantics_ready=business_semantics_ready,
        limit=limit,
        offset=offset,
    )
    return [object_view(o, include_columns=False) for o in items], total


def search_objects(
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ObjectView], int]:
    cleaned = (query or "").strip()
    if not cleaned:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_objects(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return [object_view(o, include_columns=False) for o in items], total


def search_columns(
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ColumnView], int]:
    cleaned = (query or "").strip()
    if not cleaned:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_columns(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return [column_view(c) for c in items], total


def get_object(object_ref: str) -> ObjectView:
    record = resolve_object_ref(object_ref)
    return object_view(record, include_columns=True)


def get_object_ddl(object_ref: str) -> ObjectDdlView:
    record = resolve_object_ref(object_ref)
    return ObjectDdlView(id=record.id, locator_key=record.locator_key, ddl=record.ddl)


def lookup_join_paths(
    start_ref: str,
    target_ref: str | None = None,
    *,
    max_hops: int = 1,
    top_targets: int = 3,
) -> JoinPathLookup:
    start_object_id, start_column_id = _resolve_path_endpoint(start_ref)
    target_object_id: str | None = None
    target_column_id: str | None = None
    if target_ref:
        target_object_id, target_column_id = _resolve_path_endpoint(target_ref)

    store = get_catalog_store()
    result = find_join_paths(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
        target_object_id=target_object_id,
        target_column_id=target_column_id,
        max_hops=max_hops,
        top_targets=top_targets,
    )
    if result.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()

    paths: list[JoinPathView] = []
    for path in result.paths:
        hops = [
            JoinPathHopView(
                from_column_id=hop.from_column_id,
                to_column_id=hop.to_column_id,
                from_column_locator_key=hop.from_column_locator_key,
                to_column_locator_key=hop.to_column_locator_key,
                join_id=hop.join.id,
                join_kind=hop.join.join_kind,
                join_expression=hop.join.join_expression,
                evidence=hop.join.evidence,
                origin=hop.join.origin,
            )
            for hop in path.hops
        ]
        paths.append(
            JoinPathView(
                target_object_id=path.target_object_id,
                target_column_id=path.target_column_id,
                hops=hops,
                path_summary=path.path_summary,
            )
        )
    return JoinPathLookup(
        paths_found=len(paths),
        paths=paths,
        direct_joins=[join_view(j) for j in result.direct_joins],
        reason=result.reason,
    )
