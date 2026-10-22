"""Filter node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, EngineHooks, NodeResult, NodeType, object_schema
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


_ORDER = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


class _RowCompare(Exception):
    def __init__(self, index: int, operator: str) -> None:
        super().__init__(f"Row {index} is not comparable for operator {operator}")
        self.index = index


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    items, error = render_field(hooks, config.get("items"), LIST_OF_OBJECTS)
    if error is not None:
        return error
    if len(items) > ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=LIST_ITEM_LIMIT_MESSAGE,
        )
    combinator = str(config.get("combinator") or "all")
    conditions = list(config.get("conditions") or [])
    prepared: list[tuple[str, str, Any]] = []
    for condition in conditions:
        operator = str(condition["operator"])
        value = None
        if operator not in {"is_null", "is_not_null"}:
            value, error = render_field(hooks, condition.get("value"), _ANY)
            if error is not None:
                return error
        prepared.append((str(condition["key"]), operator, value))
    kept: list[Any] = []
    try:
        for index, row in enumerate(items):
            if _keep(row, prepared, combinator, index):
                kept.append(row)
    except _RowCompare as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail={"row_index": exc.index},
        )
    return NodeResult(
        status="succeeded",
        output={"rows": kept, "count": len(kept), "dropped": len(items) - len(kept)},
    )


def _keep(
    row: Any,
    conditions: list[tuple[str, str, Any]],
    combinator: str,
    index: int,
) -> bool:
    if not conditions:
        return True
    flags = [_match(row, key, operator, value, index) for key, operator, value in conditions]
    if combinator == "any":
        return any(flags)
    return all(flags)


def _match(row: Any, key: str, operator: str, value: Any, index: int) -> bool:
    left = row.get(key) if isinstance(row, dict) else None
    if operator == "is_null":
        return left is None
    if operator == "is_not_null":
        return left is not None
    if operator == "eq":
        return _json_eq(left, value)
    if operator == "ne":
        return not _json_eq(left, value)
    if operator in _ORDER:
        return _order(left, value, operator, index)
    if operator in {"in", "not_in"}:
        if not isinstance(value, list):
            raise _RowCompare(index, operator)
        found = any(_json_eq(left, item) for item in value)
        return found if operator == "in" else not found
    if operator in {"contains", "starts_with", "ends_with"}:
        if not isinstance(left, str) or not isinstance(value, str):
            raise _RowCompare(index, operator)
        if operator == "contains":
            return value in left
        if operator == "starts_with":
            return left.startswith(value)
        return left.endswith(value)
    raise _RowCompare(index, operator)


def _order(left: Any, right: Any, operator: str, index: int) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        raise _RowCompare(index, operator)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return bool(_ORDER[operator](left, right))
    if isinstance(left, str) and isinstance(right, str):
        return bool(_ORDER[operator](left, right))
    raise _RowCompare(index, operator)


def _json_eq(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(_json_eq(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_eq(a, b) for a, b in zip(left, right))
    return left == right


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
    trigger=False,
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
    execute=_execute,
    refine=_refine,
)
