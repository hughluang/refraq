"""Error-workflow trigger node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import (
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.jobs.store import get_job_store

__all__ = ["NODE_TYPE"]

_TEST_CODE = "CHANNEL_ERROR_TRIGGER_TEST"


def _test_payload(hooks: EngineHooks) -> dict[str, Any]:
    actor = hooks.actor
    return {
        "channel_id": None,
        "channel_name": None,
        "job_id": None,
        "version": None,
        "attempt": 0,
        "error": {
            "code": _TEST_CODE,
            "message": "Error trigger test",
            "node_id": None,
        },
        "triggered_by": {"id": actor["id"], "name": actor["name"]},
        "triggered_at": hooks.started_at,
    }


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    del node
    job = get_job_store().get(hooks.run_id)
    source = (job.input or {}).get("error_source") if job is not None else None
    output = source if isinstance(source, dict) else _test_payload(hooks)
    return NodeResult(status="succeeded", output=output)


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    text = {"type": ["string", "null"]}
    return {
        "main": object_schema(
            {
                "channel_id": text,
                "channel_name": text,
                "job_id": text,
                "version": {"type": ["integer", "null"]},
                "attempt": {"type": "integer"},
                "error": object_schema(
                    {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "node_id": text,
                    },
                    ["code", "message", "node_id"],
                ),
                "triggered_by": {"type": ["object", "null"]},
                "triggered_at": {"type": "string"},
            },
            [
                "channel_id",
                "channel_name",
                "job_id",
                "version",
                "attempt",
                "error",
                "triggered_by",
                "triggered_at",
            ],
        )
    }


NODE_TYPE = NodeType(
    type_id="trigger.error",
    family="trigger",
    label="Error trigger",
    summary="Starts when another channel's published failure has nowhere left to retry.",
    description=(
        "The only trigger of an error workflow. A real start carries the failed "
        "run's identity. A manual run is a test and carries empty source ids."
    ),
    trigger=True,
    inputs=(),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema({}, []),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
)
