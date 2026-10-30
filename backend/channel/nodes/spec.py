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
    "CheckpointView",
    "ContainerBody",
    "ContainerSpec",
    "EngineHooks",
    "MAIN_INPUT",
    "MAIN_OUTPUT",
    "NodeResult",
    "NodeType",
    "OutputView",
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
    coarse_type: str = "unknown"


@dataclass
class NodeResult:
    status: str
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None
    ports: frozenset[str] | None = None
    minimum_wait_sec: float | None = None


class EngineHooks(Protocol):
    def cancelled(self) -> bool: ...

    def superseded(self) -> bool: ...

    def on_start(
        self,
        node: Mapping[str, Any],
        *,
        container_seq: int | None = None,
        round: int | None = None,
    ) -> int: ...

    def on_finish(
        self, seq: int, node: Mapping[str, Any], result: NodeResult
    ) -> None: ...

    def on_output(self, node: Mapping[str, Any], output: Any) -> None: ...

    def open_input(self, seq: int) -> Any: ...

    def close_input(self, token: Any) -> None: ...

    def on_round(self, seq: int, index: int, step: Any) -> None: ...

    def note_round_template(
        self, seq: int, index: int, path: str, entry: Any
    ) -> None: ...

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

    @property
    def run_variables(self) -> dict[str, Any]: ...

    @property
    def ignore_checkpoints(self) -> bool: ...

    @property
    def checkpoints(self) -> CheckpointView: ...


class CheckpointView(Protocol):
    """Positions one run reads and proposes. The node decides when a run may advance."""

    def durable(self, node_id: str, stream: str) -> Any: ...

    def proposed(self, node_id: str, stream: str) -> Any: ...

    def stored(self, node_id: str, stream: str) -> Any: ...

    def bound(self, node_id: str, stream: str) -> int: ...

    def propose(self, node_id: str, stream: str, position: Any) -> None: ...


class ContainerBody(Protocol):
    """One Container execution's rounds. The engine supplies the only implementation."""

    def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]: ...

    def evaluate_round_template(
        self, path: str, schema: Mapping[str, Any]
    ) -> tuple[Any, NodeResult | None]: ...


Execute = Callable[[Mapping[str, Any], EngineHooks], NodeResult]
ContainerRun = Callable[[Mapping[str, Any], EngineHooks, ContainerBody], NodeResult]
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
class ContainerSpec:
    run: ContainerRun
    round_templates: tuple[str, ...] = ()


_OUTPUT_VIEW_KINDS = frozenset(
    {"record", "rows", "dataset", "counts", "container", "value"}
)


@dataclass(frozen=True, slots=True)
class OutputView:
    kind: str
    metrics: tuple[str, ...] = ()
    rows: str | None = None
    dataset: str | None = None
    item: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _OUTPUT_VIEW_KINDS:
            raise ValueError(f"unknown output view kind: {self.kind}")
        if not isinstance(self.metrics, tuple) or any(
            not isinstance(name, str) or name == "" for name in self.metrics
        ):
            raise ValueError("output view metrics must be a tuple of names")
        if self.kind == "rows":
            if not isinstance(self.rows, str) or self.rows == "":
                raise ValueError("rows output view requires a rows key")
            if self.dataset is not None or self.item is not None:
                raise ValueError("rows output view rejects dataset and item keys")
            return
        if self.kind == "dataset":
            if not isinstance(self.dataset, str) or self.dataset == "":
                raise ValueError("dataset output view requires a dataset key")
            if self.rows is not None or self.item is not None:
                raise ValueError("dataset output view rejects rows and item keys")
            return
        if self.kind == "container":
            if not isinstance(self.item, str) or self.item == "":
                raise ValueError("container output view requires an item key")
            if self.rows is not None or self.dataset is not None:
                raise ValueError("container output view rejects rows and dataset keys")
            return
        if self.rows is not None or self.dataset is not None or self.item is not None:
            raise ValueError(
                "output view rows, dataset, and item belong to their own kinds"
            )


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
    output_view: OutputView
    execute: Execute | None = None
    container: ContainerSpec | None = None
    permission: str | None = None
    type_version: int = 1
    refine: Refine | None = None
    check: Check | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_view, OutputView):
            raise TypeError("output_view is required")
        if (self.execute is None) == (self.container is None):
            raise TypeError("a node type has execute or container")


MAIN_INPUT = PortSpec(
    "main",
    "Primary input port. It orders execution. The node reads an upstream output by name.",
    coarse_type="object",
)
MAIN_OUTPUT = PortSpec(
    "main",
    "Primary output port of a successful execution. A downstream node reads that output by name.",
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
