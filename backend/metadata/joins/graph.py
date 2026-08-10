"""BFS join-path finder over catalog join edges."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogStore,
)
from backend.metadata.errors import JoinCrossSource

__all__ = [
    "JoinPath",
    "JoinPathHop",
    "JoinPathResult",
    "find_join_paths",
]


@dataclass(frozen=True)
class JoinPathHop:
    join: CatalogJoinRecord
    from_column_id: str
    to_column_id: str


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


def find_join_paths(
    *,
    store: CatalogStore,
    start_object_id: str | None = None,
    start_column_id: str | None = None,
    target_object_id: str | None = None,
    target_column_id: str | None = None,
    max_hops: int = 1,
    top_targets: int = 3,
) -> JoinPathResult:
    """BFS over join edges; same-object columns transfer without consuming a hop."""
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

    objects = store.list_present_for_source(source_id)
    col_to_object: dict[str, str] = {}
    object_columns: dict[str, list[str]] = {}
    for obj in objects:
        present = [c.id for c in obj.columns if c.is_present]
        object_columns[obj.id] = present
        for cid in present:
            col_to_object[cid] = obj.id

    joins = store.list_all_joins_for_source(source_id)
    adjacency: dict[str, list[tuple[str, CatalogJoinRecord]]] = {}
    for join in joins:
        adjacency.setdefault(join.from_column_id, []).append(
            (join.to_column_id, join)
        )
        adjacency.setdefault(join.to_column_id, []).append(
            (join.from_column_id, join)
        )

    target_ids: set[str] | None = None
    if target_column_id:
        target_ids = {target_column_id}
    elif target_object_id:
        target_ids = set(object_columns.get(target_object_id, []))
        if not target_ids:
            return JoinPathResult(
                paths=[],
                direct_joins=[],
                reason="TARGET_UNREACHABLE",
            )

    direct_joins: list[CatalogJoinRecord] = []
    if start_column_id and max_hops == 1:
        seen_join_ids: set[str] = set()
        for neighbor, join in adjacency.get(start_column_id, []):
            if join.id not in seen_join_ids:
                direct_joins.append(join)
                seen_join_ids.add(join.id)

    queue: deque[tuple[str, list[JoinPathHop], frozenset[str]]] = deque()
    for col in start_cols:
        obj_id = col_to_object.get(col.id)
        if obj_id is None:
            continue
        queue.append((col.id, [], frozenset({obj_id})))

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
        current_obj = col_to_object.get(current)
        if current_obj is None:
            continue

        local_cols = object_columns.get(current_obj, [current])
        for local_col in local_cols:
            for neighbor, join in adjacency.get(local_col, []):
                neighbor_obj = col_to_object.get(neighbor)
                if neighbor_obj is None or neighbor_obj in visited_objects:
                    continue
                next_hops = hops + [
                    JoinPathHop(
                        join=join,
                        from_column_id=local_col,
                        to_column_id=neighbor,
                    )
                ]
                if len(next_hops) > max_hops:
                    continue

                if target_ids is not None and neighbor in target_ids:
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

                if target_ids is None and len(next_hops) <= max_hops:
                    key = neighbor
                    if key not in found_targets and len(next_hops) == max_hops:
                        found_targets.add(key)
                        paths.append(
                            JoinPath(
                                hops=next_hops,
                                target_object_id=neighbor_obj,
                                target_column_id=neighbor,
                            )
                        )

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
    if target_ids is not None and not paths:
        reason = "TARGET_UNREACHABLE"
    return JoinPathResult(paths=paths, direct_joins=direct_joins, reason=reason)


def _resolve_start_columns(
    *,
    store: CatalogStore,
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


def _source_for_column(store: CatalogStore, column_id: str) -> str | None:
    col = store.get_column(column_id)
    if col is None:
        return None
    obj = store.get_object(col.object_id)
    return obj.source_id if obj else None
