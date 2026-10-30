"""Until node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.iteration_volume import append_round
from backend.channel.item_limit import ITEM_LIMIT
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    ContainerBody,
    ContainerSpec,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    PortSpec,
    object_schema,
)

__all__ = ["NODE_TYPE"]

_BOOL = {"type": "boolean"}
_CAP_MESSAGE = "Until reached max_iterations before its condition became true."
_CONFIG_MESSAGE = "max_iterations must be an integer from 1 through 100000"
_VOLUME_MESSAGE = "Until iteration output exceeds 16 MiB."
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


def _max_iterations(node: Mapping[str, Any]) -> int | None:
    config = node.get("config")
    if not isinstance(config, dict):
        return None
    value = config.get("max_iterations")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > ITEM_LIMIT:
        return None
    return value


def _run(
    node: Mapping[str, Any], hooks: EngineHooks, body: ContainerBody
) -> NodeResult:
    """Repeat the loop body until the boolean template is true."""
    del hooks
    cap = _max_iterations(node)
    if cap is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_CONFIG_INVALID",
            error_message=_CONFIG_MESSAGE,
        )
    previous: Any = None
    collected: list[Any] = []
    for index in range(cap):
        outputs = body.run_round(
            {"previous": previous, "index": index},
            record={"index": index},
        )
        failed = append_round(collected, outputs, message=_VOLUME_MESSAGE)
        if failed is not None:
            return failed
        value, error = body.evaluate_round_template("until", _BOOL)
        if error is not None:
            return error
        if value:
            return NodeResult(
                status="succeeded",
                output={"index": index, "count": index + 1, "iterations": collected},
                ports=frozenset({"done"}),
            )
        previous = outputs
    return NodeResult(
        status="failed",
        error_code="CHANNEL_UNTIL_MAX_ITERATIONS",
        error_message=_CAP_MESSAGE,
        output={"index": cap - 1, "count": cap, "iterations": collected},
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
    container=ContainerSpec(run=_run, round_templates=("until",)),
    refine=_refine,
)
