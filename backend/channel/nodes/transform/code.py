"""Code node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, EngineHooks, NodeResult, NodeType, object_schema
from backend.channel.sandbox import CodeError

__all__ = ["NODE_TYPE"]


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    source = config.get("code")
    if not isinstance(source, str):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Code is missing",
            error_detail={"reason": "error"},
        )
    timeout = config.get("timeout_sec", 30)
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        timeout = 30
    try:
        value = hooks.run_code(source, float(timeout))
    except CodeError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail=exc.detail,
        )
    return NodeResult(status="succeeded", output=value)


NODE_TYPE = NodeType(
    type_id="transform.code",
    family="transform",
    label="Code",
    summary="Runs author Python in the run sandbox and returns its JSON value.",
    description=(
        "The configuration code is the body of def main(self). "
        "The value returned from main is this node's output and must be JSON. "
        "The call runs in the channel run's sandbox: no network, an allow-listed "
        "set of modules, and a wall-clock limit."
    ),
    entry=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "code": {
                "type": "string",
                "minLength": 1,
                "maxLength": 65536,
                "title": "Code",
                "description": (
                    "Python source, the body of def main(self). "
                    "One byte to 64 KiB. The returned value is the node output "
                    "and must be JSON."
                ),
                "contentMediaType": "text/x-python",
            },
            "timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 300,
                "default": 30,
                "title": "Timeout",
                "description": (
                    "Wall-clock seconds before this call is cancelled. "
                    "Default 30. Maximum 300."
                ),
            },
        },
        ["code"],
    ),
    execute=_execute,
    permission="channel:code_write",
)
