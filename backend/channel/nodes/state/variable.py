"""Global Variable node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
)
from backend.channel.variables import (
    VALUE_MAX_BYTES,
    apply_records,
    get_variable_store,
    valid_name,
    value_size,
)
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


def _scope(config: Mapping[str, Any]) -> str | None:
    if "scope" not in config:
        return "site"
    raw = config["scope"]
    if raw in {"site", "channel", "run"}:
        return str(raw)
    return None


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    scope = _scope(config)
    if scope is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Variable scope is invalid",
        )
    if scope == "run" and config.get("ttl_sec") is not None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Variable expiry is not valid for this run",
        )
    operation = str(config.get("operation") or "")
    rendered, error = render_field(
        hooks, config.get("name"), {"type": "string"}, path="name"
    )
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
        value, error = render_field(hooks, config.get("value"), _JSON, path="value")
        if error is not None:
            return error
        if value_size(value) > VALUE_MAX_BYTES:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_VARIABLE_TOO_LARGE",
                error_message="Variable value exceeds 64 KiB",
            )
    if operation == "compare_and_set":
        expected, error = render_field(
            hooks, config.get("expected"), _JSON, path="expected"
        )
        if error is not None:
            return error
    ttl_sec = config.get("ttl_sec") if writes else None
    if scope == "run":
        result = apply_records(
            hooks.run_variables,
            operation=operation,
            name=name,
            value=value,
            expected=expected,
            ttl_sec=ttl_sec,
        )
    else:
        result = get_variable_store().apply(
            operation=operation,
            name=name,
            value=value,
            expected=expected,
            ttl_sec=ttl_sec,
            channel_id=hooks.channel_id if scope == "channel" else None,
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
    label="Variable",
    summary="Reads or writes one named JSON value for the site, one channel, or this run.",
    description=(
        "An omitted scope is the site. "
        "A channel value belongs to that channel, and a draft run and a published run see the same value. "
        "A write is visible immediately and is not rolled back when the run fails. "
        "A run value has no expiry and lives only for this execution."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["site", "channel", "run"],
                "default": "site",
                "title": "Scope",
                "description": "site, channel, or run. Omitted is site.",
            },
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
        "allOf": [
            {
                "if": {
                    "properties": {"scope": {"const": "run"}},
                    "required": ["scope"],
                },
                "then": {"properties": {"ttl_sec": {"type": "null"}}},
            }
        ],
    },
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
)
