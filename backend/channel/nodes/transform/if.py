"""If node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    PortSpec,
    object_schema,
)

__all__ = ["NODE_TYPE"]

_BOOL = {"type": "boolean"}
_VALUE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["value"],
    "properties": {"value": {"type": "boolean"}},
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"true": _VALUE, "false": _VALUE}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    value, error = render_field(
        hooks, node["config"].get("condition"), _BOOL, path="condition"
    )
    if error is not None:
        return error
    live = "true" if value else "false"
    return NodeResult(
        status="succeeded",
        output={"value": value},
        ports=frozenset({live}),
    )


NODE_TYPE = NodeType(
    type_id="transform.if",
    family="transform",
    label="If",
    summary="Routes the run down the true or the false output.",
    description=(
        "The condition is a boolean template evaluated once. "
        "The live output is true when the condition is true, and false otherwise. "
        "Both ports carry the object {value: bool}. A dead branch does not run."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(
        PortSpec("true", "Taken when the condition is true.", coarse_type="object"),
        PortSpec("false", "Taken when the condition is false.", coarse_type="object"),
    ),
    config_schema=object_schema(
        {
            "condition": {
                "type": "string",
                "minLength": 1,
                "title": "Condition",
                "description": "Boolean template. Text with no {{ }} is parsed once as JSON.",
                "x-refraq-template": {"type": "boolean"},
            }
        },
        ["condition"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
)
