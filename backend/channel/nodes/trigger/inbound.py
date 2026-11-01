"""Inbound trigger node type."""

from __future__ import annotations

import re
from typing import Any, Mapping

from backend.channel.nodes.spec import (
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
    object_schema,
)

__all__ = ["NODE_TYPE"]

_PATH = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_JSON_TYPES = ["string", "integer", "number", "boolean", "object", "array"]


def build_inbound_trigger_output(
    request: Mapping[str, Any] | None,
    *,
    received_at: str,
) -> dict[str, Any]:
    """Trigger output for one request.

    A missing request is the test-run default. A later caller can pass the
    live request, including raw_body and event_id, through this function.
    """
    source = request if isinstance(request, Mapping) else {}
    method = source.get("method")
    if not isinstance(method, str) or method == "":
        method = "POST"
    return {
        "method": method,
        "headers": _headers(source.get("headers")),
        "query": _query(source.get("query")),
        "body": source.get("body") if isinstance(request, Mapping) and "body" in source else None,
        "raw_body": source.get("raw_body") if isinstance(request, Mapping) and "raw_body" in source else None,
        "event_id": source.get("event_id") if isinstance(request, Mapping) and "event_id" in source else None,
        "received_at": received_at,
    }


def _headers(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key).lower(): item for key, item in value.items()}


def _query(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


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
            "required": [
                "method",
                "headers",
                "query",
                "body",
                "raw_body",
                "event_id",
                "received_at",
            ],
            "properties": {
                "method": {"type": "string"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "query": {"type": "object"},
                "body": {},
                "raw_body": {"type": ["string", "null"]},
                "event_id": {"type": ["string", "null"]},
                "received_at": {"type": "string"},
            },
        }
    }


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    sample = config.get("sample_request") if isinstance(config, Mapping) else None
    request = sample if isinstance(sample, Mapping) else None
    return NodeResult(
        status="succeeded",
        output=build_inbound_trigger_output(request, received_at=hooks.started_at),
    )


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    path = config.get("path")
    if not isinstance(path, str) or _PATH.fullmatch(path) is None:
        return [
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "Path must be 1 to 64 characters from a-z, 0-9, and hyphen, and must not start or end with a hyphen",
                path=("path",),
            )
        ]
    response = config.get("response")
    if isinstance(response, dict):
        mode = response.get("mode")
        foreign: list[str] = []
        if mode == "immediate":
            foreign = [key for key in ("wait_sec", "fallback") if key in response]
        elif mode == "respond_node":
            foreign = [
                key
                for key in ("status", "content_type", "headers", "body")
                if key in response
            ]
        if foreign:
            return [
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    "Response fields do not belong to this mode",
                    path=("response", foreign[0]),
                )
            ]
    return []


def _field(title: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"title": title, "description": description, **schema}


_INPUT_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "type", "required"],
    "properties": {
        "name": _field(
            "Name",
            "Field name on the parsed body.",
            {"type": "string", "minLength": 1},
        ),
        "type": _field(
            "Type",
            "JSON type required of this field.",
            {"type": "string", "enum": _JSON_TYPES},
        ),
        "required": _field(
            "Required",
            "Whether a missing field refuses the request.",
            {"type": "boolean"},
        ),
    },
}

_STATIC_OR_ECHO = {
    "type": "object",
    "additionalProperties": False,
    "title": "Body",
    "description": "Static text, or one value echoed from the query or the parsed body.",
    "required": ["kind"],
    "properties": {
        "kind": _field(
            "Kind",
            "static sends text. echo copies one query or body value.",
            {"type": "string", "enum": ["static", "echo"]},
        ),
        "text": _field(
            "Text",
            "Static response text. Required when kind is static.",
            {"type": "string"},
        ),
        "from": _field(
            "From",
            "query or body. Required when kind is echo.",
            {"type": "string", "enum": ["query", "body"]},
        ),
        "key": _field(
            "Key",
            "Query name or dotted body path. Required when kind is echo.",
            {"type": "string", "minLength": 1},
        ),
    },
    "allOf": [
        {
            "if": {
                "properties": {"kind": {"const": "static"}},
                "required": ["kind"],
            },
            "then": {"required": ["text"]},
        },
        {
            "if": {
                "properties": {"kind": {"const": "echo"}},
                "required": ["kind"],
            },
            "then": {"required": ["from", "key"]},
        },
    ],
}

