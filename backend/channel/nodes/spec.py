"""Shared declaration for a Data Channel node type.

Node modules depend on this module only. The catalog in ``nodes`` is the
registry; it is not imported from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ERROR_OUTPUT",
    "MAIN_INPUT",
    "MAIN_OUTPUT",
    "NodeType",
    "PortSpec",
    "object_schema",
]


@dataclass(frozen=True, slots=True)
class PortSpec:
    port: str
    description: str
    loop_back: bool = False


@dataclass(frozen=True, slots=True)
class NodeType:
    type_id: str
    family: str
    label: str
    summary: str
    description: str
    entry: bool
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    config_schema: dict[str, Any]
    permission: str | None = None


MAIN_INPUT = PortSpec(
    "main",
    "Items or a dataset reference from the previous node.",
)
MAIN_OUTPUT = PortSpec(
    "main",
    "Items or a dataset reference from a successful execution.",
)
ERROR_OUTPUT = PortSpec(
    "error",
    "Items that failed this node when on_error is error_output.",
)


def object_schema(
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }
