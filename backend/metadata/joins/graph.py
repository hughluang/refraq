"""BFS join-path finder over catalog join edges."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogGraphStore,
    CatalogJoinRecord,
)
from backend.metadata.errors import JoinCrossSource

__all__ = [
    "JoinPath",
    "JoinPathHop",
    "JoinPathResult",
    "find_join_paths",
    "find_reachable_object_paths",
]


@dataclass(frozen=True)
class JoinPathHop:
    join: CatalogJoinRecord
    from_column_id: str
    to_column_id: str
    from_column_locator_key: str | None
    to_column_locator_key: str | None


@dataclass
class JoinPath:
    hops: list[JoinPathHop]
    target_object_id: str | None
    target_column_id: str | None

    @property
    def path_summary(self) -> str:
        parts: list[str] = []
        for hop in self.hops:
            expr = hop.join.join_expression or f"{hop.from_column_id}={hop.to_column_id}"
            parts.append(expr)
        return " -> ".join(parts)


@dataclass
class JoinPathResult:
    paths: list[JoinPath]
    direct_joins: list[CatalogJoinRecord]
    reason: str | None = None


@dataclass
class _SourceGraph:
    col_to_object: dict[str, str]
    col_locator: dict[str, str]
    object_columns: dict[str, list[str]]
    adjacency: dict[str, list[tuple[str, CatalogJoinRecord]]]


def find_join_paths(
    *,
    store: CatalogGraphStore,
    start_object_id: str | None = None,
    start_column_id: str | None = None,
    target_object_id: str | None = None,
    target_column_id: str | None = None,
    max_hops: int = 1,
    top_targets: int = 3,
) -> JoinPathResult:
    """BFS to an explicit target; same-object columns transfer without consuming a hop."""
    max_hops = max(1, min(5, max_hops))
    top_targets = max(1, top_targets)

    start_cols = _resolve_start_columns(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
    )
    if not start_cols:
        return JoinPathResult(
            paths=[],
            direct_joins=[],
            reason="NO_START_COLUMNS",
        )

    source_id = _source_for_column(store, start_cols[0].id)
    if source_id is None:
        return JoinPathResult(
            paths=[],
            direct_joins=[],
            reason="NO_START_COLUMNS",
        )

    if target_column_id:
        target_source = _source_for_column(store, target_column_id)
        if target_source is not None and target_source != source_id:
            raise JoinCrossSource()
    elif target_object_id:
        target_obj = store.get_object(target_object_id)
        if target_obj is not None and target_obj.source_id != source_id:
            raise JoinCrossSource()

    if not target_column_id and not target_object_id:
        raise ValueError("find_join_paths requires a target")

    graph = _load_source_graph(store, source_id)
    if target_column_id:
        target_ids = {target_column_id}
    else:
        assert target_object_id is not None
        target_ids = set(graph.object_columns.get(target_object_id, []))
        if not target_ids:
            return JoinPathResult(
                paths=[],
                direct_joins=[],
                reason="TARGET_UNREACHABLE",
            )

    direct_joins = _direct_joins(graph, start_column_id, max_hops)

    queue = _start_queue(graph, start_cols)
    if not queue:
        return JoinPathResult(
            paths=[],
            direct_joins=direct_joins,
            reason="NO_START_COLUMNS",
        )

    paths: list[JoinPath] = []
    found_targets: set[str] = set()

    while queue and len(found_targets) < top_targets:
        current, hops, visited_objects = queue.popleft()
        current_obj = graph.col_to_object.get(current)
        if current_obj is None:
            continue

        local_cols = graph.object_columns.get(current_obj, [current])
        for local_col in local_cols:
            for neighbor, join in graph.adjacency.get(local_col, []):
                neighbor_obj = graph.col_to_object.get(neighbor)
                if neighbor_obj is None or neighbor_obj in visited_objects:
                    continue
                next_hops = hops + [
                    JoinPathHop(
                        join=join,
                        from_column_id=local_col,
                        to_column_id=neighbor,
                        from_column_locator_key=graph.col_locator.get(local_col),
                        to_column_locator_key=graph.col_locator.get(neighbor),
                    )
                ]
                if len(next_hops) > max_hops:
                    continue

                if neighbor in target_ids:
                    if neighbor not in found_targets:
                        found_targets.add(neighbor)
                        paths.append(
                            JoinPath(
                                hops=next_hops,
                                target_object_id=neighbor_obj,
                                target_column_id=neighbor,
                            )
                        )
                    continue

                if len(next_hops) < max_hops:
                    queue.append(
                        (
                            neighbor,
                            next_hops,
                            visited_objects | {neighbor_obj},
                        )
                    )

    paths.sort(key=lambda p: (len(p.hops), p.path_summary))
    paths = paths[:top_targets]
    reason = None
    if not paths:
        reason = "TARGET_UNREACHABLE"
    return JoinPathResult(paths=paths, direct_joins=direct_joins, reason=reason)


def find_reachable_object_paths(
    *,
    store: CatalogGraphStore,
    start_object_id: str | None = None,
    start_column_id: str | None = None,
    max_hops: int = 1,
) -> JoinPathResult:
    """One shortest path per object reachable within `max_hops`. Builds the graph once."""
    max_hops = max(1, min(5, max_hops))
    start_cols = _resolve_start_columns(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
    )
    if not start_cols:
        return JoinPathResult(
            paths=[],
            direct_joins=[],
            reason="NO_START_COLUMNS",
        )

    source_id = _source_for_column(store, start_cols[0].id)
    if source_id is None:
        return JoinPathResult(
            paths=[],
            direct_joins=[],
            reason="NO_START_COLUMNS",
        )

    graph = _load_source_graph(store, source_id)
    direct_joins = _direct_joins(graph, start_column_id, max_hops)
    queue = _start_queue(graph, start_cols)
    if not queue:
        return JoinPathResult(
            paths=[],
            direct_joins=direct_joins,
            reason="NO_START_COLUMNS",
        )

    found: dict[str, JoinPath] = {}
    while queue:
        current, hops, visited_objects = queue.popleft()
        current_obj = graph.col_to_object.get(current)
        if current_obj is None:
            continue
        local_cols = graph.object_columns.get(current_obj, [current])
        for local_col in local_cols:
            for neighbor, join in graph.adjacency.get(local_col, []):
                neighbor_obj = graph.col_to_object.get(neighbor)
                if neighbor_obj is None or neighbor_obj in visited_objects:
                    continue
                next_hops = hops + [
                    JoinPathHop(
                        join=join,
                        from_column_id=local_col,
                        to_column_id=neighbor,
                        from_column_locator_key=graph.col_locator.get(local_col),
                        to_column_locator_key=graph.col_locator.get(neighbor),
                    )
                ]
                if len(next_hops) > max_hops:
                    continue
                if neighbor_obj not in found:
                    found[neighbor_obj] = JoinPath(
                        hops=next_hops,
                        target_object_id=neighbor_obj,
                        target_column_id=neighbor,
                    )
                if len(next_hops) < max_hops:
                    queue.append(
                        (
                            neighbor,
                            next_hops,
                            visited_objects | {neighbor_obj},
                        )
                    )

    paths = sorted(found.values(), key=lambda p: (len(p.hops), p.path_summary))
    return JoinPathResult(paths=paths, direct_joins=direct_joins, reason=None)


def _load_source_graph(store: CatalogGraphStore, source_id: str) -> _SourceGraph:
    objects = store.list_present_for_source(source_id)
    col_to_object: dict[str, str] = {}
    col_locator: dict[str, str] = {}
    object_columns: dict[str, list[str]] = {}
    for obj in objects:
        present = [c for c in obj.columns if c.is_present]
        object_columns[obj.id] = [c.id for c in present]
        for col in present:
            col_to_object[col.id] = obj.id
            col_locator[col.id] = col.locator_key

    joins = [
        join
        for join in store.list_all_joins_for_source(source_id)
        if not join.is_rejected
    ]
    adjacency: dict[str, list[tuple[str, CatalogJoinRecord]]] = {}
    for join in joins:
        adjacency.setdefault(join.from_column_id, []).append(
            (join.to_column_id, join)
        )
        adjacency.setdefault(join.to_column_id, []).append(
            (join.from_column_id, join)
        )
    return _SourceGraph(
        col_to_object=col_to_object,
        col_locator=col_locator,
        object_columns=object_columns,
        adjacency=adjacency,
    )


def _direct_joins(
    graph: _SourceGraph,
    start_column_id: str | None,
    max_hops: int,
) -> list[CatalogJoinRecord]:
    if not start_column_id or max_hops != 1:
        return []
    seen_join_ids: set[str] = set()
    direct: list[CatalogJoinRecord] = []
    for _neighbor, join in graph.adjacency.get(start_column_id, []):
        if join.id not in seen_join_ids:
            direct.append(join)
            seen_join_ids.add(join.id)
    return direct


def _start_queue(
    graph: _SourceGraph,
    start_cols: list[CatalogColumnRecord],
) -> deque[tuple[str, list[JoinPathHop], frozenset[str]]]:
    queue: deque[tuple[str, list[JoinPathHop], frozenset[str]]] = deque()
    for col in start_cols:
        obj_id = graph.col_to_object.get(col.id)
        if obj_id is None:
            continue
        queue.append((col.id, [], frozenset({obj_id})))
    return queue


def _resolve_start_columns(
    *,
    store: CatalogGraphStore,
    start_object_id: str | None,
    start_column_id: str | None,
) -> list[CatalogColumnRecord]:
    if start_column_id:
        col = store.get_column(start_column_id)
        return [col] if col is not None else []
    if start_object_id:
        obj = store.get_object(start_object_id)
        if obj is None:
            return []
        return [c for c in obj.columns if c.is_present]
    return []


def _source_for_column(store: CatalogGraphStore, column_id: str) -> str | None:
    col = store.get_column(column_id)
    if col is None:
        return None
    obj = store.get_object(col.object_id)
    return obj.source_id if obj else None
