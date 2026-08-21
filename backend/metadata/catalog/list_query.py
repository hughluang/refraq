"""List-query predicates for Catalog Objects.

Every predicate here is pushdown-capable. The SQL adapter asks this module
for WHERE clauses; the Memory adapter applies the same spec in Python. Do
not add a rule here that SQL cannot express as a column predicate — that
would force a post-filter and an N+1-shaped list.

Predicates (all evaluated after ``source_id``):

- ``include_absent``: False keeps only ``is_present`` rows
- ``object_type``: exact match when not None
- ``business_semantics_ready``: exact match when not None
- ``name_search``: case-insensitive substring of ``name``, ``schema_name``, or
  ``business_name`` (not ``business_description`` — list q is a name locator)

Sort: ``(schema_name, name, object_type)``.

``list_objects`` projects away columns, foreign keys, indexes, and ddl.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy import or_

from backend.metadata.catalog.records import CatalogObjectRecord


class ListObjectColumns(Protocol):
    """ORM-free column handles for the SQL translation of list predicates."""

    source_id: Any
    is_present: Any
    object_type: Any
    business_semantics_ready: Any
    name: Any
    schema_name: Any
    business_name: Any


@dataclass(frozen=True)
class ListObjectFilterSpec:
    source_id: str
    include_absent: bool
    object_type: str | None
    business_semantics_ready: bool | None
    name_needle: str


def list_object_filter_spec(
    source_id: str,
    *,
    name_search: str | None,
    include_absent: bool,
    object_type: str | None,
    business_semantics_ready: bool | None,
) -> ListObjectFilterSpec:
    return ListObjectFilterSpec(
        source_id=source_id,
        include_absent=include_absent,
        object_type=object_type,
        business_semantics_ready=business_semantics_ready,
        name_needle=(name_search or "").strip(),
    )


def escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def object_matches_name_search(obj: CatalogObjectRecord, needle: str) -> bool:
    if needle in obj.name.lower() or needle in obj.schema_name.lower():
        return True
    if obj.business_name and needle in obj.business_name.lower():
        return True
    return False


def object_matches_list_filters(
    obj: CatalogObjectRecord,
    *,
    source_id: str,
    name_search: str | None,
    include_absent: bool,
    object_type: str | None,
    business_semantics_ready: bool | None,
) -> bool:
    spec = list_object_filter_spec(
        source_id,
        name_search=name_search,
        include_absent=include_absent,
        object_type=object_type,
        business_semantics_ready=business_semantics_ready,
    )
    if obj.source_id != spec.source_id:
        return False
    if not spec.include_absent and not obj.is_present:
        return False
    if spec.object_type is not None and obj.object_type != spec.object_type:
        return False
    if (
        spec.business_semantics_ready is not None
        and obj.business_semantics_ready is not spec.business_semantics_ready
    ):
        return False
    if spec.name_needle and not object_matches_name_search(
        obj, spec.name_needle.lower()
    ):
        return False
    return True


def list_object_sql_filters(
    columns: ListObjectColumns,
    *,
    source_id: str,
    name_search: str | None,
    include_absent: bool,
    object_type: str | None,
    business_semantics_ready: bool | None,
) -> list[Any]:
    spec = list_object_filter_spec(
        source_id,
        name_search=name_search,
        include_absent=include_absent,
        object_type=object_type,
        business_semantics_ready=business_semantics_ready,
    )
    filters: list[Any] = [columns.source_id == spec.source_id]
    if not spec.include_absent:
        filters.append(columns.is_present.is_(True))
    if spec.object_type is not None:
        filters.append(columns.object_type == spec.object_type)
    if spec.business_semantics_ready is not None:
        filters.append(
            columns.business_semantics_ready.is_(spec.business_semantics_ready)
        )
    if spec.name_needle:
        pattern = f"%{escape_like_literal(spec.name_needle)}%"
        filters.append(
            or_(
                columns.name.ilike(pattern, escape="\\"),
                columns.schema_name.ilike(pattern, escape="\\"),
                columns.business_name.ilike(pattern, escape="\\"),
            )
        )
    return filters


def list_object_sort_key(obj: CatalogObjectRecord) -> tuple[str, str, str]:
    return (obj.schema_name, obj.name, obj.object_type)


def list_object_projection(obj: CatalogObjectRecord) -> CatalogObjectRecord:
    return replace(obj, columns=[], foreign_keys=[], indexes=[], ddl=None)
