"""Merge node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.node_support import canonical_json, render_field
from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, EngineHooks, NodeResult, NodeType, object_schema
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


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    groups: list[list[Any]] = []
    for text in config["inputs"]:
        rows, error = render_field(hooks, text, LIST_OF_OBJECTS)
        if error is not None:
            return error
        if len(rows) > ITEM_LIMIT:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
                error_message=LIST_ITEM_LIMIT_MESSAGE,
            )
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
        merged = groups[0]
        for group in groups[1:]:
            merged = _by_key(merged, group, key, join)
        rows = merged
    if len(rows) > ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=LIST_ITEM_LIMIT_MESSAGE,
        )
    return NodeResult(status="succeeded", output={"rows": rows, "count": len(rows)})


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
    return canonical_json(row[key])


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
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=_schema(),
    execute=_execute,
    refine=_refine,
)
