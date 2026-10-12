"""Control-flow execution of a Data Channel graph.

Edges order nodes. A node runs once, after every ancestor this run reached has
finished. Among siblings, the smaller canvas y, then x, is explored first, and
that branch finishes before the next sibling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

__all__ = ["EngineHooks", "NodeResult", "RunOutcome", "execute"]


@dataclass
class NodeResult:
    status: str
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None


@dataclass
class RunOutcome:
    status: str
    outcome: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    failed_node_id: str | None = None
    stopped_node_id: str | None = None
    skipped_node_ids: list[str] = field(default_factory=list)


class EngineHooks(Protocol):
    def cancelled(self) -> bool: ...

    def superseded(self) -> bool: ...

    def on_start(self, node: Mapping[str, Any]) -> int: ...

    def on_finish(self, seq: int, node: Mapping[str, Any], result: NodeResult) -> None: ...

    def on_output(self, node: Mapping[str, Any], output: Any) -> None: ...


Executor = Callable[[Mapping[str, Any], EngineHooks], NodeResult]


def execute(
    graph: Mapping[str, Any],
    entry_node_id: str,
    executors: Mapping[str, Executor],
    hooks: EngineHooks,
    *,
    timeout_sec: int | None = None,
    started: float | None = None,
) -> RunOutcome:
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    if entry_node_id not in nodes:
        return RunOutcome(
            status="cancelled",
            error_code="CHANNEL_TRIGGER_INVALID",
            error_message="Trigger node is not in the graph",
        )
    children, parents = _links(graph, nodes)
    reachable = _reachable(entry_node_id, children)
    done: set[str] = set()
    skipped: list[str] = []
    clock = time.monotonic() if started is None else started
    stack = [entry_node_id]
    while stack:
        pending = stack[-1]
        if hooks.cancelled() or hooks.superseded():
            return RunOutcome(
                status="cancelled",
                stopped_node_id=pending,
                skipped_node_ids=skipped,
            )
        if timeout_sec is not None and time.monotonic() - clock > timeout_sec:
            return RunOutcome(
                status="failed",
                error_code="CHANNEL_RUN_TIMEOUT",
                error_message="Run timeout elapsed",
                stopped_node_id=pending,
                skipped_node_ids=skipped,
            )
        node_id = stack.pop()
        if node_id in done or node_id not in reachable:
            continue
        if any(parent not in done for parent in parents.get(node_id, [])):
            continue
        node = nodes[node_id]
        seq = hooks.on_start(node)
        executor = executors.get(str(node["type"]))
        if executor is None:
            result = NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message=f"No executor for {node['type']}",
            )
        else:
            result = executor(node, hooks)
        hooks.on_finish(seq, node, result)
        done.add(node_id)
        if result.status == "failed":
            return RunOutcome(
                status="failed",
                error_code=result.error_code or "CHANNEL_NODE_FAILED",
                error_message=result.error_message,
                failed_node_id=node_id,
                skipped_node_ids=skipped,
            )
        if result.status == "skipped":
            skipped.append(node_id)
            output = result.output if result.output is not None else {
                "skipped": True,
                "reason": result.error_message,
            }
        else:
            output = result.output
        hooks.on_output(node, output)
        ready = [
            child
            for child in children.get(node_id, [])
            if child in reachable and all(parent in done for parent in parents.get(child, []))
        ]
        ready.sort(key=lambda item: _position(nodes[item]), reverse=True)
        stack.extend(ready)
    return RunOutcome(status="succeeded", outcome="completed", skipped_node_ids=skipped)


def _links(
    graph: Mapping[str, Any],
    nodes: dict[str, Mapping[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    parents: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in graph["edges"]:
        source = str(edge["source"]["node_id"])
        target = str(edge["target"]["node_id"])
        if source in nodes and target in nodes:
            children[source].append(target)
            parents[target].append(source)
    for node_id, kids in children.items():
        kids.sort(key=lambda item: _position(nodes[item]))
    return children, parents


def _reachable(entry: str, children: dict[str, list[str]]) -> set[str]:
    seen = {entry}
    stack = [entry]
    while stack:
        node_id = stack.pop()
        for child in children.get(node_id, []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _position(node: Mapping[str, Any]) -> tuple[float, float]:
    position = node.get("position") or {}
    return (float(position.get("y") or 0), float(position.get("x") or 0))
