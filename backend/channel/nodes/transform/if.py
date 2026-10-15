"""If node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, NodeType, PortSpec, object_schema

__all__ = ["NODE_TYPE"]

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
    entry=False,
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
    refine=_refine,
)
