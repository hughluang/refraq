"""Merge node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema
from backend.channel.values import LIST_OF_OBJECTS

__all__ = ["NODE_TYPE"]

_ROWS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "count"],
    "properties": {
        "rows": LIST_OF_OBJECTS,
        "count": {"type": "integer"},
    },
}


def _schema() -> dict[str, Any]:
    schema = object_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["append", "by_key", "by_position"],
                "title": "Mode",
                "description": "append concatenates. by_key matches a field. by_position pairs by index.",
            },
            "inputs": {
                "type": "array",
                "minItems": 2,
                "title": "Inputs",
                "description": "Templates whose values are lists of objects, folded from left to right.",
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Input",
                    "description": "Template whose value is a list of objects.",
                    "x-refraq-template": LIST_OF_OBJECTS,
                },
            },
            "key": {
                "type": ["string", "null"],
                "title": "Key",
                "description": "Field matched by by_key. Null keys never match. Ignored by other modes.",
            },
            "join": {
                "type": "string",
                "enum": ["inner", "left", "full"],
                "default": "inner",
                "title": "Join",
                "description": "inner, left, or full. Default inner. append ignores it.",
            },
        },
        ["mode", "inputs"],
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"mode": {"const": "by_key"}},
                "required": ["mode"],
            },
            "then": {
                "properties": {"key": {"type": "string", "minLength": 1}},
                "required": ["key"],
            },
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
    type_id="transform.merge",
    family="transform",
    label="Merge",
    summary="Combines two or more lists of objects into one list.",
    description=(
        "append concatenates the lists in order. "
        "by_key matches on one field and folds from left to right, one row to many. "
        "by_position pairs rows by index. "
        "The join is inner, left, or full. append ignores the join."
    ),
    entry=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=_schema(),
    refine=_refine,
)
