"""Deduplicate node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema
from backend.channel.values import LIST_OF_OBJECTS

__all__ = ["NODE_TYPE"]

_ROWS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "count", "removed"],
    "properties": {
        "rows": LIST_OF_OBJECTS,
        "count": {"type": "integer"},
        "removed": {"type": "integer"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _ROWS}


NODE_TYPE = NodeType(
    type_id="transform.deduplicate",
    family="transform",
    label="Deduplicate",
    summary="Keeps the first object for each key combination.",
    description=(
        "The items template is a list of objects. "
        "keys names the fields that form the identity, compared as JSON. "
        "A missing field is null. Later duplicates are counted in removed."
    ),
    entry=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "items": {
                "type": "string",
                "minLength": 1,
                "title": "Items",
                "description": "Template whose value is a list of objects.",
                "x-refraq-template": LIST_OF_OBJECTS,
            },
            "keys": {
                "type": "array",
                "minItems": 1,
                "title": "Keys",
                "description": "Field names that identify a duplicate. At least one.",
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Key",
                    "description": "Field name. A missing field is null.",
                },
            },
        },
        ["items", "keys"],
    ),
    refine=_refine,
)
