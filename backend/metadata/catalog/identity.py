"""Catalog Object structural identity matching (Source-scoped natural keys)."""

from __future__ import annotations

from typing import Any

from backend.metadata.catalog.records import CatalogWriteAborted
from backend.metadata.locators import format_column_locator, format_object_locator

# view ↔ materialized_view may be the same physical object across connector versions.
_VIEW_TYPE_TRANSITION = frozenset({"view", "materialized_view"})


def _natural_key(
    schema_name: str, name: str, object_type: str
) -> tuple[str, str, str]:
    return (schema_name, name, object_type)


def _is_view_type_transition(a: str, b: str) -> bool:
    return (
        a != b
        and a in _VIEW_TYPE_TRANSITION
        and b in _VIEW_TYPE_TRANSITION
    )


def _incoming_covers_existing(
    *,
    existing_schema: str,
    existing_name: str,
    existing_type: str,
    incoming_keys: dict[tuple[str, str, str], Any],
) -> bool:
    """True when an incoming object claims this existing identity (exact or type transition)."""
    exact = _natural_key(existing_schema, existing_name, existing_type)
    if exact in incoming_keys:
        return True
    if existing_type not in _VIEW_TYPE_TRANSITION:
        return False
    for (schema, name, otype) in incoming_keys:
        if (
            schema == existing_schema
            and name == existing_name
            and _is_view_type_transition(existing_type, otype)
        ):
            return True
    return False


def _match_existing_for_incoming(
    *,
    schema_name: str,
    name: str,
    object_type: str,
    existing_by_key: dict[tuple[str, str, str], Any],
) -> Any | None:
    exact = _natural_key(schema_name, name, object_type)
    match = existing_by_key.get(exact)
    if match is not None:
        return match
    if object_type not in _VIEW_TYPE_TRANSITION:
        return None
    candidates = [
        row
        for (schema, n, otype), row in existing_by_key.items()
        if schema == schema_name
        and n == name
        and _is_view_type_transition(otype, object_type)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise CatalogWriteAborted(
            "JOB_STRUCTURE_IDENTITY_AMBIGUOUS",
            f"Ambiguous view/materialized_view identity for "
            f"{schema_name}.{name}",
        )
    return None


def _recompute_object_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
) -> str:
    return format_object_locator(
        engine=engine,
        kind=kind,
        source_key=source_key,
        schema_name=schema_name,
        object_type=object_type,
        name=name,
    )


def _recompute_column_locator(
    *,
    engine: str | None,
    kind: str,
    source_key: str,
    schema_name: str,
    object_type: str,
    name: str,
    column_name: str,
    field_kind: str,
) -> str:
    return format_column_locator(
        engine=engine,
        kind=kind,
        source_key=source_key,
        schema_name=schema_name,
        object_type=object_type,
        name=name,
        column_name=column_name,
        field_kind=field_kind or "column",
    )


