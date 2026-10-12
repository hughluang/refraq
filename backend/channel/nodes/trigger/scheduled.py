"""Scheduled trigger node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_OUTPUT, NodeType

__all__ = ["NODE_TYPE"]


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schedule_id", "name", "scheduled_for"],
            "properties": {
                "schedule_id": {"type": ["string", "null"]},
                "name": {"type": "string"},
                "scheduled_for": {"type": "string"},
            },
        }
    }


NODE_TYPE = NodeType(
    type_id="trigger.scheduled",
    family="trigger",
    label="Scheduled trigger",
    summary="Starts a run when the published cadence is due.",
    description=(
        "Entry point of a Data Channel. Publish syncs this node's cadence to one "
        "locked Scheduled Task for the channel. A due tick starts a published run "
        "at this node. The output carries the schedule id, name, and scheduled_for."
    ),
    entry=True,
    inputs=(),
    outputs=(MAIN_OUTPUT,),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cron": {
                "type": ["string", "null"],
                "title": "Cron",
                "description": "Five-field cron, interpreted in the Schedule Timezone. Exactly one of cron or interval.",
            },
            "interval_seconds": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 252460800,
                "title": "Interval",
                "description": "Seconds between runs. Exactly one of cron or interval.",
            },
            "start_at": {
                "type": ["string", "null"],
                "title": "Start",
                "description": "Optional Schedule Start Instant. Absent means start immediately.",
            },
        },
        "required": [],
    },
    refine=_refine,
)
