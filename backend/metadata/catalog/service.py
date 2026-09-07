"""Current catalog reads and Join Path lookup (HTTP + MCP)."""

from __future__ import annotations

from typing import Generic, Literal, NamedTuple, TypeVar

from backend.core.metrics import record_catalog_hybrid
from backend.metadata.catalog.embedding import embedding_configured
from backend.metadata.catalog.refs import resolve_column_ref, resolve_object_ref
from backend.metadata.catalog.search_hybrid import vector_page
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
from backend.metadata.joins.graph import (
    JoinPath,
    JoinPathResult,
    find_join_paths,
    find_reachable_object_paths,
)
from backend.metadata.sources.service import require_source

T = TypeVar("T")
RankMode = Literal["vector", "lexical"]


class CatalogSearchPage(NamedTuple, Generic[T]):
    items: list[T]
    rank_mode: RankMode
    truncated: bool


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
) -> CatalogSearchPage[ObjectView]:
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
        record_catalog_hybrid("lexical")
        return CatalogSearchPage(
            [object_view(o, include_columns=False) for o in items],
            "lexical",
            offset + len(items) < total,
        )
    items, truncated = vector_page(
        query=cleaned,
        kind="object",
        id_of=lambda o: o.id,
        limit=limit,
        offset=offset,
        source_id=source_id,
        object_type=object_type,
    )
    return CatalogSearchPage(
        [object_view(o, include_columns=False) for o in items],
        "vector",
        truncated,
    )


def search_columns(
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> CatalogSearchPage[ColumnView]:
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
        record_catalog_hybrid("lexical")
        return CatalogSearchPage(
            [column_view(c) for c in items],
            "lexical",
            offset + len(items) < total,
        )
    items, truncated = vector_page(
        query=cleaned,
        kind="column",
        id_of=lambda c: c.id,
        limit=limit,
        offset=offset,
        source_id=source_id,
        object_type=object_type,
    )
    return CatalogSearchPage([column_view(c) for c in items], "vector", truncated)


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
    if target_object_id or target_column_id:
        result = find_join_paths(
            store=store,
            start_object_id=start_object_id,
            start_column_id=start_column_id,
            target_object_id=target_object_id,
            target_column_id=target_column_id,
            max_hops=max_hops,
            top_targets=top_targets,
        )
    else:
        reachable = find_reachable_object_paths(
            store=store,
            start_object_id=start_object_id,
            start_column_id=start_column_id,
            max_hops=max_hops,
        )
        result = JoinPathResult(
            paths=reachable.paths[:top_targets],
            direct_joins=reachable.direct_joins,
            reason=reachable.reason,
        )
    if result.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()

    return _join_path_lookup(result)


def _join_path_lookup(result: object) -> JoinPathLookup:
    paths = [_join_path_view(path) for path in result.paths]  # type: ignore[attr-defined]
    return JoinPathLookup(
        paths_found=len(paths),
        paths=paths,
        direct_joins=[join_view(j) for j in result.direct_joins],  # type: ignore[attr-defined]
        reason=result.reason,  # type: ignore[attr-defined]
        rank_mode=None,
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
    reachable = find_reachable_object_paths(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
        max_hops=max_hops,
    )
    if reachable.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()
    direct_joins = _join_path_lookup(reachable).direct_joins
    by_object = {
        path.target_object_id: path
        for path in reachable.paths
        if path.target_object_id is not None
    }
    object_ids = list(by_object)
    rank_mode: RankMode = "vector" if embedding_configured() else "lexical"
    if not object_ids:
        return JoinPathLookup(
            paths_found=0,
            paths=[],
            direct_joins=direct_joins,
            reason="TARGET_UNREACHABLE",
            rank_mode=rank_mode,
        )

    ranked_object_ids = _rank_objects_by_query(
        query_text,
        object_ids=object_ids,
        rank_mode=rank_mode,
    )
    collected: list[JoinPathView] = []
    for object_id in ranked_object_ids:
        if len(collected) >= top_targets:
            break
        collected.append(_join_path_view(by_object[object_id]))
    reason = None if collected else "TARGET_UNREACHABLE"
    return JoinPathLookup(
        paths_found=len(collected),
        paths=collected,
        direct_joins=direct_joins,
        reason=reason,
        rank_mode=rank_mode,
    )


def _rank_objects_by_query(
    query_text: str,
    *,
    object_ids: list[str],
    rank_mode: RankMode,
) -> list[str]:
    store = get_catalog_store()
    if rank_mode == "lexical":
        columns, _total = store.search_columns(
            query_text,
            object_ids=object_ids,
            limit=50,
            offset=0,
        )
        record_catalog_hybrid("lexical")
        ordered: list[str] = []
        seen: set[str] = set()
        for col in columns:
            if col.object_id in seen:
                continue
            seen.add(col.object_id)
            ordered.append(col.object_id)
        return ordered

    items, _truncated = vector_page(
        query=query_text,
        kind="column",
        id_of=lambda c: c.id,
        limit=50,
        offset=0,
        object_ids=object_ids,
    )
    records = store.get_columns_by_ids([c.id for c in items])
    by_id = {col.id: col for col in records}
    ordered = []
    seen = set()
    for item in items:
        col = by_id.get(item.id)
        if col is None or col.object_id in seen:
            continue
        seen.add(col.object_id)
        ordered.append(col.object_id)
    return ordered


def _join_path_view(path: JoinPath) -> JoinPathView:
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
    return JoinPathView(
        target_object_id=path.target_object_id,
        target_column_id=path.target_column_id,
        hops=hops,
        path_summary=path.path_summary,
    )