_RESPONSE = {
    "type": "object",
    "additionalProperties": False,
    "title": "Response",
    "description": "How the caller is answered. immediate replies at once. respond_node waits for a Respond node.",
    "required": ["mode"],
    "properties": {
        "mode": _field(
            "Mode",
            "immediate or respond_node.",
            {"type": "string", "enum": ["immediate", "respond_node"]},
        ),
        "status": _field(
            "Status",
            "HTTP status for immediate mode, from 100 to 599. Omitted means 200.",
            {"type": "integer", "minimum": 100, "maximum": 599, "default": 200},
        ),
        "content_type": _field(
            "Content type",
            "Content type for immediate mode. Omitted means application/json.",
            {"type": "string", "default": "application/json"},
        ),
        "headers": _field(
            "Headers",
            "Static response headers for immediate mode.",
            {"type": "object", "additionalProperties": {"type": "string"}},
        ),
        "body": _STATIC_OR_ECHO,
        "wait_sec": _field(
            "Wait",
            "Seconds respond_node mode waits for a Respond node, from 1 to 30. Omitted means 5.",
            {"type": "integer", "minimum": 1, "maximum": 30, "default": 5},
        ),
        "fallback": {
            "type": "object",
            "additionalProperties": False,
            "title": "Fallback",
            "description": "Response sent when respond_node mode waits too long.",
            "properties": {
                "status": _field(
                    "Status",
                    "HTTP status from 100 to 599. Omitted means 503.",
                    {"type": "integer", "minimum": 100, "maximum": 599, "default": 503},
                ),
                "body": _field(
                    "Body",
                    "Optional static fallback text.",
                    {"type": "string"},
                ),
            },
        },
    },
    "allOf": [
        {
            "if": {
                "properties": {"mode": {"const": "immediate"}},
                "required": ["mode"],
            },
            "then": {"required": ["body"]},
        }
    ],
}


NODE_TYPE = NodeType(
    type_id="trigger.inbound",
    family="trigger",
    label="Inbound",
    summary="Starts a run when a third party calls the published path.",
    description=(
        "Trigger of a Data Channel. Publish registers this path for the channel. "
        "A test run copies the sample request into the trigger output."
    ),
    trigger=True,
    inputs=(),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "path": _field(
                "Path",
                "Public path of 1 to 64 characters from a-z, 0-9, and hyphen, not starting or ending with a hyphen.",
                {"type": "string", "minLength": 1, "maxLength": 64},
            ),
            "allow_get": _field(
                "Allow GET",
                "Whether GET is accepted in addition to POST. Omitted means false.",
                {"type": "boolean", "default": False},
            ),
            "credential_id": _field(
                "Credential",
                "Inbound Credential that authenticates the caller.",
                {"type": "string", "minLength": 1},
            ),
            "input": _field(
                "Input",
                "Declared fields of a parsed body. Undeclared keys pass through.",
                {"type": "array", "items": _INPUT_ITEM},
            ),
            "event_id": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "key"],
                "title": "Event id",
                "description": "Where the event id lives. Absent means no deduplication.",
                "properties": {
                    "from": _field(
                        "From",
                        "header, query, or body.",
                        {"type": "string", "enum": ["header", "query", "body"]},
                    ),
                    "key": _field(
                        "Key",
                        "Header name, query name, or dotted body path.",
                        {"type": "string", "minLength": 1},
                    ),
                },
            },
            "dedup_window_sec": _field(
                "Dedup window",
                "Seconds a repeated event id is held, from 60 to 604800. Omitted means 86400.",
                {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": 604800,
                    "default": 86400,
                },
            ),
            "max_in_flight": _field(
                "In-flight cap",
                "Unfinished runs this trigger may hold, from 1 to 1000. Omitted means 10.",
                {"type": "integer", "minimum": 1, "maximum": 1000, "default": 10},
            ),
            "response": _RESPONSE,
            "sample_request": {
                "type": "object",
                "additionalProperties": False,
                "title": "Sample request",
                "description": "Request a test run uses as this node's output.",
                "properties": {
                    "method": _field(
                        "Method",
                        "HTTP method copied into the test-run output.",
                        {"type": "string", "minLength": 1},
                    ),
                    "headers": _field(
                        "Headers",
                        "Header values. Names are lowercased in the output.",
                        {"type": "object", "additionalProperties": {"type": "string"}},
                    ),
                    "query": _field(
                        "Query",
                        "Query parameters copied into the test-run output.",
                        {"type": "object", "additionalProperties": {"type": "string"}},
                    ),
                    "body": _field(
                        "Body",
                        "Parsed body copied into the test-run output.",
                        {},
                    ),
                },
            },
        },
        ["path", "credential_id", "response"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
    check=_check,
)
