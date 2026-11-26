"""Read Entity node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
    object_schema,
)
from backend.channel.values import LIST_OF_OBJECTS, attribute_value_schema
from backend.entity.errors import EntityRowLimitExceeded
from backend.entity.rows import read_rows

__all__ = ["NODE_TYPE"]

_DEFAULT_LIMIT = 1000
_DEFAULT_TIMEOUT_SEC = 60

_OPERATORS = (
    "eq",
    "ne",
    "ieq",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "is_null",
    "is_not_null",
    "json_contains",
    "has_key",
    "has_any_keys",
    "has_all_keys",
)
_NEEDS_VALUE = tuple(op for op in _OPERATORS if op not in ("is_null", "is_not_null"))
_ROW_ID_OPS = frozenset(
    ("eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "not_in", "is_null", "is_not_null")
)
_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}


def _output_schema(row_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows", "count", "total"],
        "properties": {
            "rows": {"type": "array", "items": row_schema},
            "count": {"type": "integer", "minimum": 0},
            "total": {"type": "integer", "minimum": 0},
        },
    }


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream
    entity_id = config.get("entity_id")
    head = resolver.entity_head(entity_id) if isinstance(entity_id, str) and entity_id else None
    if head is None:
        return {"main": _output_schema(LIST_OF_OBJECTS["items"]), "error": None}
    properties: dict[str, Any] = {"row_id": {"type": "integer"}}
    for attr in head.attributes:
        properties[attr.name] = attribute_value_schema(attr.value_type)
    return {
        "main": _output_schema({"type": "object", "properties": properties}),
        "error": None,
    }


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    entity_id = config.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id:
        return []
    head = resolver.entity_head(entity_id)
    if head is None:
        return []
    problems: list[Problem] = []
    by_name = {attr.name: attr for attr in head.attributes}
    for index, entry in enumerate(config.get("filters") or []):
        if not isinstance(entry, Mapping):
            continue
        attr_name = entry.get("attribute")
        op = entry.get("op")
        if not isinstance(attr_name, str) or not isinstance(op, str):
            continue
        if attr_name == "row_id":
            if op not in _ROW_ID_OPS:
                problems.append(
                    Problem(
                        "CHANNEL_NODE_CONFIG_INVALID",
                        f"Operator '{op}' is not allowed for row_id",
                        path=("filters", index, "op"),
                    )
                )
            continue
        attr = by_name.get(attr_name)
        if attr is not None and attr.operators and op not in attr.operators:
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    f"Operator '{op}' is not allowed for attribute '{attr_name}'",
                    path=("filters", index, "op"),
                )
            )
    sort_attr = config.get("sort_attribute")
    if isinstance(sort_attr, str) and sort_attr and sort_attr != "row_id":
        attr = by_name.get(sort_attr)
        if attr is None:
            problems.append(
                Problem(
                    "CHANNEL_REFERENCE_UNRESOLVED",
                    f"Attribute does not resolve: {sort_attr}",
                    path=("sort_attribute",),
                )
            )
        elif not attr.sortable:
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    f"Sorting is not supported for attribute '{sort_attr}'",
                    path=("sort_attribute",),
                )
            )
    return problems


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    entity_id = str(config["entity_id"])
    limit = int(config.get("limit", _DEFAULT_LIMIT))
    timeout_sec = int(config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC))
    match = "any" if config.get("match") == "any" else "all"
    clauses: list[dict[str, Any]] = []

    for index, entry in enumerate(config.get("filters") or []):
        attr_name = str(entry["attribute"])
        op = str(entry["op"])
        leaf: dict[str, Any] = {"field": attr_name, "op": op}
        if op in _NEEDS_VALUE:
            value, err = render_field(
                hooks,
                entry.get("value"),
                _ANY,
                path=f"filters[{index}].value",
            )
            if err is not None:
                return err
            leaf["value"] = value
        clauses.append({"not": leaf} if entry.get("negate") else leaf)

    filter_parts: list[dict[str, Any]] = []
    if clauses:
        filter_parts.append(clauses[0] if len(clauses) == 1 else {match: clauses})

    raw_where = config.get("where")
    if isinstance(raw_where, str) and raw_where.strip():
        rendered_where, err = render_field(
            hooks,
            raw_where,
            {"type": "object"},
            path="where",
        )
        if err is not None:
            return err
        if isinstance(rendered_where, Mapping) and rendered_where:
            filter_parts.append(dict(rendered_where))

    combined_filters: dict[str, Any] | None = None
    if len(filter_parts) == 1:
        combined_filters = filter_parts[0]
    elif len(filter_parts) > 1:
        combined_filters = {"all": filter_parts}

    sort_spec: dict[str, str] | None = None
    sort_attr = config.get("sort_attribute")
    if isinstance(sort_attr, str) and sort_attr.strip():
        sort_spec = {
            "field": sort_attr.strip(),
            "direction": "desc" if config.get("sort_direction") == "desc" else "asc",
        }

    try:
        rows, total = read_rows(
            entity_id,
            filters=combined_filters,
            sort=sort_spec,
            user=hooks.user,
            limit=limit,
            statement_timeout_ms=timeout_sec * 1000,
        )
    except EntityRowLimitExceeded as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=exc.message,
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code=getattr(exc, "code", "CHANNEL_NODE_FAILED"),
            error_message=getattr(exc, "message", str(exc)),
        )

    return NodeResult(
        status="succeeded",
        output={"rows": rows, "count": len(rows), "total": total},
    )


NODE_TYPE = NodeType(
    type_id="read.entity",
    family="read",
    label="Read Entity",
    summary="Reads bounded rows from a Business Entity through Entity Access Control.",
    description=(
        "Queries the current published head of one Business Entity as the platform "
        "System Identity through Entity Access Control. Supports structured filters, "
        "sorting, and a bounded row limit."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "entity_id": {
                "type": "string",
                "minLength": 1,
                "title": "Entity",
                "description": "Business Entity whose published head is read.",
                "x-refraq-ref": "entity",
            },
            "match": {
                "type": "string",
                "enum": ["all", "any"],
                "default": "all",
                "title": "Match",
                "description": "all requires every filter condition; any requires at least one.",
            },
            "filters": {
                "type": "array",
                "title": "Filters",
                "description": "Optional structured conditions combined by Match.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["attribute", "op"],
                    "properties": {
                        "attribute": {
                            "type": "string",
                            "minLength": 1,
                            "title": "Attribute",
                            "description": "Head attribute name or row_id.",
                            "x-refraq-ref": "entity_attribute",
                        },
                        "op": {
                            "type": "string",
                            "enum": list(_OPERATORS),
                            "title": "Operator",
                            "description": "Comparison operator supported by the attribute.",
                        },
                        "negate": {
                            "type": "boolean",
                            "default": False,
                            "title": "Negate",
                            "description": "Wrap this condition in NOT.",
                        },
                        "value": {
                            "type": "string",
                            "title": "Value",
                            "description": "Template or literal value for the selected operator.",
                            "x-refraq-template": {"from": "entity_attribute"},
                        },
                    },
                    "allOf": [
                        {
                            "if": {
                                "properties": {"op": {"enum": list(_NEEDS_VALUE)}},
                                "required": ["op"],
                            },
                            "then": {"required": ["value"]},
                        }
                    ],
                },
            },
            "where": {
                "type": ["string", "null"],
                "title": "Advanced filter AST",
                "description": "Optional JSON template resolving to a canonical Entity filters object.",
                "x-refraq-template": {"type": "object"},
            },
            "sort_attribute": {
                "type": ["string", "null"],
                "title": "Sort attribute",
                "description": "Optional head attribute or row_id to sort by. Null defaults to row_id.",
            },
            "sort_direction": {
                "type": "string",
                "enum": ["asc", "desc"],
                "default": "asc",
                "title": "Sort direction",
                "description": "asc or desc.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": ITEM_LIMIT,
                "default": _DEFAULT_LIMIT,
                "title": "Limit",
                "description": "Maximum rows returned in one execution (1 to 100000). Default 1000.",
            },
            "statement_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": _DEFAULT_TIMEOUT_SEC,
                "title": "Statement timeout",
                "description": "Seconds for the read. Default 60.",
            },
        },
        ["entity_id"],
    ),
    output_view=OutputView(kind="rows", rows="rows", metrics=("count", "total")),
    execute=_execute,
    refine=_refine,
    check=_check,
)
