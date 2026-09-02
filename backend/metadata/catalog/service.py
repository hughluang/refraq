"""Current catalog reads and Join Path lookup (HTTP + MCP)."""

from __future__ import annotations

from backend.metadata.catalog.embedding import embedding_configured
from backend.metadata.catalog.refs import resolve_column_ref, resolve_object_ref
from backend.metadata.catalog.search_hybrid import LEXICAL_POOL, hybrid_page
from backend.metadata.catalog.semantics_changes import CatalogSemanticsChangeRecord
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
    store = get_catalog_store()
    if not embedding_configured():
        items, total = store.search_objects(
            cleaned,
            source_id=source_id,
            object_type=object_type,
            limit=limit,
            offset=offset,
        )
        return [object_view(o, include_columns=False) for o in items], total
    pool, lexical_total = store.search_objects(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=LEXICAL_POOL,
        offset=0,
    )
    merged = hybrid_page(
        query=cleaned,
        lexical_items=pool,
        kind="object",
        id_of=lambda o: o.id,
        limit=limit,
        offset=offset,
    )
    if merged is None:
        items, total = store.search_objects(
            cleaned,
            source_id=source_id,
            object_type=object_type,
            limit=limit,
            offset=offset,
        )
        return [object_view(o, include_columns=False) for o in items], total
    items, _window = merged
    return [object_view(o, include_columns=False) for o in items], lexical_total


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
    store = get_catalog_store()
    if not embedding_configured():
        items, total = store.search_columns(
            cleaned,
            source_id=source_id,
            object_type=object_type,
            limit=limit,
            offset=offset,
        )
        return [column_view(c) for c in items], total
    pool, lexical_total = store.search_columns(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=LEXICAL_POOL,
        offset=0,
    )
    merged = hybrid_page(
        query=cleaned,
        lexical_items=pool,
        kind="column",
        id_of=lambda c: c.id,
        limit=limit,
        offset=offset,
    )
    if merged is None:
        items, total = store.search_columns(
            cleaned,
            source_id=source_id,
            object_type=object_type,
            limit=limit,
            offset=offset,
        )
        return [column_view(c) for c in items], total
    items, _window = merged
    return [column_view(c) for c in items], lexical_total


def get_object(object_ref: str) -> ObjectView:
    record = resolve_object_ref(object_ref)
    return object_view(record, include_columns=True)


def get_object_ddl(object_ref: str) -> ObjectDdlView:
    record = resolve_object_ref(object_ref)
    return ObjectDdlView(id=record.id, locator_key=record.locator_key, ddl=record.ddl)


def list_semantics_changes(
    object_ref: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CatalogSemanticsChangeRecord], int]:
    obj = resolve_object_ref(object_ref)
    return get_catalog_store().list_semantics_changes(
        obj.id, limit=limit, offset=offset
    )


def lookup_join_paths(
    start_ref: str,
    target_ref: str | None = None,
    *,
    query_text: str | None = None,
    max_hops: int = 1,
    top_targets: int = 3,
) -> JoinPathLookup:
    start_object_id, start_column_id = _resolve_path_endpoint(start_ref)
    target_object_id: str | None = None
    target_column_id: str | None = None
    if target_ref:
        target_object_id, target_column_id = _resolve_path_endpoint(target_ref)
    elif (query_text or "").strip():
        return _lookup_join_paths_from_query(
            start_object_id=start_object_id,
            start_column_id=start_column_id,
            query_text=(query_text or "").strip(),
            max_hops=max_hops,
            top_targets=top_targets,
        )

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

    return _join_path_lookup(result)


def _join_path_lookup(result: object) -> JoinPathLookup:
    paths: list[JoinPathView] = []
    for path in result.paths:  # type: ignore[attr-defined]
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
        direct_joins=[join_view(j) for j in result.direct_joins],  # type: ignore[attr-defined]
        reason=result.reason,  # type: ignore[attr-defined]
    )


def _lookup_join_paths_from_query(
    *,
    start_object_id: str | None,
    start_column_id: str | None,
    query_text: str,
    max_hops: int,
    top_targets: int,
) -> JoinPathLookup:
    store = get_catalog_store()
    start_probe = find_join_paths(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
        max_hops=max_hops,
        top_targets=1,
    )
    if start_probe.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()
    direct_joins = _join_path_lookup(start_probe).direct_joins

    objects, _ = search_objects(query_text, limit=max(top_targets * 3, 10), offset=0)
    columns, _ = search_columns(query_text, limit=max(top_targets * 3, 10), offset=0)
    start_obj = start_object_id
    if start_column_id:
        col = store.get_column(start_column_id)
        start_obj = col.object_id if col is not None else start_obj
    collected: list[JoinPathView] = []
    seen: set[tuple[str | None, str | None]] = set()
    targets: list[tuple[str | None, str | None]] = []
    for obj in objects:
        if obj.id == start_obj:
            continue
        targets.append((obj.id, None))
    for col in columns:
        if col.id == start_column_id:
            continue
        parent = get_catalog_store().get_column(col.id)
        if parent is not None and parent.object_id == start_obj:
            continue
        targets.append((None, col.id))
    for target_object_id, target_column_id in targets:
        if len(collected) >= top_targets:
            break
        result = find_join_paths(
            store=store,
            start_object_id=start_object_id,
            start_column_id=start_column_id,
            target_object_id=target_object_id,
            target_column_id=target_column_id,
            max_hops=max_hops,
            top_targets=1,
        )
        lookup = _join_path_lookup(result)
        for path in lookup.paths:
            key = (path.target_object_id, path.target_column_id)
            if key in seen:
                continue
            seen.add(key)
            collected.append(path)
            if len(collected) >= top_targets:
                break
    reason = None if collected else "TARGET_UNREACHABLE"
    return JoinPathLookup(
        paths_found=len(collected),
        paths=collected,
        direct_joins=direct_joins,
        reason=reason,
    )
