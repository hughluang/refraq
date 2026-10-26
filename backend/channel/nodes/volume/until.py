"""Until node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT
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

_ANY_OBJECT: dict[str, Any] = {"type": ["object", "null"]}
_EACH: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["previous", "index"],
    "properties": {
        "previous": _ANY_OBJECT,
        "index": {"type": "integer"},
    },
}
_DONE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["index", "count", "iterations"],
    "properties": {
        "index": {"type": "integer"},
        "count": {"type": "integer"},
        "iterations": {"type": "array"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"each": _EACH, "done": _DONE}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    """Succeed once. The engine owns the rounds; this result does not list them."""
    del node, hooks
    return NodeResult(
        status="succeeded",
        output={"index": 0, "count": 0, "iterations": []},
        ports=frozenset({"done"}),
    )


NODE_TYPE = NodeType(
    type_id="volume.until",
    family="volume",
    label="Until",
    summary="Runs its loop body again until a condition becomes true.",
    description=(
        "The until template is a boolean evaluated after each round. "
        "True stops the container and the done output then runs. "
        "max_iterations is required and is a positive integer through 100000, with no default. "
        "Each round exposes previous and index. The stored output is index, count, and iterations."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(
        PortSpec(
            "each",
            "Starts one round. Connects only to direct children of this Until.",
            coarse_type="object",
        ),
        PortSpec("done", "Taken after the condition becomes true.", coarse_type="object"),
    ),
    config_schema=object_schema(
        {
            "until": {
                "type": "string",
                "minLength": 1,
                "title": "Until",
                "description": (
                    "Boolean template evaluated after each round. "
                    "True stops the container. Text with no {{ }} is parsed once as JSON."
                ),
                "x-refraq-template": {"type": "boolean"},
            },
            "max_iterations": {
                "type": "integer",
                "minimum": 1,
                "maximum": ITEM_LIMIT,
                "title": "Max iterations",
                "description": (
                    "Most rounds this Until may run. "
                    "Required. An integer from 1 through 100000, with no default."
                ),
            },
        },
        ["until", "max_iterations"],
    ),
    output_view=OutputView(kind="container", metrics=("count",), item="index"),
    execute=_execute,
    refine=_refine,
)
