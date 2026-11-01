"""Respond action node type."""

from __future__ import annotations

import json
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
    object_schema,
)

__all__ = ["NODE_TYPE"]

_TEXT: dict[str, Any] = {"type": "string"}
_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}
_STATUS: dict[str, Any] = {"type": "integer", "minimum": 100, "maximum": 599}


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
            "required": ["status", "headers", "body", "delivered"],
            "properties": {
                "status": {"type": "integer"},
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "body": {},
                "delivered": {"type": "boolean"},
            },
        }
    }


def _fail(message: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message=message,
    )


def _status_value(rendered: Any) -> int | None:
    if isinstance(rendered, bool) or not isinstance(rendered, int):
        return None
    if not 100 <= rendered <= 599:
        return None
    return rendered


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    status, failure = render_field(hooks, config.get("status"), _STATUS, path="status")
    if failure is not None:
        return failure
    status_code = _status_value(status)
    if status_code is None:
        return _fail("Status must be an integer from 100 to 599")
    content_type, failure = _content_type(hooks, config.get("content_type"))
    if failure is not None:
        return failure
    headers, failure = _headers(hooks, config.get("headers"))
    if failure is not None:
        return failure
    body, failure = _body(hooks, config)
    if failure is not None:
        return failure
    sent = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    sent["Content-Type"] = content_type
    return NodeResult(
        status="succeeded",
        output={
            "status": status_code,
            "headers": sent,
            "body": body,
            "delivered": False,
        },
    )


def _content_type(
    hooks: EngineHooks, raw: Any
) -> tuple[str, NodeResult | None]:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return "application/json", None
    rendered, failure = render_field(hooks, raw, _TEXT, path="content_type")
    if failure is not None:
        return "", failure
    if not isinstance(rendered, str) or rendered.strip() == "":
        return "application/json", None
    return rendered, None


def _headers(
    hooks: EngineHooks, raw: Any
) -> tuple[dict[str, str], NodeResult | None]:
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return {}, _fail("Headers must be an object")
    headers: dict[str, str] = {}
    for name, item in raw.items():
        rendered, failure = render_field(
            hooks, item, _TEXT, path=f"headers.{name}"
        )
        if failure is not None:
            return {}, failure
        headers[str(name)] = str(rendered)
    return headers, None


def _body(
    hooks: EngineHooks, config: Mapping[str, Any]
) -> tuple[Any, NodeResult | None]:
    if "body" not in config:
        return None, None
    return render_field(hooks, config.get("body"), _ANY, path="body")


def _static_status(text: str) -> int | None:
    if "{{" in text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    status = config.get("status")
    if not isinstance(status, str):
        return []
    value = _static_status(status)
    if value is None or 100 <= value <= 599:
        return []
    return [
        Problem(
            "CHANNEL_NODE_CONFIG_INVALID",
            "Status must be an integer from 100 to 599",
            path=("status",),
        )
    ]


NODE_TYPE = NodeType(
    type_id="action.respond",
    family="action",
    label="Respond",
    summary="Builds the HTTP response for an Inbound Trigger.",
    description=(
        "Status, content type, headers, and body are templates. "
        "A test run records that response with delivered false."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "status": {
                "type": "string",
                "minLength": 1,
                "title": "Status",
                "description": "Template that renders to an integer HTTP status from 100 to 599.",
                "x-refraq-template": _STATUS,
            },
            "content_type": {
                "type": "string",
                "default": "application/json",
                "title": "Content type",
                "description": "Template for the response content type. Omitted means application/json.",
                "x-refraq-template": _TEXT,
            },
            "headers": {
                "type": "object",
                "title": "Headers",
                "description": "Header names mapped to template strings.",
                "additionalProperties": {
                    "type": "string",
                    "x-refraq-template": _TEXT,
                },
            },
            "body": {
                "type": "string",
                "title": "Body",
                "description": (
                    "Template rendered to any JSON value. "
                    "A string is sent as text and any other value as JSON."
                ),
                "x-refraq-template": _ANY,
            },
        },
        ["status"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
    check=_check,
)
