"""Global Variable node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, EngineHooks, NodeResult, NodeType
from backend.channel.variables import VALUE_MAX_BYTES, get_variable_store, valid_name, value_size
from backend.core.time import format_instant

__all__ = ["NODE_TYPE"]

_JSON = {"type": ["object", "array", "string", "number", "boolean", "null"]}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "found", "value", "applied", "expires_at"],
            "properties": {
                "name": {"type": "string"},
                "found": {"type": "boolean"},
                "value": _JSON,
                "applied": {"type": "boolean"},
                "expires_at": {"type": ["string", "null"]},
            },
        }
    }


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    operation = str(config.get("operation") or "")
    rendered, error = render_field(hooks, config.get("name"), {"type": "string"})
    if error is not None:
        return error
    name = str(rendered)
    if not valid_name(name):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Variable name is invalid",
        )
    value = None
    expected = None
    writes = operation in {"set", "set_if_absent", "compare_and_set"}
    if writes:
        value, error = render_field(hooks, config.get("value"), _JSON)
        if error is not None:
            return error
        if value_size(value) > VALUE_MAX_BYTES:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_VARIABLE_TOO_LARGE",
                error_message="Variable value exceeds 64 KiB",
            )
    if operation == "compare_and_set":
        expected, error = render_field(hooks, config.get("expected"), _JSON)
        if error is not None:
            return error
    ttl_sec = config.get("ttl_sec") if writes else None
    result = get_variable_store().apply(
        operation=operation,
        name=name,
        value=value,
        expected=expected,
        ttl_sec=ttl_sec,
    )
    expires = format_instant(result.expires_at) if result.expires_at is not None else None
    return NodeResult(
        status="succeeded",
        output={
            "name": result.name,
            "found": result.found,
            "value": result.value,
            "applied": result.applied,
            "expires_at": expires,
        },
    )
NODE_TYPE = NodeType(
    type_id="state.variable",
    family="state",
    label="Global variable",
    summary="Reads or writes one site-wide named JSON value.",
    description=(
        "Gets, sets, deletes, sets if absent, or compares and sets a Global Variable. "
        "A write takes effect immediately and is not rolled back when the run fails. "
        "An optional expiry lets a lease release itself."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["get", "set", "delete", "set_if_absent", "compare_and_set"],
                "title": "Operation",
                "description": "get, set, delete, set_if_absent, or compare_and_set.",
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "title": "Name",
                "description": "Variable name. Letters, digits, and _ . : - up to 128 characters.",
                "x-refraq-template": {"type": "string"},
            },
            "value": {
                "type": "string",
                "title": "Value",
                "description": "JSON value template for set, set_if_absent, and compare_and_set.",
                "x-refraq-template": _JSON,
            },
            "expected": {
                "type": "string",
                "title": "Expected",
                "description": "JSON value the compare_and_set must match.",
                "x-refraq-template": _JSON,
            },
            "ttl_sec": {
                "type": ["integer", "null"],
                "minimum": 1,
                "title": "Expiry",
                "description": "Seconds until the written value expires. Null keeps it until deleted.",
            },
        },
        "required": ["operation", "name"],
    },
    execute=_execute,
    refine=_refine,
)
