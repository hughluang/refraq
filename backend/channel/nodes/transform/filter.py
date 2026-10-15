"""Filter node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema
from backend.channel.values import LIST_OF_OBJECTS

__all__ = ["NODE_TYPE"]

_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}
_OPERATORS = [
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
    "is_null",
    "is_not_null",
]
_NEEDS_VALUE = [
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "starts_with",
    "ends_with",
]

_ROWS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "count", "dropped"],
    "properties": {
        "rows": LIST_OF_OBJECTS,
        "count": {"type": "integer"},
        "dropped": {"type": "integer"},
    },
}


def _condition_schema() -> dict[str, Any]:
    schema = object_schema(
        {
            "key": {
                "type": "string",
                "minLength": 1,
                "title": "Key",
                "description": "Field compared on each object. A missing field is null.",
            },
            "operator": {
                "type": "string",
                "enum": _OPERATORS,
                "title": "Operator",
                "description": (
                    "eq, ne, gt, gte, lt, lte, in, not_in, contains, "
                    "starts_with, ends_with, is_null, or is_not_null."
                ),
            },
            "value": {
                "type": "string",
                "title": "Value",
                "description": (
                    "JSON template compared with the field. Evaluated once, not per row. "
                    "Omitted for is_null and is_not_null."
                ),
                "x-refraq-template": _ANY,
            },
        },
        ["key", "operator"],
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"operator": {"enum": _NEEDS_VALUE}},
                "required": ["operator"],
            },
            "then": {"required": ["key", "operator", "value"]},
        }
    ]
    return schema


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _ROWS}


NODE_TYPE = NodeType(
    type_id="transform.filter",
    family="transform",
    label="Filter",
    summary="Keeps the objects in a list that match the conditions.",
    description=(
        "The items template is a list of objects. "
        "Each condition compares one key with a value that is evaluated once. "
        "all keeps a row only when every condition matches. any keeps it when one matches. "
        "The output lists the kept rows and how many were dropped."
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
            "combinator": {
                "type": "string",
                "enum": ["all", "any"],
                "default": "all",
                "title": "Combinator",
                "description": "all requires every condition. any requires one. Default all.",
            },
            "conditions": {
                "type": "array",
                "title": "Conditions",
                "description": "Comparisons applied to each object. Empty keeps every row.",
                "items": _condition_schema(),
            },
        },
        ["items", "conditions"],
    ),
    refine=_refine,
)
