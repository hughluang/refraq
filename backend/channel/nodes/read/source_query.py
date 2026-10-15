"""Live Source query node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema
from backend.channel.values import LIST_OF_OBJECTS

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
    entry=False,
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
    permission="channel:source_query",
    refine=_refine,
)
