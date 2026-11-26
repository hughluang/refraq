"""Call Sub-channel action node type."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.channel.node_support import record_execution_input_error, render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.channel.subchannel import param_input_schema

__all__ = ["NODE_TYPE"]

_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job_id", "channel_id", "version", "outcome", "result"],
    "properties": {
        "job_id": {"type": "string"},
        "channel_id": {"type": "string"},
        "version": {"type": "integer"},
        "outcome": {"type": "string", "enum": ["completed", "skipped"]},
        "result": {},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _OUTPUT_SCHEMA, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    channel_id = str(config.get("channel_id") or "")
    raw_inputs = config.get("inputs") if isinstance(config.get("inputs"), Mapping) else {}
    prepared, preflight_failure = hooks.prepare_subchannel_call(channel_id)
    if preflight_failure is not None:
        return preflight_failure
    param_schemas = {
        param.name: param_input_schema(param) for param in prepared.params
    }
    rendered_inputs: dict[str, Any] = {}
    for key, raw_template in raw_inputs.items():
        name = str(key)
        expected = param_schemas.get(name, _ANY)
        rendered, failure = render_field(
            hooks, raw_template, expected, path=f"inputs.{name}"
        )
        if failure is not None:
            if failure.error_code == "CHANNEL_VALUE_TYPE_MISMATCH":
                msg = failure.error_message or ""
                record_execution_input_error(
                    f"inputs.{name}", "CHANNEL_SUBCHANNEL_INPUT_INVALID", msg
                )
                return NodeResult(
                    status="failed",
                    error_code="CHANNEL_SUBCHANNEL_INPUT_INVALID",
                    error_message=msg,
                    error_detail={
                        "details": [
                            {"field": name, "code": "type_mismatch", "message": msg}
                        ]
                    },
                )
            return failure
        rendered_inputs[name] = rendered
    return hooks.call_subchannel(
        prepared=prepared,
        inputs=rendered_inputs,
        caller_node_id=str(node.get("id") or ""),
    )


NODE_TYPE = NodeType(
    type_id="action.call_channel",
    family="action",
    label="Call Sub-channel",
    summary="Runs another published Sub Data Channel synchronously and reads its return value.",
    description=(
        "Invokes the latest published version of an active Data Channel whose "
        "trigger is Sub-channel trigger. Input templates are checked against "
        "the sub-channel's parameter contract, and a real child Channel Run is "
        "recorded and linked."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "channel_id": {
                "type": "string",
                "minLength": 1,
                "title": "Sub-channel",
                "description": "Published Data Channel whose trigger is Sub-channel trigger.",
                "x-refraq-ref": "subchannel",
            },
            "inputs": {
                "type": "object",
                "default": {},
                "title": "Inputs",
                "description": "Parameter names mapped to template strings.",
                "additionalProperties": {
                    "type": "string",
                    "x-refraq-template": {"from": "subchannel_input"},
                },
            },
        },
        ["channel_id"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
)
