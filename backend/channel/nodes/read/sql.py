"""SQL read node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType
from backend.channel.values import LIST_OF_OBJECTS

__all__ = ["NODE_TYPE"]

_ROWS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "count", "rowcount"],
    "properties": {
        "rows": LIST_OF_OBJECTS,
        "count": {"type": "integer"},
        "rowcount": {"type": ["integer", "null"]},
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
    type_id="read.sql",
    family="read",
    label="SQL",
    summary="Runs one SQL statement on the entity database or a registered Source.",
    description=(
        "The source is required: the entity database, or one registered Source. "
        "On the entity database, unqualified names resolve in schema entity_data. "
        "The statement text is a template, and expression results are spliced as text. "
        "The node returns the driver result."
    ),
    entry=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {
                "type": "object",
                "additionalProperties": False,
                "title": "Source",
                "description": "Entity database or a registered Source.",
                "x-refraq-ref": "sql_source",
                "required": ["kind"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["entity", "source"],
                        "title": "Kind",
                        "description": "entity selects the entity database. source selects a registered Source.",
                    },
                    "source_id": {
                        "type": "string",
                        "minLength": 1,
                        "title": "Source",
                        "description": "Registered Source id. Required when kind is source.",
                    },
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {"kind": {"const": "source"}},
                            "required": ["kind"],
                        },
                        "then": {"required": ["source_id"]},
                    },
                    {
                        "if": {
                            "properties": {"kind": {"const": "entity"}},
                            "required": ["kind"],
                        },
                        "then": {"properties": {"source_id": False}},
                    },
                ],
            },
            "sql": {
                "type": "string",
                "minLength": 1,
                "title": "SQL",
                "description": (
                    "One SQL statement. Each {{ }} result is spliced as text. "
                    "Quote literals in the statement."
                ),
                "x-refraq-template": {"type": "string"},
            },
            "statement_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": 30,
                "title": "Statement timeout",
                "description": "Seconds before the statement is cancelled. Default 30.",
            },
        },
        "required": ["source", "sql"],
    },
    refine=_refine,
)
