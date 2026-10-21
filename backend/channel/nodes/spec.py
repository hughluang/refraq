"""Declaration and runtime value types for a Data Channel node type.

Node modules import this module for the type declaration and the values they
return from execute. The catalog in ``nodes`` is the registry and is not
imported from here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from backend.admin.user_store import UserRecord

__all__ = [
    "ERROR_OUTPUT",
    "EngineHooks",
    "MAIN_INPUT",
    "MAIN_OUTPUT",
    "NodeResult",
    "NodeType",
    "PortSpec",
    "Problem",
    "ReferenceResolver",
    "ResolvedAttribute",
    "ResolvedEntity",
    "object_schema",
]


@dataclass(frozen=True, slots=True)
class PortSpec:
    port: str
    description: str
    loop_back: bool = False
    coarse_type: str = "unknown"


@dataclass
class NodeResult:
    status: str
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None
    ports: frozenset[str] | None = None
    iterations: list[Any] | None = None


class EngineHooks(Protocol):
    def cancelled(self) -> bool: ...

    def superseded(self) -> bool: ...

    def on_start(self, node: Mapping[str, Any]) -> int: ...

    def on_finish(self, seq: int, node: Mapping[str, Any], result: NodeResult) -> None: ...

    def on_output(self, node: Mapping[str, Any], output: Any) -> None: ...

    def drop_outputs(self, refs: list[str]) -> None: ...

    def evaluate(self, expression: str) -> Any: ...

    def run_code(self, source: str, timeout_sec: float) -> Any: ...

    @property
    def run_id(self) -> str: ...

    @property
    def channel_id(self) -> str: ...

    @property
    def actor(self) -> Mapping[str, str]: ...

    @property
    def started_at(self) -> str: ...

    @property
    def user(self) -> UserRecord: ...

    @property
    def schedule(self) -> Mapping[str, Any]: ...


Execute = Callable[[Mapping[str, Any], EngineHooks], NodeResult]
Refine = Callable[
    [Mapping[str, Any], Mapping[str, Any], Any],
    dict[str, Any],
]


@dataclass(frozen=True, slots=True)
class ResolvedAttribute:
    name: str
    unique: bool
    business_key: bool
    value_type: str = "string"


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    attributes: tuple[ResolvedAttribute, ...]


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    detail: str
    node_id: str | None = None
    edge_id: str | None = None
    severity: str = "error"
    path: tuple[str | int, ...] = ()


class ReferenceResolver(Protocol):
    def entity_head(self, entity_id: str) -> ResolvedEntity | None: ...

    def channel_exists(self, channel_id: str) -> bool: ...

    def published_trigger_type(self, channel_id: str) -> str | None: ...

    def source_exists(self, source_id: str) -> bool: ...


Check = Callable[[Mapping[str, Any], ReferenceResolver], list[Problem]]


@dataclass(frozen=True, slots=True)
class NodeType:
    type_id: str
    family: str
    label: str
    summary: str
    description: str
    trigger: bool
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    config_schema: dict[str, Any]
    execute: Execute
    permission: str | None = None
    type_version: int = 1
    refine: Refine | None = None
    check: Check | None = None


MAIN_INPUT = PortSpec(
    "main",
    "Items or a dataset reference from the previous node.",
    coarse_type="object",
)
MAIN_OUTPUT = PortSpec(
    "main",
    "Items or a dataset reference from a successful execution.",
    coarse_type="object",
)
ERROR_OUTPUT = PortSpec(
    "error",
    "Items that failed this node when on_error is error_output.",
    coarse_type="unknown",
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
