"""JSON Schema fragments for declared template values and port shapes."""

from __future__ import annotations

from typing import Any

__all__ = ["LIST_OF_OBJECTS", "attribute_value_schema"]

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
