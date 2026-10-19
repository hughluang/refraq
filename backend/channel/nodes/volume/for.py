"""For node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import MAIN_INPUT, EngineHooks, NodeResult, NodeType, PortSpec, object_schema

__all__ = ["NODE_TYPE"]

_ITEM_LIMIT = 100_000
_ARRAY = {"type": "array"}

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


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    items, error = render_field(hooks, node["config"].get("items"), _ARRAY)
    if error is not None:
        return error
    if len(items) > _ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message="For items exceed 100000 elements",
        )
    count = len(items)
    iterations = [
        {"current": item, "index": index, "count": count} for index, item in enumerate(items)
    ]
    if count == 0:
        current: Any = None
        index: int | None = None
    else:
        current = items[-1]
        index = count - 1
    return NodeResult(
        status="succeeded",
        output={"current": current, "index": index, "count": count, "results": []},
        iterations=iterations,
        ports=frozenset({"done"}),
    )


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
    execute=_execute,
    refine=_refine,
)
