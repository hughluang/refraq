"""Set Fields, If, Filter, Merge, Deduplicate, and For."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.channel.engine import EngineHooks, NodeResult
from backend.channel.template import TemplateTypeError, render
from backend.channel.values import LIST_OF_OBJECTS

__all__ = [
    "run_deduplicate",
    "run_filter",
    "run_for",
    "run_if",
    "run_merge",
    "run_set_fields",
]

_ANY = {"type": ["object", "array", "string", "number", "boolean", "null"]}
_BOOL = {"type": "boolean"}
_ARRAY = {"type": "array"}
_ITEM_LIMIT = 100_000
_ORDER = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}


class _RowCompare(Exception):
    def __init__(self, index: int, operator: str) -> None:
        super().__init__(f"Row {index} is not comparable for operator {operator}")
        self.index = index


def run_set_fields(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    output: dict[str, Any] = {}
    for field in node["config"]["fields"]:
        value, error = _render(hooks, field.get("value"), _ANY)
        if error is not None:
            return error
        output[str(field["name"])] = value
    return NodeResult(status="succeeded", output=output)


def run_if(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    value, error = _render(hooks, node["config"].get("condition"), _BOOL)
    if error is not None:
        return error
    live = "true" if value else "false"
    return NodeResult(
        status="succeeded",
        output={"value": value},
        ports=frozenset({live}),
    )


def run_filter(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    items, error = _render(hooks, config.get("items"), LIST_OF_OBJECTS)
    if error is not None:
        return error
    combinator = str(config.get("combinator") or "all")
    conditions = list(config.get("conditions") or [])
    prepared: list[tuple[str, str, Any]] = []
    for condition in conditions:
        operator = str(condition["operator"])
        value = None
        if operator not in {"is_null", "is_not_null"}:
            value, error = _render(hooks, condition.get("value"), _ANY)
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


def run_merge(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    groups: list[list[Any]] = []
    for text in config["inputs"]:
        rows, error = _render(hooks, text, LIST_OF_OBJECTS)
        if error is not None:
            return error
        groups.append(rows)
    mode = str(config["mode"])
    join = str(config.get("join") or "inner")
    if mode == "append":
        rows = [dict(row) for group in groups for row in group]
    elif mode == "by_position":
        rows = _by_position(groups, join)
    else:
        key = config.get("key")
        if not isinstance(key, str) or not key:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="Merge by_key requires a key",
            )
        rows = groups[0]
        for group in groups[1:]:
            rows = _by_key(rows, group, key, join)
    return NodeResult(status="succeeded", output={"rows": rows, "count": len(rows)})


def run_deduplicate(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    items, error = _render(hooks, config.get("items"), LIST_OF_OBJECTS)
    if error is not None:
        return error
    keys = [str(key) for key in config["keys"]]
    seen: set[str] = set()
    kept: list[Any] = []
    for row in items:
        token = _canon([row.get(key) if isinstance(row, dict) else None for key in keys])
        if token in seen:
            continue
        seen.add(token)
        kept.append(row)
    return NodeResult(
        status="succeeded",
        output={"rows": kept, "count": len(kept), "removed": len(items) - len(kept)},
    )


def run_for(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    items, error = _render(hooks, node["config"].get("items"), _ARRAY)
    if error is not None:
        return error
    if len(items) > _ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message="For items exceed 100000 elements",
        )
    editor = getattr(hooks, "editor", None)
    if editor is not None and len(items) > editor.row_limit:
        items = list(items[: editor.row_limit])
    count = len(items)
    iterations = [
        {"current": item, "index": index, "count": count} for index, item in enumerate(items)
    ]
    if count == 0:
        current: Any = None
        index: int | None = None
    else:
        current = items[-1]
        index = count - 1
    return NodeResult(
        status="succeeded",
        output={"current": current, "index": index, "count": count, "results": []},
        iterations=iterations,
        ports=frozenset({"done"}),
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


def _by_key(
    left_rows: list[Any],
    right_rows: list[Any],
    key: str,
    join: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[int]] = {}
    for index, row in enumerate(right_rows):
        token = _key_token(row, key)
        if token is None:
            continue
        buckets.setdefault(token, []).append(index)
    matched: set[int] = set()
    output: list[dict[str, Any]] = []
    for left in left_rows:
        token = _key_token(left, key)
        hits = buckets.get(token, []) if token is not None else []
        if hits:
            for index in hits:
                matched.add(index)
                output.append({**left, **right_rows[index]})
        elif join in {"left", "full"}:
            output.append(dict(left))
    if join == "full":
        for index, row in enumerate(right_rows):
            if index not in matched:
                output.append(dict(row))
    return output


def _by_position(groups: list[list[Any]], join: str) -> list[dict[str, Any]]:
    lengths = [len(group) for group in groups]
    if join == "left":
        width = lengths[0]
    elif join == "full":
        width = max(lengths)
    else:
        width = min(lengths)
    rows: list[dict[str, Any]] = []
    for index in range(width):
        merged: dict[str, Any] = {}
        for group in groups:
            if index < len(group):
                merged.update(group[index])
        rows.append(merged)
    return rows


def _key_token(row: Any, key: str) -> str | None:
    if not isinstance(row, dict) or key not in row or row[key] is None:
        return None
    return _canon(row[key])


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _render(
    hooks: EngineHooks,
    raw: Any,
    schema: Mapping[str, Any],
) -> tuple[Any, NodeResult | None]:
    try:
        if not isinstance(raw, str):
            raise TemplateTypeError("Template value must be text")
        return render(raw, hooks.evaluate, schema), None  # type: ignore[attr-defined]
    except TemplateTypeError as exc:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_VALUE_TYPE_MISMATCH",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
    except Exception as exc:  # noqa: BLE001
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail={"expression": raw},
        )
