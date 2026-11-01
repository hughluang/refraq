"""SQL read node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
)
from backend.channel.sql_read import SqlReadError, run_channel_sql
from backend.channel.values import LIST_OF_OBJECTS

__all__ = ["NODE_TYPE"]

_JSON_SCALAR = {"type": ["string", "number", "boolean", "null"]}

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


def _bound_params(
    hooks: EngineHooks, raw: Any
) -> tuple[list[Any] | None, NodeResult | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_VALUE_TYPE_MISMATCH",
            error_message="Parameters must be a list",
        )
    values: list[Any] = []
    for index, item in enumerate(raw):
        value, error = render_field(hooks, item, _JSON_SCALAR, path=f"params.{index}")
        if error is not None:
            return None, error
        values.append(value)
    return values, None


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    statement, error = render_field(
        hooks, config.get("sql"), {"type": "string"}, path="sql"
    )
    if error is not None:
        return error
    params, error = _bound_params(hooks, config.get("params"))
    if error is not None:
        return error
    try:
        if params is None:
            output = run_channel_sql(
                str(statement),
                source=config["source"],
                statement_timeout_sec=config.get("statement_timeout_sec", 30),
            )
        else:
            output = run_channel_sql(
                str(statement),
                source=config["source"],
                statement_timeout_sec=config.get("statement_timeout_sec", 30),
                params=params,
            )
    except SqlReadError as exc:
        return NodeResult(status="failed", error_code=exc.code, error_message=exc.message)
    return NodeResult(status="succeeded", output=output)


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    source = config["source"]
    if source.get("kind") != "source":
        return []
    source_id = source["source_id"]
    if resolver.source_exists(source_id):
        return []
    return [
        Problem(
            "CHANNEL_REFERENCE_UNRESOLVED",
            f"Source does not resolve: {source_id}",
        )
    ]


NODE_TYPE = NodeType(
    type_id="read.sql",
    family="read",
    label="SQL",
    summary="Runs one SQL statement on the entity database or a registered Source.",
    description=(
        "The source is required: the entity database, or one registered Source. "
        "On the entity database, unqualified names resolve in schema entity_data. "
        "The statement text is a template, and expression results are spliced as text. "
        "Optional parameters are bound by the driver and are not spliced into the statement. "
        "The node returns the driver result."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
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
            "params": {
                "type": "array",
                "title": "Parameters",
                "description": (
                    "Optional bound values, in positional order. "
                    "Each item renders to one JSON scalar or null and is passed "
                    "to the driver. It is not spliced into the statement."
                ),
                "items": {
                    "type": "string",
                    "title": "Parameter",
                    "description": (
                        "Template for one bound value. "
                        "The result must be a string, number, boolean, or null."
                    ),
                    "x-refraq-template": _JSON_SCALAR,
                },
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
    output_view=OutputView(kind="rows", rows="rows", metrics=("count", "rowcount")),
    execute=_execute,
    refine=_refine,
    check=_check,
)
