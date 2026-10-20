"""Scheduled trigger node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import (
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    Problem,
    ReferenceResolver,
)
from backend.core.time import parse_instant
from backend.worker.api import validate_cadence, validate_start_at
from backend.worker.errors import ScheduleCadenceInvalid, ScheduleStartAtInvalid

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


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    del node
    schedule = hooks.schedule
    return NodeResult(
        status="succeeded",
        output={
            "schedule_id": schedule.get("schedule_id"),
            "name": schedule.get("name"),
            "scheduled_for": schedule.get("scheduled_for"),
        },
    )


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    cron = config.get("cron")
    cron_text = str(cron).strip() if isinstance(cron, str) and str(cron).strip() else None
    interval = config.get("interval_seconds")
    seconds = interval if isinstance(interval, int) else None
    start = None
    raw_start = config.get("start_at")
    try:
        if isinstance(raw_start, str) and raw_start.strip():
            start = parse_instant(raw_start)
        start = validate_start_at(start)
        validate_cadence(cron=cron_text, interval_seconds=seconds, start_at=start)
    except (ScheduleCadenceInvalid, ScheduleStartAtInvalid, ValueError) as exc:
        return [Problem("CHANNEL_NODE_CONFIG_INVALID", str(exc))]
    return []


NODE_TYPE = NodeType(
    type_id="trigger.scheduled",
    family="trigger",
    label="Scheduled trigger",
    summary="Starts a run when the published cadence is due.",
    description=(
        "Trigger of a Data Channel. Publish syncs this node's cadence to one "
        "locked Scheduled Task for the channel. A due tick starts a published run "
        "at this node. The output carries the schedule id, name, and scheduled_for."
    ),
    trigger=True,
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
    execute=_execute,
    refine=_refine,
    check=_check,
)
