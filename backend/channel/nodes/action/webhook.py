"""Webhook action node type."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
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
from backend.channel.template import TemplateSyntaxError, parse
from backend.channel.webhooks import deliver, get_webhook_store

__all__ = ["NODE_TYPE"]

_BODY = {"type": "string"}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") or {}
    webhook_id = config.get("webhook_id")
    record = get_webhook_store().get(webhook_id) if isinstance(webhook_id, str) else None
    if record is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Webhook was not found",
        )
    rendered, failure = render_field(hooks, config.get("body"), _BODY, path="body")
    if failure is not None:
        return failure
    try:
        payload = json.loads(rendered)
    except (TypeError, json.JSONDecodeError) as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=f"Webhook body is not JSON: {exc}",
        )
    result = deliver(record, payload)
    if not result.ok:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=result.error or "Webhook delivery failed",
            error_detail={"status_code": result.status_code},
        )
    return NodeResult(
        status="succeeded",
        output={"status_code": result.status_code, "ok": True},
    )


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    webhook_id = config.get("webhook_id")
    problems: list[Problem] = []
    if not isinstance(webhook_id, str) or get_webhook_store().get(webhook_id) is None:
        problems.append(
            Problem(
                "CHANNEL_REFERENCE_UNRESOLVED",
                "Webhook was not found",
                path=("webhook_id",),
            )
        )
    body = config.get("body")
    if isinstance(body, str):
        try:
            parse(body)
        except TemplateSyntaxError as exc:
            problems.append(
                Problem("CHANNEL_NODE_CONFIG_INVALID", str(exc), path=("body",))
            )
    return problems


NODE_TYPE = NodeType(
    type_id="action.webhook",
    family="action",
    label="Webhook",
    summary="POSTs a JSON body to one saved Webhook.",
    description=(
        "Calls a site-wide Webhook when this node runs. The body is a template "
        "whose result must be JSON. A refused address or an HTTP status of 400 "
        "or higher fails this node."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "webhook_id": {
                "type": "string",
                "minLength": 1,
                "title": "Webhook",
                "description": "Saved Webhook this node calls.",
                "x-refraq-ref": "webhook",
            },
            "body": {
                "type": "string",
                "minLength": 1,
                "title": "Body",
                "description": "Template rendered to the JSON body.",
                "x-refraq-template": {"type": "string"},
            },
        },
        ["webhook_id", "body"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    check=_check,
)
