"""For node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.iteration_volume import append_round
from backend.channel.node_support import render_field
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
from backend.channel.template import schema_at_path
from backend.channel.values import array_item_schema

__all__ = ["NODE_TYPE"]
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
    "required": ["current", "index", "count", "iterations"],
    "properties": {
        "current": _ANY,
        "index": {"type": ["integer", "null"]},
        "count": {"type": "integer"},
        "iterations": {"type": "array"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del resolver
    text = config.get("items")
    item = array_item_schema(schema_at_path(text, upstream)) if isinstance(text, str) else None
    if item is None:
        return {"each": _STEP, "done": _DONE}
    return {
        "each": _with_current(_STEP, item),
        "done": _with_current(_DONE, _nullable(item)),
    }


def _with_current(base: Mapping[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    properties = dict(base["properties"])
    properties["current"] = current
    return {**base, "properties": properties}


def _nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
    kind = schema.get("type")
    if isinstance(kind, str) and kind != "null":
        return {**schema, "type": [kind, "null"]}
    if isinstance(kind, list) and "null" not in kind:
        return {**schema, "type": [*kind, "null"]}
    return dict(schema)


_VOLUME_MESSAGE = "For iteration output exceeds 16 MiB. Read the items in batches."


def _run(node: Mapping[str, Any], hooks: EngineHooks, body: ContainerBody) -> NodeResult:
    items, error = render_field(hooks, node["config"].get("items"), _ARRAY, path="items")
    if error is not None:
        return error
    if len(items) > ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=LIST_ITEM_LIMIT_MESSAGE,
        )
    count = len(items)
    collected: list[Any] = []
    current: Any = None
    index: int | None = None
    for index, item in enumerate(items):
        outputs = body.run_round({"current": item, "index": index, "count": count})
        failed = append_round(collected, outputs, message=_VOLUME_MESSAGE)
        if failed is not None:
            return failed
        current = item
    return NodeResult(
        status="succeeded",
        output={
            "current": current,
            "index": index,
            "count": count,
            "iterations": collected,
        },
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
        "The done output adds iterations, one object per element, keyed by the nodes that ran. "
        "An empty list runs the body zero times and sets current and index to null."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(
        PortSpec(
            "each",
            "Starts one iteration for each element. Connects only to direct children of this For.",
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
    output_view=OutputView(kind="container", metrics=("count",), item="current"),
    container=ContainerSpec(run=_run),
    refine=_refine,
)
