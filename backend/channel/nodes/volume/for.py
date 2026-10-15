"""For node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, NodeType, PortSpec, object_schema

__all__ = ["NODE_TYPE"]

_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}
_STEP: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["current", "index", "count"],
    "properties": {
        "current": _ANY,
        "index": {"type": ["integer", "null"]},
        "count": {"type": "integer"},
    },
}
_DONE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["current", "index", "count", "results"],
    "properties": {
        "current": _ANY,
        "index": {"type": ["integer", "null"]},
        "count": {"type": "integer"},
        "results": {"type": "array"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"each": _STEP, "done": _DONE}


NODE_TYPE = NodeType(
    type_id="volume.for",
    family="volume",
    label="For",
    summary="Runs its loop body once for each element of a list.",
    description=(
        "The items template is a JSON array of at most 100000 elements. "
        "Each iteration exposes current, index, and count on this node. "
        "The done output adds results collected from the loop input. "
        "An empty list runs the body zero times and sets current and index to null."
    ),
    entry=False,
    inputs=(
        MAIN_INPUT,
        PortSpec("loop", "Return edge that collects one result per iteration.", coarse_type="object"),
    ),
    outputs=(
        PortSpec(
            "each",
            "Starts the loop body. One iteration per element.",
            loop_back=True,
            coarse_type="object",
        ),
        PortSpec("done", "Taken after every iteration has finished.", coarse_type="object"),
    ),
    config_schema=object_schema(
        {
            "items": {
                "type": "string",
                "minLength": 1,
                "title": "Items",
                "description": (
                    "JSON array template. Elements may be any JSON value. "
                    "More than 100000 elements fails the node."
                ),
                "x-refraq-template": {"type": "array"},
            }
        },
        ["items"],
    ),
    refine=_refine,
)
