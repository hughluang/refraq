"""Return action node type for Sub Data Channels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.channel.node_support import render_field
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

__all__ = ["NODE_TYPE"]

_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": None, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    rendered, failure = render_field(hooks, config.get("value"), _ANY, path="value")
    if failure is not None:
        return failure
    hooks.set_return_value(rendered)
    return NodeResult(status="succeeded", output=rendered)


NODE_TYPE = NodeType(
    type_id="action.return",
    family="action",
    label="Return",
    summary="Sets the return value of a Sub-channel run.",
    description=(
        "Evaluates a template to any JSON value or Dataset Reference and "
        "records it as the result returned to a calling Data Channel. "
        "Valid only when the channel's trigger is Sub-channel trigger."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "value": {
                "type": "string",
                "title": "Return value",
                "description": (
                    "Template rendered to any JSON value or Dataset Reference "
                    "returned to the caller as output.result."
                ),
                "x-refraq-template": _ANY,
            }
        },
        ["value"],
    ),
    output_view=OutputView(kind="value"),
    execute=_execute,
    refine=_refine,
)
