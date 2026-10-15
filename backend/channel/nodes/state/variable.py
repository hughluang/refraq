"""Global Variable node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType

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
                "dry_run": {"type": "boolean"},
            },
        }
    }


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
    entry=False,
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
    refine=_refine,
)
