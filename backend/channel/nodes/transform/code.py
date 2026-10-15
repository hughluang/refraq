"""Code node type."""

from __future__ import annotations

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema

__all__ = ["NODE_TYPE"]

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
    permission="channel:code_write",
)
