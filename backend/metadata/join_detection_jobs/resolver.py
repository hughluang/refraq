"""Resolve parsed join leaves to present catalog column ids."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.join_detection_jobs.parser import JoinLeaf

PARSEABLE_OBJECT_TYPES = frozenset(
    {"view", "materialized_view", "procedure", "function"}
)


class UnresolvedReason(StrEnum):
    EXTERNAL_CATALOG = "external_catalog"
    OBJECT_NOT_IN_CATALOG = "object_not_in_catalog"
    COLUMN_NOT_IN_OBJECT = "column_not_in_object"
    ALIAS_UNRESOLVED = "alias_unresolved"


@dataclass(frozen=True)
class ResolvedJoin:
    from_column_id: str
    to_column_id: str
    join_kind: str
    join_expression: str
    host_locator_key: str


@dataclass(frozen=True)
class LeafResolveOutcome:
    """Resolved edge, unresolved miss, or neither (same catalog column — not an edge)."""

    join: ResolvedJoin | None
    reason: UnresolvedReason | None


def _fold(value: str | None) -> str:
    return (value or "").casefold()


class CatalogJoinResolver:
    def __init__(
        self,
        objects: list[CatalogObjectRecord],
        *,
        source_database: str | None = None,
    ) -> None:
        self._source_database = _fold(source_database) if source_database else None
        self._by_schema_table_col: dict[tuple[str, str, str], str] = {}
        self._by_table_col: dict[tuple[str, str], list[str]] = {}
        self._tables: set[tuple[str, str]] = set()
        self._tables_by_name: set[str] = set()
        for obj in objects:
            if not obj.is_present:
                continue
            schema = _fold(obj.schema_name)
            table = _fold(obj.name)
            self._tables.add((schema, table))
            self._tables_by_name.add(table)
            for col in obj.columns:
                if not col.is_present:
                    continue
                col_key = _fold(col.name)
                self._by_schema_table_col[(schema, table, col_key)] = col.id
                self._by_table_col.setdefault((table, col_key), []).append(col.id)

    def _is_external_catalog(self, catalog: str | None) -> bool:
        if not catalog:
            return False
        if self._source_database is None:
            # Cannot defend without a known Source database; do not invent misses.
            return False
        return _fold(catalog) != self._source_database

    def resolve_column(
        self, schema: str | None, table: str, column: str
    ) -> str | None:
        table_key = _fold(table)
        col_key = _fold(column)
        if schema:
            found = self._by_schema_table_col.get((_fold(schema), table_key, col_key))
            if found is not None:
                return found
        matches = self._by_table_col.get((table_key, col_key), [])
        if len(matches) == 1:
            return matches[0]
        return None

    def _endpoint_reason(
        self, catalog: str | None, schema: str | None, table: str, column: str
    ) -> UnresolvedReason | None:
        if self._is_external_catalog(catalog):
            return UnresolvedReason.EXTERNAL_CATALOG
        table_key = _fold(table)
        col_key = _fold(column)
        if schema:
            schema_key = _fold(schema)
            if (schema_key, table_key, col_key) in self._by_schema_table_col:
                return None
            if (schema_key, table_key) in self._tables:
                return UnresolvedReason.COLUMN_NOT_IN_OBJECT
        matches = self._by_table_col.get((table_key, col_key), [])
        if len(matches) == 1:
            return None
        if table_key in self._tables_by_name:
            return UnresolvedReason.COLUMN_NOT_IN_OBJECT
        return UnresolvedReason.OBJECT_NOT_IN_CATALOG

    def resolve_leaf(
        self, leaf: JoinLeaf, *, host_locator_key: str
    ) -> LeafResolveOutcome:
        if self._is_external_catalog(leaf.left_catalog) or self._is_external_catalog(
            leaf.right_catalog
        ):
            return LeafResolveOutcome(
                join=None, reason=UnresolvedReason.EXTERNAL_CATALOG
            )
        left = self.resolve_column(leaf.left_schema, leaf.left_table, leaf.left_column)
        right = self.resolve_column(
            leaf.right_schema, leaf.right_table, leaf.right_column
        )
        if left is not None and right is not None:
            if left == right:
                return LeafResolveOutcome(join=None, reason=None)
            return LeafResolveOutcome(
                join=ResolvedJoin(
                    from_column_id=left,
                    to_column_id=right,
                    join_kind=leaf.join_kind or "INNER",
                    join_expression=leaf.join_expression,
                    host_locator_key=host_locator_key,
                ),
                reason=None,
            )
        left_reason = self._endpoint_reason(
            leaf.left_catalog, leaf.left_schema, leaf.left_table, leaf.left_column
        )
        right_reason = self._endpoint_reason(
            leaf.right_catalog, leaf.right_schema, leaf.right_table, leaf.right_column
        )
        # Prefer the more specific miss when one side resolved.
        if left is None and left_reason is not None:
            return LeafResolveOutcome(join=None, reason=left_reason)
        if right is None and right_reason is not None:
            return LeafResolveOutcome(join=None, reason=right_reason)
        return LeafResolveOutcome(
            join=None, reason=UnresolvedReason.OBJECT_NOT_IN_CATALOG
        )
