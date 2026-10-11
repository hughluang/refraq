"""Manual trigger node type."""

from __future__ import annotations

from backend.channel.nodes.spec import MAIN_OUTPUT, NodeType, object_schema

__all__ = ["NODE_TYPE"]

NODE_TYPE = NodeType(
    type_id="trigger.manual",
    family="trigger",
    label="Manual trigger",
    summary="Starts a run when an operator asks for one by hand.",
    description=(
        "Entry point of a Data Channel. An operator with channel:write starts the "
        "run from the Console, including while the channel is inactive. The run "
        "begins with no upstream items."
    ),
    entry=True,
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
)
