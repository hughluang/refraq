"""Runtime values of ``self.channel``, ``self.run``, and ``self.platform``, and their schema.

The value builders and ``context_schema`` live together so the Console completion
contract cannot drift from what a run actually puts in scope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.admin.system_parameters.registry import list_registered_specs
from backend.admin.system_parameters.resolver import resolve_int, resolve_str
from backend.admin.system_parameters.spec import IntConstraint
from backend.core.time import format_instant

__all__ = [
    "channel_context",
    "context_schema",
    "platform_context",
    "run_context",
]


def channel_context(channel: Any, run: Any) -> dict[str, Any]:
    return {
        "id": channel.id,
        "name": channel.name,
        "description": channel.description,
        "active": channel.active,
        "settings": run.graph.get("settings") or {},
    }


def run_context(
    run: Any,
    started: datetime,
    actor: dict[str, str],
    trigger_kind: str | None,
) -> dict[str, Any]:
    return {
        "id": run.job_id,
        "target": run.target,
        "version": run.version,
        "draft_revision": run.draft_revision,
        "trigger_kind": trigger_kind or "user",
        "started_at": format_instant(started),
        "triggered_by": actor,
    }


def platform_context(started: datetime) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for spec in list_registered_specs():
        if isinstance(spec.constraint, IntConstraint):
            parameters[spec.key] = resolve_int(spec.key).value
        else:
            parameters[spec.key] = resolve_str(spec.key).value
    return {
        "site_name": "",
        "schedule_timezone": parameters["schedule_timezone"],
        "now": format_instant(started),
        "parameters": parameters,
    }


def context_schema() -> dict[str, dict[str, Any]]:
    """JSON Schema for the three context objects, keyed by attribute name."""
    parameter_properties = {
        spec.key: {"type": "integer"}
        if isinstance(spec.constraint, IntConstraint)
        else {"type": "string"}
        for spec in list_registered_specs()
    }
    return {
        "channel": _object(
            {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "active": {"type": "boolean"},
                "settings": _object(
                    {
                        "run_timeout_sec": {"type": ["integer", "null"]},
                        "error_channel_id": {"type": ["string", "null"]},
                    },
                ),
            },
            required=["id", "name", "description", "active", "settings"],
        ),
        "run": _object(
            {
                "id": {"type": "string"},
                "target": {"type": "string"},
                "version": {"type": ["integer", "null"]},
                "draft_revision": {"type": ["integer", "null"]},
                "trigger_kind": {"type": "string"},
                "started_at": {"type": "string"},
                "triggered_by": _object(
                    {"id": {"type": "string"}, "name": {"type": "string"}},
                    required=["id", "name"],
                ),
            },
            required=[
                "id",
                "target",
                "version",
                "draft_revision",
                "trigger_kind",
                "started_at",
                "triggered_by",
            ],
        ),
        "platform": _object(
            {
                "site_name": {"type": "string"},
                "schedule_timezone": {"type": "string"},
                "now": {"type": "string"},
                "parameters": _object(
                    parameter_properties,
                    required=list(parameter_properties),
                ),
            },
            required=["site_name", "schedule_timezone", "now", "parameters"],
        ),
    }


def _object(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required is not None:
        schema["required"] = required
    return schema
