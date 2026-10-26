"""Filter node type."""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.channel.template import schema_at_path
from backend.channel.values import LIST_OF_OBJECTS, array_item_schema, temporal_declaration

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
    del resolver
    element = _element(config.get("items"), upstream)
    _remember(config, _facts(element, config, upstream))
    return {"main": _with_items(element)}


def _element(text: Any, upstream: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    return array_item_schema(schema_at_path(text, upstream))


def _with_items(item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return _ROWS
    properties = dict(_ROWS["properties"])
    properties["rows"] = {"type": "array", "items": item}
    return {**_ROWS, "properties": properties}


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
    items, error = render_field(hooks, config.get("items"), LIST_OF_OBJECTS, path="items")
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
    for index, condition in enumerate(conditions):
        operator = str(condition["operator"])
        value = None
        if operator not in {"is_null", "is_not_null"}:
            value, error = render_field(
                hooks,
                condition.get("value"),
                _ANY,
                path=f"conditions.{index}.value",
            )
            if error is not None:
                return error
        prepared.append((str(condition["key"]), operator, value))
    kept: list[Any] = []
    facts = _recall(config)
    try:
        for index, row in enumerate(items):
            if _keep(row, prepared, combinator, index, facts):
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
    facts: "_Facts | None",
) -> bool:
    if not conditions:
        return True
    flags = [
        _match(row, key, operator, value, index, _shared(facts, key, position))
        for position, (key, operator, value) in enumerate(conditions)
    ]
    if combinator == "any":
        return any(flags)
    return all(flags)


def _match(
    row: Any,
    key: str,
    operator: str,
    value: Any,
    index: int,
    side: "_Side | None",
) -> bool:
    left = row.get(key) if isinstance(row, dict) else None
    if operator == "is_null":
        return left is None
    if operator == "is_not_null":
        return left is not None
    if operator == "eq":
        return _equals(left, value, side)
    if operator == "ne":
        return not _equals(left, value, side)
    if operator in _ORDER:
        return _order(left, value, operator, index, side)
    if operator in {"in", "not_in"}:
        if not isinstance(value, list):
            raise _RowCompare(index, operator)
        found = any(_equals(left, item, side) for item in value)
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


def _order(
    left: Any, right: Any, operator: str, index: int, side: "_Side | None"
) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        raise _RowCompare(index, operator)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return bool(_ORDER[operator](left, right))
    compared = _temporal_order(left, right, side)
    if compared is not None:
        return bool(_ORDER[operator](compared, 0))
    if isinstance(left, str) and isinstance(right, str):
        return bool(_ORDER[operator](left, right))
    raise _RowCompare(index, operator)


def _equals(left: Any, right: Any, side: "_Side | None") -> bool:
    compared = _temporal_order(left, right, side)
    if compared is not None:
        return compared == 0
    return _json_eq(left, right)


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


@dataclass(frozen=True)
class _Side:
    kind: str
    precision: int | None


@dataclass(frozen=True)
class _Facts:
    columns: dict[str, _Side]
    rights: tuple[_Side | None, ...]


_CACHE: ContextVar[dict[int, tuple[object, _Facts]] | None] = ContextVar(
    "channel_filter_temporal", default=None
)
_ELAPSED = re.compile(
    r"^(-)?P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)
_UTC = timezone.utc


def _remember(config: Mapping[str, Any], facts: _Facts) -> None:
    cache = _CACHE.get()
    if cache is None:
        cache = {}
        _CACHE.set(cache)
    cache[id(config)] = (config.get("items"), facts)


def _recall(config: Mapping[str, Any]) -> _Facts | None:
    cache = _CACHE.get()
    if cache is None:
        return None
    found = cache.get(id(config))
    if found is None or found[0] != config.get("items"):
        return None
    return found[1]


def _facts(
    element: Mapping[str, Any] | None,
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
) -> _Facts:
    columns: dict[str, _Side] = {}
    properties = element.get("properties") if isinstance(element, Mapping) else None
    if isinstance(properties, Mapping):
        for name, schema in properties.items():
            side = _side(schema)
            if isinstance(name, str) and side is not None:
                columns[name] = side
    rights: list[_Side | None] = []
    conditions = config.get("conditions") or []
    if isinstance(conditions, list):
        for condition in conditions:
            if not isinstance(condition, Mapping):
                rights.append(None)
                continue
            value = condition.get("value")
            schema = schema_at_path(value, upstream) if isinstance(value, str) else None
            rights.append(_side(schema) or _side(array_item_schema(schema)))
    return _Facts(columns, tuple(rights))


def _side(schema: Mapping[str, Any] | None) -> _Side | None:
    if not isinstance(schema, Mapping):
        return None
    declared = temporal_declaration(schema)
    if declared is None:
        return None
    kind, precision, _nullable = declared
    return _Side(kind, precision)


def _shared(facts: _Facts | None, key: str, position: int) -> _Side | None:
    if facts is None:
        return None
    left = facts.columns.get(key)
    right = facts.rights[position] if position < len(facts.rights) else None
    if left is None or right is None or left.kind != right.kind:
        return None
    return _Side(left.kind, left.precision)


def _temporal_order(left: Any, right: Any, side: _Side | None) -> int | None:
    if side is None or not isinstance(left, str) or not isinstance(right, str):
        return None
    try:
        first = _temporal_key(left, side.kind, side.precision)
        second = _temporal_key(right, side.kind, side.precision)
    except (TypeError, ValueError, OverflowError):
        return None
    if first is None or second is None:
        return None
    if first < second:
        return -1
    if first > second:
        return 1
    return 0


def _temporal_key(text: str, kind: str, precision: int | None):
    if kind == "date":
        return _parse_date(text)
    if kind == "time":
        clock = _parse_time(text, offset=False)
        return None if clock is None else _truncate_time(clock, precision)
    if kind == "time_with_offset":
        clock = _parse_time(text, offset=True)
        if clock is None or clock.utcoffset() is None:
            return None
        return (clock.utcoffset(), _truncate_time(clock, precision))
    if kind in {"local_datetime", "timestamp_with_local_time_zone"}:
        parsed = _parse_datetime(text)
        if parsed is None or parsed.tzinfo is not None:
            return None
        return _truncate_datetime(parsed, precision)
    if kind == "timestamp_with_time_zone":
        parsed = _parse_datetime(text)
        if parsed is None or parsed.tzinfo is None:
            return None
        return _truncate_datetime(parsed, precision).astimezone(_UTC)
    if kind in {"interval", "interval_fixed", "interval_calendar"}:
        return _parse_elapsed(text, precision)
    return None


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_datetime(text: str) -> datetime | None:
    body = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(body)
    except ValueError:
        return None


def _parse_time(text: str, *, offset: bool) -> time | None:
    try:
        parsed = time.fromisoformat(text)
    except ValueError:
        return None
    if offset:
        return parsed if parsed.tzinfo is not None else None
    return None if parsed.tzinfo is not None else parsed


def _truncate_datetime(value: datetime, precision: int | None) -> datetime:
    return value.replace(microsecond=_truncate_us(value.microsecond, precision))


def _truncate_time(value: time, precision: int | None) -> time:
    return value.replace(microsecond=_truncate_us(value.microsecond, precision), tzinfo=None)


def _truncate_us(microseconds: int, precision: int | None) -> int:
    if precision is None or precision >= 6:
        return microseconds
    if precision <= 0:
        return 0
    factor = 10 ** (6 - precision)
    return (microseconds // factor) * factor


def _parse_elapsed(text: str, precision: int | None) -> timedelta | None:
    match = _ELAPSED.fullmatch(text)
    if match is None:
        return None
    sign, days, hours, minutes, seconds = match.groups()
    if days is None and hours is None and minutes is None and seconds is None:
        return None
    whole = 0
    fraction = 0
    if seconds is not None:
        whole, fraction = _split_seconds(seconds)
    elapsed = timedelta(
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=whole,
        microseconds=_truncate_us(fraction, precision),
    )
    if sign:
        return -elapsed
    return elapsed


def _split_seconds(text: str) -> tuple[int, int]:
    if "." not in text:
        return int(text), 0
    whole, fraction = text.split(".", 1)
    padded = (fraction + "000000")[:6]
    return int(whole or "0"), int(padded)


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
    output_view=OutputView(kind="rows", rows="rows", metrics=("count", "dropped")),
    execute=_execute,
    refine=_refine,
)
