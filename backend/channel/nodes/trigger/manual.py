"""Manual trigger node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import (
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
    object_schema,
)

__all__ = ["NODE_TYPE"]

_RESERVED_PAYLOAD = frozenset({"triggered_by", "triggered_at"})


def _json_schema(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array"}
    if isinstance(value, dict):
        properties = {key: _json_schema(item) for key, item in value.items()}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }
    return {"type": "string"}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream, resolver
    payload = config.get("payload") if isinstance(config, Mapping) else None
    if not isinstance(payload, dict):
        payload = {}
    properties = {
        key: _json_schema(value)
        for key, value in payload.items()
        if key not in _RESERVED_PAYLOAD
    }
    properties["triggered_by"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        },
    }
    properties["triggered_at"] = {"type": "string"}
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }
    }


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    payload = dict((node.get("config") or {}).get("payload") or {})
    actor = hooks.actor
    payload["triggered_by"] = {"id": actor["id"], "name": actor["name"]}
    payload["triggered_at"] = hooks.started_at
    return NodeResult(status="succeeded", output=payload)


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    payload = config.get("payload") or {}
    if _RESERVED_PAYLOAD & set(payload):
        return [
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "Manual payload uses a reserved key",
                path=("payload",),
            )
        ]
    return []


NODE_TYPE = NodeType(
    type_id="trigger.manual",
    family="trigger",
    label="Manual trigger",
    summary="Starts a run when an operator asks for one by hand.",
    description=(
        "Trigger of a Data Channel. An operator with channel:write starts the "
        "run from the Console, including while the channel is inactive. The run "
        "begins with no upstream items."
    ),
    trigger=True,
    inputs=(),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "payload": {
                "type": "object",
                "title": "Output",
                "description": (
                    "JSON object copied into this node's output. "
                    "triggered_by and triggered_at are added by the run."
                ),
                "x-refraq-ref": "json",
            },
        },
        [],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
    check=_check,
)
