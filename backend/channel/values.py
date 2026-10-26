"""JSON Schema fragments for declared template values and port shapes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "LIST_OF_OBJECTS",
    "TEMPORAL_KINDS",
    "array_item_schema",
    "attribute_value_schema",
    "dataset_row_schema",
    "temporal_declaration",
    "temporal_kinds_by_name",
]

# Closed set carried on dataset reference columns. Same names as the source
# stream declaration. A lone with_time_zone flag is not a member.
TEMPORAL_KINDS = frozenset(
    {
        "date",
        "time",
        "time_with_offset",
        "local_datetime",
        "timestamp_with_time_zone",
        "timestamp_with_local_time_zone",
        "interval",
        "interval_calendar",
        "interval_fixed",
    }
)

LIST_OF_OBJECTS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "object"},
}

_SCALARS: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "text": {"type": "string"},
    "user": {"type": "string"},
    "dictionary": {"type": "string"},
    "reference": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "decimal": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string"},
    "timestamp": {"type": "string"},
    "time": {"type": "string"},
    "json": {"type": ["object", "array", "string", "number", "boolean", "null"]},
}


def array_item_schema(schema: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Element schema when ``schema`` is an array. Otherwise None."""
    if not isinstance(schema, Mapping):
        return None
    kind = schema.get("type")
    is_array = kind == "array" or (isinstance(kind, list) and "array" in kind)
    items = schema.get("items")
    if not is_array or not isinstance(items, dict):
        return None
    return dict(items)


def dataset_row_schema(schema: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Row object schema when a dataset reference names its columns."""
    columns = _concrete_columns(schema)
    if columns is None:
        return None
    properties: dict[str, Any] = {}
    for column in columns:
        name = column.get("name")
        kind = column.get("type")
        if (
            not isinstance(name, str)
            or name == ""
            or not isinstance(kind, str)
            or kind == ""
        ):
            return None
        properties[name] = _column_value_schema(column, kind)
    return {"type": "object", "properties": properties}


def _concrete_columns(schema: Mapping[str, Any] | None) -> list[Any] | None:
    if not isinstance(schema, Mapping):
        return None
    const = schema.get("const")
    if isinstance(const, Mapping):
        found = _column_list(const.get("columns"))
        if found is not None:
            return found
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    columns = properties.get("columns")
    if not isinstance(columns, Mapping):
        return None
    return _column_list(columns.get("const"))


def _column_list(value: object) -> list[Any] | None:
    if not isinstance(value, list) or not value:
        return None
    if all(isinstance(item, Mapping) for item in value):
        return list(value)
    return None


def attribute_value_schema(attribute_type: str) -> dict[str, Any]:
    """Schema for one attribute value, including null."""
    base = _SCALARS.get(attribute_type, {"type": "string"})
    kind = base["type"]
    if isinstance(kind, list):
        types = list(kind)
        if "null" not in types:
            types.append("null")
        return {"type": types}
    return {"type": [kind, "null"]}


def temporal_kinds_by_name(columns: object) -> dict[str, str]:
    """Column name to temporal kind, for columns that declare one."""
    found: dict[str, str] = {}
    if not isinstance(columns, list):
        return found
    for column in columns:
        if not isinstance(column, Mapping):
            continue
        name = column.get("name")
        declared = temporal_declaration(column)
        if isinstance(name, str) and declared is not None:
            found[name] = declared[0]
    return found


def temporal_declaration(
    column: Mapping[str, Any],
) -> tuple[str, int | None, bool | None] | None:
    """Kind, fractional precision, and nullable when the column declares a kind.

    ``with_time_zone`` alone does not choose a kind. An unknown kind is ignored.
    """
    kind = column.get("temporal_kind")
    if not isinstance(kind, str) or kind not in TEMPORAL_KINDS:
        return None
    return kind, _precision(column.get("precision")), _nullable(column.get("nullable"))


def _column_value_schema(column: Mapping[str, Any], attribute_type: str) -> dict[str, Any]:
    schema = attribute_value_schema(attribute_type)
    declared = temporal_declaration(column)
    if declared is None:
        return schema
    kind, precision, nullable = declared
    schema["temporal_kind"] = kind
    schema["precision"] = precision
    schema["nullable"] = nullable
    return schema


def _precision(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _nullable(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None
