"""Live Source query node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    object_schema,
)
from backend.channel.values import LIST_OF_OBJECTS
from backend.core.errors import AppError
from backend.metadata.query.service import run_controlled_query

__all__ = ["NODE_TYPE"]

_ROWS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "count", "truncated"],
    "properties": {
        "rows": LIST_OF_OBJECTS,
        "count": {"type": "integer"},
        "truncated": {"type": "boolean"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _ROWS}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    statement, error = render_field(hooks, config.get("sql"), {"type": "string"})
    if error is not None:
        return error
    row_cap = config.get("row_cap", 100)
    if not isinstance(row_cap, int) or isinstance(row_cap, bool):
        row_cap = 100
    user = hooks.user
    audit_detail = {
        key: value
        for key, value in {
            "channel_id": hooks.channel_id,
            "job_id": hooks.run_id,
            "node_id": node.get("id"),
        }.items()
        if value
    }
    try:
        outcome = run_controlled_query(
            source_id=str(config["source_id"]),
            sql=str(statement),
            max_rows=row_cap,
            actor_user_id=user.id,
            actor_token_id=None,
            audit_detail=audit_detail or None,
        )
    except AppError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=exc.message,
            error_detail={"code": exc.code},
        )
    rows = [dict(zip(outcome.columns, row)) for row in outcome.rows]
    return NodeResult(
        status="succeeded",
        output={"rows": rows, "count": len(rows), "truncated": outcome.truncated},
    )


NODE_TYPE = NodeType(
    type_id="read.source_query",
    family="read",
    label="Source query",
    summary="Reads a small live result from a registered Source through Controlled Query.",
    description=(
        "Runs one read-only statement on a registered Source through Controlled Query. "
        "The platform applies its timeout, row cap, and query audit. "
        "Rows come back as objects keyed by column name."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "source_id": {
                "type": "string",
                "minLength": 1,
                "title": "Source",
                "description": "Registered Source this query reads.",
                "x-refraq-ref": "source",
            },
            "sql": {
                "type": "string",
                "minLength": 1,
                "title": "SQL",
                "description": (
                    "One SQL statement. Each {{ }} result is spliced as text. "
                    "Quote literals in the statement. "
                    "Controlled Query allows a single read-only statement."
                ),
                "x-refraq-template": {"type": "string"},
            },
            "row_cap": {
                "type": "integer",
                "minimum": 1,
                "default": 100,
                "title": "Row cap",
                "description": (
                    "Maximum rows returned by this node. Default 100. "
                    "A cap above the platform query_max_rows fails the node."
                ),
            },
        },
        ["source_id", "sql"],
    ),
    execute=_execute,
    permission="channel:source_query",
    refine=_refine,
)
