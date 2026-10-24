"""Email action node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.email_accounts import (
    SmtpDeliveryError,
    deliver,
    get_email_account_store,
    prepare_message,
)
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

__all__ = ["NODE_TYPE"]

_TEXT = {"type": "string"}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") or {}
    account_id = config.get("email_account_id")
    record = (
        get_email_account_store().get(account_id) if isinstance(account_id, str) else None
    )
    if record is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Email Account was not found",
        )
    rendered: dict[str, str] = {}
    for key in ("to", "subject", "body"):
        value, failure = render_field(hooks, config.get(key), _TEXT, path=key)
        if failure is not None:
            return failure
        rendered[key] = value
    try:
        recipients = prepare_message(rendered["to"], rendered["subject"], rendered["body"])
    except SmtpDeliveryError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    result = deliver(record, recipients, rendered["subject"], rendered["body"])
    if not result.ok:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=result.error or "Email delivery failed",
        )
    return NodeResult(status="succeeded", output={"ok": True})


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    account_id = config.get("email_account_id")
    problems: list[Problem] = []
    if not isinstance(account_id, str) or get_email_account_store().get(account_id) is None:
        problems.append(
            Problem(
                "CHANNEL_REFERENCE_UNRESOLVED",
                "Email Account was not found",
                path=("email_account_id",),
            )
        )
    for key in ("to", "subject", "body"):
        value = config.get(key)
        if isinstance(value, str):
            try:
                parse(value)
            except TemplateSyntaxError as exc:
                problems.append(
                    Problem("CHANNEL_NODE_CONFIG_INVALID", str(exc), path=(key,))
                )
    return problems


NODE_TYPE = NodeType(
    type_id="action.email",
    family="action",
    label="Email",
    summary="Sends one plain-text message through a saved Email Account.",
    description=(
        "Sends one message when this node runs. To, subject, and body are templates. "
        "From comes from the Email Account. A bad address, a limit, or a refused "
        "recipient sends nothing and fails this node."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "email_account_id": {
                "type": "string",
                "minLength": 1,
                "title": "Email Account",
                "description": "Saved Email Account this node sends through.",
                "x-refraq-ref": "email_account",
            },
            "to": {
                "type": "string",
                "minLength": 1,
                "title": "To",
                "description": "Template rendered to one or more mailboxes.",
                "x-refraq-template": {"type": "string"},
            },
            "subject": {
                "type": "string",
                "title": "Subject",
                "description": "Template rendered to the subject.",
                "x-refraq-template": {"type": "string"},
            },
            "body": {
                "type": "string",
                "title": "Body",
                "description": "Template rendered to the plain-text body.",
                "x-refraq-template": {"type": "string"},
            },
        },
        ["email_account_id", "to", "subject", "body"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    check=_check,
)
