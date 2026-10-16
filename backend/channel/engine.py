"""Control-flow execution of a Data Channel graph.

Edges order nodes and select a branch. They do not carry items. A node runs
when every incoming edge in scope has settled and at least one is live. A node
whose incoming edges are all dead does not run. Among ready siblings, the
smaller canvas y, then x, is explored first, and that branch finishes before
the next sibling.

A loop-type node (its type declares a loop-back output) runs its body once per
iteration. Edges into a non-``main`` input of a loop node are return edges:
they do not gate the loop, and they collect one result per iteration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from backend.channel.graph import ancestor_closure, refine_ports
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, ReferenceResolver
from backend.channel.template import output_matches

__all__ = [
    "RunOutcome",
    "execute",
]


@dataclass
class RunOutcome:
    status: str
    outcome: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    failed_node_id: str | None = None
    stopped_node_id: str | None = None
    skipped_node_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Link:
    source: str
    source_port: str
    target: str
    target_port: str


class _Run:
    def __init__(
        self,
        graph: Mapping[str, Any],
        by_type: Mapping[str, NodeType],
        schemas: Mapping[str, Mapping[str, Any]],
        hooks: EngineHooks,
        loop_ports: Mapping[str, str],
        reachable: set[str],
        *,
        timeout_sec: int | None,
        clock: float,
    ) -> None:
        self.nodes = {str(node["id"]): node for node in graph["nodes"]}
        self.by_type = by_type
        self.schemas = schemas
        self.hooks = hooks
        self.loop_ports = dict(loop_ports)
        self.reachable = reachable
        self.timeout_sec = timeout_sec
        self.clock = clock
        self.links = _links(graph, self.nodes)
        self.outgoing: dict[str, list[int]] = {node_id: [] for node_id in self.nodes}
        self.incoming: dict[str, list[int]] = {node_id: [] for node_id in self.nodes}
        for index, link in enumerate(self.links):
            self.outgoing[link.source].append(index)
            self.incoming[link.target].append(index)
        self.state = ["pending"] * len(self.links)
        self.skipped: list[str] = []
        self.produced: dict[str, Any] = {}
        self.ran_stack: list[set[str]] = [set()]
        self.loop_out: dict[str, str] = {}
        self.bodies: dict[str, set[str]] = {}
        self._index_loops()

    def _index_loops(self) -> None:
        for node_id, node in self.nodes.items():
            port = self.loop_ports.get(str(node["type"]))
            if port is None:
                continue
            self.loop_out[node_id] = port
            self.bodies[node_id] = self._body(node_id, port)

    def _body(self, loop_id: str, port: str) -> set[str]:
        seen: set[str] = set()
        stack = [
            self.links[index].target
            for index in self.outgoing[loop_id]
            if self.links[index].source_port == port and self.links[index].target != loop_id
        ]
        while stack:
            node_id = stack.pop()
            if node_id in seen or node_id == loop_id:
                continue
            seen.add(node_id)
            for index in self.outgoing.get(node_id, []):
                target = self.links[index].target
                if target != loop_id and target not in seen:
                    stack.append(target)
        return seen

    def walk(self, scope: set[str], *, entry: str | None) -> RunOutcome | None:
        direct = (scope & self.reachable) - self._hidden(scope)
        done: set[str] = set()
        if entry is not None:
            stack = [entry] if entry in direct else []
        else:
            stack = self._seeds(direct, done)
        while stack:
            pending = stack[-1]
            stopped = self._stopped(pending)
            if stopped is not None:
                return stopped
            node_id = stack.pop()
            if node_id in done or node_id not in direct:
                continue
            if not self._ready(node_id):
                continue
            if not self._live_incoming(node_id):
                self._kill(node_id)
                done.add(node_id)
                self._push(node_id, direct, done, stack)
                continue
            outcome = self._run(node_id, direct, done, stack)
            if outcome is not None:
                return outcome
            done.add(node_id)
        return None

    def _hidden(self, scope: set[str]) -> set[str]:
        hidden: set[str] = set()
        for loop_id, body in self.bodies.items():
            if loop_id in scope:
                hidden |= body
        return hidden

    def _seeds(self, direct: set[str], done: set[str]) -> list[str]:
        ready = [
            node_id
            for node_id in direct
            if node_id not in done and self._ready(node_id)
        ]
        ready.sort(key=self._position, reverse=True)
        return ready

    def _stopped(self, pending: str) -> RunOutcome | None:
        if self.hooks.cancelled() or self.hooks.superseded():
            return RunOutcome(
                status="cancelled",
                stopped_node_id=pending,
                skipped_node_ids=list(self.skipped),
            )
        if self.timeout_sec is not None and time.monotonic() - self.clock > self.timeout_sec:
            return RunOutcome(
                status="failed",
                error_code="CHANNEL_RUN_TIMEOUT",
                error_message="Run timeout elapsed",
                stopped_node_id=pending,
                skipped_node_ids=list(self.skipped),
            )
        return None

    def _back(self, index: int) -> bool:
        link = self.links[index]
        return link.target in self.loop_out and link.target_port != "main"

    def _counting(self, node_id: str) -> list[int]:
        return [index for index in self.incoming[node_id] if not self._back(index)]

    def _ready(self, node_id: str) -> bool:
        return all(self.state[index] != "pending" for index in self._counting(node_id))

    def _live_incoming(self, node_id: str) -> bool:
        incoming = self._counting(node_id)
        if not incoming:
            return True
        return any(self.state[index] == "live" for index in incoming)

    def _kill(self, node_id: str) -> None:
        for index in self.outgoing[node_id]:
            self.state[index] = "dead"

    def _settle(self, node_id: str, result: NodeResult, skip: set[str]) -> None:
        ports = {self.links[index].source_port for index in self.outgoing[node_id]}
        if result.ports is None:
            live = {port for port in ports if port != "error"}
        else:
            live = set(result.ports)
        for index in self.outgoing[node_id]:
            link = self.links[index]
            if link.source_port in skip:
                continue
            self.state[index] = "live" if link.source_port in live else "dead"

    def _push(self, node_id: str, direct: set[str], done: set[str], stack: list[str]) -> None:
        kids: list[str] = []
        seen: set[str] = set()
        for index in self.outgoing[node_id]:
            target = self.links[index].target
            if (
                target in direct
                and target not in done
                and target not in seen
                and self._ready(target)
            ):
                seen.add(target)
                kids.append(target)
        kids.sort(key=self._position, reverse=True)
        stack.extend(kids)

    def _run(
        self,
        node_id: str,
        direct: set[str],
        done: set[str],
        stack: list[str],
    ) -> RunOutcome | None:
        if node_id in self.loop_out:
            return self._run_loop(node_id, direct, done, stack)
        seq, result = self._start(node_id)
        node = self.nodes[node_id]
        self.hooks.on_finish(seq, node, result)
        failed = self._failure(node_id, result)
        if failed is not None:
            return failed
        self._note(node_id, result)
        self._settle(node_id, result, set())
        self._push(node_id, direct, done, stack)
        return None

    def _run_loop(
        self,
        node_id: str,
        direct: set[str],
        done: set[str],
        stack: list[str],
    ) -> RunOutcome | None:
        seq, result = self._start(node_id)
        node = self.nodes[node_id]
        loop_port = self.loop_out[node_id]
        if result.status == "failed":
            self.hooks.on_finish(seq, node, result)
            return self._failure(node_id, result)
        if result.status != "succeeded":
            self.hooks.on_finish(seq, node, result)
            self._note(node_id, result)
            self._settle(node_id, result, {loop_port})
            self._push(node_id, direct, done, stack)
            return None
        outcome = self._iterate(node_id, seq, result)
        if outcome is not None:
            return outcome
        self._settle(node_id, result, {loop_port})
        self._push(node_id, direct, done, stack)
        return None

    def _iterate(self, node_id: str, seq: int, result: NodeResult) -> RunOutcome | None:
        node = self.nodes[node_id]
        body = self.bodies[node_id]
        steps = result.iterations if isinstance(result.iterations, list) else []
        back = self._return_edge(node_id)
        collected: list[Any] = []
        for step in steps:
            self._drop(body)
            for body_id in body:
                self.produced.pop(body_id, None)
            self.hooks.on_output(node, step)
            self.produced[node_id] = step
            self._arm(node_id, body)
            self.ran_stack.append(set())
            outcome = self.walk(body, entry=None)
            ran = self.ran_stack.pop()
            if outcome is not None:
                self.hooks.on_finish(
                    seq,
                    node,
                    NodeResult(
                        status="failed",
                        error_code=outcome.error_code,
                        error_message=outcome.error_message or "cancelled",
                    ),
                )
                return outcome
            if back is not None:
                source = back.source
                collected.append(self.produced.get(source) if source in ran else None)
        base = result.output if isinstance(result.output, dict) else {}
        final = {**base, "results": collected}
        result.output = final
        self.hooks.on_finish(seq, node, result)
        self._note(node_id, result)
        return None

    def _arm(self, loop_id: str, body: set[str]) -> None:
        loop_port = self.loop_out[loop_id]
        for index, link in enumerate(self.links):
            from_loop = link.source == loop_id and link.source_port == loop_port
            if link.target not in body or not (link.source in body or from_loop):
                continue
            self.state[index] = "live" if from_loop else "pending"

    def _return_edge(self, loop_id: str) -> _Link | None:
        for index in self.incoming[loop_id]:
            if self._back(index):
                return self.links[index]
        return None

    def _drop(self, body: set[str]) -> None:
        refs = [str(self.nodes[node_id].get("ref") or node_id) for node_id in body]
        drop = getattr(self.hooks, "drop_outputs", None)
        if callable(drop) and refs:
            drop(refs)

    def _start(self, node_id: str) -> tuple[int, NodeResult]:
        node = self.nodes[node_id]
        seq = self.hooks.on_start(node)
        spec = self.by_type.get(str(node["type"]))
        if spec is None:
            result = NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message=f"No executor for {node['type']}",
            )
        else:
            pinned = self.hooks.pinned_output(node)
            if pinned is not None:
                result = spec.pinned(node, pinned.value)
            else:
                result = spec.execute(node, self.hooks)
                result = _apply_output_check(node_id, spec, result, self.schemas)
        if result.status == "skipped" and result.output is None:
            result.output = {"skipped": True, "reason": result.error_message}
        return seq, result

    def _failure(self, node_id: str, result: NodeResult) -> RunOutcome | None:
        if result.status != "failed":
            return None
        return RunOutcome(
            status="failed",
            error_code=result.error_code or "CHANNEL_NODE_FAILED",
            error_message=result.error_message,
            failed_node_id=node_id,
            skipped_node_ids=list(self.skipped),
        )

    def _note(self, node_id: str, result: NodeResult) -> None:
        if result.status == "skipped":
            self.skipped.append(node_id)
        self.hooks.on_output(self.nodes[node_id], result.output)
        self.produced[node_id] = result.output
        self.ran_stack[-1].add(node_id)

    def _position(self, node_id: str) -> tuple[float, float]:
        return _position(self.nodes[node_id])


def execute(
    graph: Mapping[str, Any],
    entry_node_id: str,
    catalog: Sequence[NodeType],
    resolver: ReferenceResolver,
    hooks: EngineHooks,
    *,
    timeout_sec: int | None = None,
    started: float | None = None,
    stop_at_node_id: str | None = None,
) -> RunOutcome:
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    if entry_node_id not in nodes:
        return RunOutcome(
            status="cancelled",
            error_code="CHANNEL_TRIGGER_INVALID",
            error_message="Trigger node is not in the graph",
        )
    children, _parents = _child_index(graph, nodes)
    reachable = _reachable(entry_node_id, children)
    if stop_at_node_id is not None:
        closure = ancestor_closure(graph, stop_at_node_id)
        reachable &= closure if closure is not None else set()
    clock = time.monotonic() if started is None else started
    types = list(catalog)
    runner = _Run(
        graph,
        {item.type_id: item for item in types},
        _output_schemas(refine_ports(graph, resolver, types)),
        hooks,
        _loop_ports(types),
        reachable,
        timeout_sec=timeout_sec,
        clock=clock,
    )
    outcome = runner.walk(reachable, entry=entry_node_id)
    if outcome is not None:
        return outcome
    return RunOutcome(
        status="succeeded",
        outcome="completed",
        skipped_node_ids=list(runner.skipped),
    )


def _loop_ports(catalog: Sequence[NodeType]) -> dict[str, str]:
    found: dict[str, str] = {}
    for spec in catalog:
        for port in spec.outputs:
            if port.loop_back:
                found[spec.type_id] = port.port
                break
    return found


def _output_schemas(ports: Sequence[Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for port in ports:
        if port.direction != "output":
            continue
        found.setdefault(port.node_id, {})[port.port] = port.schema
    return found


def _apply_output_check(
    node_id: str,
    spec: NodeType,
    result: NodeResult,
    schemas: Mapping[str, Mapping[str, Any]],
) -> NodeResult:
    if result.status != "succeeded":
        return result
    produced = schemas.get(node_id, {})
    for port in spec.outputs:
        if port.loop_back or port.port == "error":
            continue
        schema = produced.get(port.port)
        if isinstance(schema, dict) and not output_matches(result.output, schema):
            return NodeResult(
                status="failed",
                error_code="CHANNEL_OUTPUT_SCHEMA_MISMATCH",
                error_message="Output does not match the declared schema",
            )
    return result


def _links(graph: Mapping[str, Any], nodes: dict[str, Mapping[str, Any]]) -> list[_Link]:
    found: list[_Link] = []
    for edge in graph["edges"]:
        source = str(edge["source"]["node_id"])
        target = str(edge["target"]["node_id"])
        if source in nodes and target in nodes:
            found.append(
                _Link(
                    source,
                    str(edge["source"]["port"]),
                    target,
                    str(edge["target"]["port"]),
                )
            )
    return found


def _child_index(
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
    for kids in children.values():
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
