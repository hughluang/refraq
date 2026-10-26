"""Control-flow execution of a Data Channel graph.

Edges order nodes and select a branch. They do not carry items. A node runs
when every incoming edge in scope has settled and at least one is live. A node
whose incoming edges are all dead does not run. Among ready siblings, the
smaller canvas y, then x, is explored first, and that branch finishes before
the next sibling.

A container runs once for each element. Its body is the nodes whose parent is
that container. ``CONTAINER_TYPES`` names the containers. Each accumulated
round records the outputs of the body nodes that ran. A container that does
not accumulate leaves those rounds off its output. Until is the exception:
it repeats its direct children until a boolean template is true, and the
rounds are not known before the body runs. An incoming edge that does not
target main does not gate the container.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from backend.channel.graph import CONTAINER_TYPES, ancestor_closure, refine_ports
from backend.channel.item_limit import ITEM_LIMIT
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, ReferenceResolver
from backend.channel.template import output_matches
from backend.channel.variables import value_size

__all__ = [
    "ITERATION_VOLUME_MAX_BYTES",
    "RunOutcome",
    "execute",
]

ITERATION_VOLUME_MAX_BYTES = 16 * 1024 * 1024
_EACH_PORT = "each"
_UNTIL_TYPE = "volume.until"
_BOOL = {"type": "boolean"}
_UNTIL_CAP_MESSAGE = "Until reached max_iterations before its condition became true."
_UNTIL_VOLUME_MESSAGE = "Until iteration output exceeds 16 MiB."


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
        reachable: set[str],
        *,
        timeout_sec: int | None,
        clock: float,
    ) -> None:
        self.nodes = {str(node["id"]): node for node in graph["nodes"]}
        self.by_type = by_type
        self.schemas = schemas
        self.hooks = hooks
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
        self.loops: set[str] = set()
        self.accumulating: set[str] = set()
        self.bodies: dict[str, set[str]] = {}
        self._frames: list[tuple[int, int]] = []
        self._index_loops()

    def _index_loops(self) -> None:
        children: dict[str, set[str]] = {}
        for node_id, node in self.nodes.items():
            parent = node.get("parent")
            if isinstance(parent, str) and parent in self.nodes and parent != node_id:
                children.setdefault(parent, set()).add(node_id)
        for node_id, node in self.nodes.items():
            kind = CONTAINER_TYPES.get(str(node.get("type")))
            if kind is None:
                continue
            self.loops.add(node_id)
            self.bodies[node_id] = set(children.get(node_id, ()))
            if kind.accumulate:
                self.accumulating.add(node_id)

    def walk(self, scope: set[str], *, start: str | None) -> RunOutcome | None:
        direct = (scope & self.reachable) - self._hidden(scope)
        done: set[str] = set()
        if start is not None:
            stack = [start] if start in direct else []
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
        return link.target in self.loops and link.target_port != "main"

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
        if node_id in self.loops:
            return self._run_loop(node_id, direct, done, stack)
        outcome, result = self._finish_tries(node_id)
        if outcome is not None:
            return outcome
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
        stopped, seq, result = self._tries(node_id)
        if stopped is not None:
            return stopped
        node = self.nodes[node_id]
        if result.status == "failed":
            outcome = self._policy(node_id, result)
            self.hooks.on_finish(seq, node, result)
            if outcome is not None:
                return outcome
            self._note(node_id, result)
            self._settle(node_id, result, {_EACH_PORT})
            self._push(node_id, direct, done, stack)
            return None
        if result.status != "succeeded":
            self.hooks.on_finish(seq, node, result)
            self._note(node_id, result)
            self._settle(node_id, result, {_EACH_PORT})
            self._push(node_id, direct, done, stack)
            return None
        if str(node.get("type")) == _UNTIL_TYPE:
            outcome = self._until(node_id, seq, result)
        else:
            outcome = self._iterate(node_id, seq, result)
        if outcome is not None:
            return outcome
        self._settle(node_id, result, {_EACH_PORT})
        self._push(node_id, direct, done, stack)
        return None

    def _until(self, node_id: str, seq: int, result: NodeResult) -> RunOutcome | None:
        """Repeat direct children until the boolean template is true.

        Rounds are not known before the body runs. ``previous`` is frozen from
        the round that just finished, before the next round drops those outputs.
        """
        node = self.nodes[node_id]
        body = self.bodies[node_id]
        cap = _until_cap(node)
        if cap is None:
            failed = NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_CONFIG_INVALID",
                error_message="max_iterations must be an integer from 1 through 100000",
            )
            self.hooks.on_finish(seq, node, failed)
            return self._failure(node_id, failed)
        previous: Any = None
        collected: list[Any] = []
        config = node["config"]
        for index in range(cap):
            step = {"previous": previous, "index": index}
            self._drop(body)
            for body_id in body:
                self.produced.pop(body_id, None)
            self.hooks.on_output(node, step)
            self.produced[node_id] = step
            _record_round(self.hooks, seq, index, {"index": index})
            self._arm(node_id, body)
            self.ran_stack.append(set())
            self._frames.append((seq, index))
            try:
                outcome = self.walk(body, start=None)
            finally:
                self._frames.pop()
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
            collected.append(self._round(ran))
            if value_size(collected) > ITERATION_VOLUME_MAX_BYTES:
                failed = NodeResult(
                    status="failed",
                    error_code="CHANNEL_ITERATION_VOLUME_EXCEEDED",
                    error_message=_UNTIL_VOLUME_MESSAGE,
                )
                self.hooks.on_finish(seq, node, failed)
                return RunOutcome(
                    status="failed",
                    error_code="CHANNEL_ITERATION_VOLUME_EXCEEDED",
                    error_message=_UNTIL_VOLUME_MESSAGE,
                    failed_node_id=node_id,
                    skipped_node_ids=list(self.skipped),
                )
            value, error = render_field(self.hooks, config.get("until"), _BOOL, path="until")
            if error is not None:
                _note_round_condition(self.hooks, seq, index, _until_error_entry(error))
                self.hooks.on_finish(seq, node, error)
                return self._failure(node_id, error)
            _note_round_condition(self.hooks, seq, index, {"value": value})
            if value:
                result.output = {"index": index, "count": index + 1, "iterations": collected}
                self.hooks.on_finish(seq, node, result)
                self._note(node_id, result)
                return None
            previous = collected[-1]
        failed = NodeResult(
            status="failed",
            error_code="CHANNEL_UNTIL_MAX_ITERATIONS",
            error_message=_UNTIL_CAP_MESSAGE,
            output={"index": cap - 1, "count": cap, "iterations": collected},
        )
        self.hooks.on_finish(seq, node, failed)
        return RunOutcome(
            status="failed",
            error_code="CHANNEL_UNTIL_MAX_ITERATIONS",
            error_message=_UNTIL_CAP_MESSAGE,
            failed_node_id=node_id,
            skipped_node_ids=list(self.skipped),
        )

    def _iterate(self, node_id: str, seq: int, result: NodeResult) -> RunOutcome | None:
        node = self.nodes[node_id]
        body = self.bodies[node_id]
        steps = _iteration_steps(result.iterations)
        collected: list[Any] = []
        accumulate = node_id in self.accumulating
        for index, step in enumerate(steps):
            self._drop(body)
            for body_id in body:
                self.produced.pop(body_id, None)
            self.hooks.on_output(node, step)
            self.produced[node_id] = step
            _record_round(self.hooks, seq, index, step)
            self._arm(node_id, body)
            self.ran_stack.append(set())
            self._frames.append((seq, index))
            try:
                outcome = self.walk(body, start=None)
            finally:
                self._frames.pop()
            ran = self.ran_stack.pop()
            if outcome is not None:
                detail = None
                if outcome.status == "failed" and not accumulate:
                    detail = {"index": index}
                self.hooks.on_finish(
                    seq,
                    node,
                    NodeResult(
                        status="failed",
                        error_code=outcome.error_code,
                        error_message=outcome.error_message or "cancelled",
                        error_detail=detail,
                    ),
                )
                return outcome
            if not accumulate:
                continue
            collected.append(self._round(ran))
            if value_size(collected) > ITERATION_VOLUME_MAX_BYTES:
                message = "For iteration output exceeds 16 MiB. Read the items in batches."
                failed = NodeResult(
                    status="failed",
                    error_code="CHANNEL_ITERATION_VOLUME_EXCEEDED",
                    error_message=message,
                )
                self.hooks.on_finish(seq, node, failed)
                return RunOutcome(
                    status="failed",
                    error_code="CHANNEL_ITERATION_VOLUME_EXCEEDED",
                    error_message=message,
                    failed_node_id=node_id,
                    skipped_node_ids=list(self.skipped),
                )
        if accumulate:
            base = result.output if isinstance(result.output, dict) else {}
            result.output = {**base, "iterations": collected}
        self.hooks.on_finish(seq, node, result)
        self._note(node_id, result)
        return None

    def _round(self, ran: set[str]) -> dict[str, Any]:
        record: dict[str, Any] = {}
        ordered = sorted(ran, key=lambda item: str(self.nodes[item].get("ref") or item))
        for body_id in ordered:
            ref = str(self.nodes[body_id].get("ref") or body_id)
            record[ref] = self.produced.get(body_id)
        return record

    def _arm(self, loop_id: str, body: set[str]) -> None:
        for index, link in enumerate(self.links):
            from_loop = link.source == loop_id and link.source_port == _EACH_PORT
            if link.target not in body or not (link.source in body or from_loop):
                continue
            self.state[index] = "live" if from_loop else "pending"

    def _drop(self, body: set[str]) -> None:
        refs = sorted(str(self.nodes[node_id].get("ref") or node_id) for node_id in body)
        drop = getattr(self.hooks, "drop_outputs", None)
        if callable(drop) and refs:
            drop(refs)

    def _finish_tries(self, node_id: str) -> tuple[RunOutcome | None, NodeResult]:
        stopped, seq, result = self._tries(node_id)
        if stopped is not None:
            return stopped, result
        outcome = self._policy(node_id, result)
        self.hooks.on_finish(seq, self.nodes[node_id], result)
        if outcome is not None:
            return outcome, result
        return None, result

    def _tries(self, node_id: str) -> tuple[RunOutcome | None, int, NodeResult]:
        node = self.nodes[node_id]
        tries, wait = _retry_budget(node)
        stopped = self._stopped(node_id)
        if stopped is not None:
            return (
                stopped,
                0,
                NodeResult(
                    status="failed",
                    error_code="CHANNEL_NODE_FAILED",
                    error_message="Node did not execute",
                ),
            )
        seq, result = self._start(node_id)
        attempt = 1
        while result.status == "failed" and attempt < tries:
            self.hooks.on_finish(seq, node, result)
            stopped = self._pause(node_id, wait)
            if stopped is not None:
                return stopped, seq, result
            stopped = self._stopped(node_id)
            if stopped is not None:
                return stopped, seq, result
            seq, result = self._start(node_id)
            attempt += 1
        return None, seq, result

    def _pause(self, node_id: str, wait_sec: int) -> RunOutcome | None:
        stopped = self._stopped(node_id)
        if stopped is not None or wait_sec <= 0:
            return stopped
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(0.05, remaining))
            stopped = self._stopped(node_id)
            if stopped is not None:
                return stopped
        return None

    def _policy(self, node_id: str, result: NodeResult) -> RunOutcome | None:
        if result.status != "failed":
            return None
        policy = self.nodes[node_id].get("on_error") or "stop"
        if policy == "continue":
            result.output = None
            return None
        if policy == "error_output" and _declares_error(self.by_type.get(str(self.nodes[node_id]["type"]))):
            result.output = {
                "code": result.error_code or "CHANNEL_NODE_FAILED",
                "message": result.error_message,
                "detail": result.error_detail,
            }
            result.ports = frozenset({"error"})
            return None
        return self._failure(node_id, result)

    def _start(self, node_id: str) -> tuple[int, NodeResult]:
        node = self.nodes[node_id]
        container_seq = None
        round_index = None
        if self._frames:
            container_seq, round_index = self._frames[-1]
        seq = self.hooks.on_start(node, container_seq=container_seq, round=round_index)
        spec = self.by_type.get(str(node["type"]))
        token = _open_input(self.hooks, seq)
        try:
            if spec is None:
                result = NodeResult(
                    status="failed",
                    error_code="CHANNEL_NODE_FAILED",
                    error_message=f"No executor for {node['type']}",
                )
            else:
                result = spec.execute(node, self.hooks)
                result = _apply_output_check(node_id, spec, result, self.schemas)
            if result.status == "skipped" and result.output is None:
                result.output = {"skipped": True, "reason": result.error_message}
            return seq, result
        finally:
            _close_input(self.hooks, token)

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


def _open_input(hooks: EngineHooks, seq: int) -> Any:
    opener = getattr(hooks, "open_input", None)
    if not callable(opener):
        return None
    return opener(seq)


def _close_input(hooks: EngineHooks, token: Any) -> None:
    closer = getattr(hooks, "close_input", None)
    if callable(closer):
        closer(token)


def _record_round(hooks: EngineHooks, seq: int, index: int, step: Any) -> None:
    recorder = getattr(hooks, "on_round", None)
    if callable(recorder):
        recorder(seq, index, step)


def _note_round_condition(hooks: EngineHooks, seq: int, index: int, entry: Any) -> None:
    """Record the condition on the round that just finished evaluating it."""
    note = getattr(hooks, "note_round_condition", None)
    if callable(note):
        note(seq, index, entry)


def _until_error_entry(error: NodeResult) -> dict[str, Any]:
    return {"error": {"code": error.error_code, "message": error.error_message}}


def _until_cap(node: Mapping[str, Any]) -> int | None:
    config = node.get("config")
    if not isinstance(config, dict):
        return None
    value = config.get("max_iterations")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > ITEM_LIMIT:
        return None
    return value


def _iteration_steps(iterations: Any) -> Any:
    """Rounds to walk. A list stays a list. Any other iterable stays lazy."""
    if isinstance(iterations, list):
        return iterations
    if iterations is None or isinstance(iterations, (str, bytes, bytearray)):
        return []
    try:
        return iter(iterations)
    except TypeError:
        return []


def execute(
    graph: Mapping[str, Any],
    trigger_node_id: str,
    catalog: Sequence[NodeType],
    resolver: ReferenceResolver,
    hooks: EngineHooks,
    *,
    timeout_sec: int | None = None,
    started: float | None = None,
    stop_at_node_id: str | None = None,
) -> RunOutcome:
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    if trigger_node_id not in nodes:
        return RunOutcome(
            status="cancelled",
            error_code="CHANNEL_TRIGGER_INVALID",
            error_message="Trigger node is not in the graph",
        )
    children, _parents = _child_index(graph, nodes)
    reachable = _reachable(trigger_node_id, children)
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
        reachable,
        timeout_sec=timeout_sec,
        clock=clock,
    )
    outcome = runner.walk(reachable, start=trigger_node_id)
    if outcome is not None:
        return outcome
    return RunOutcome(
        status="succeeded",
        outcome="completed",
        skipped_node_ids=list(runner.skipped),
    )


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
        if port.port == "error":
            continue
        if result.ports is not None and port.port not in result.ports:
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


def _reachable(start: str, children: dict[str, list[str]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        node_id = stack.pop()
        for child in children.get(node_id, []):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _retry_budget(node: Mapping[str, Any]) -> tuple[int, int]:
    retry = node.get("retry")
    if not isinstance(retry, dict):
        return 1, 0
    tries = retry.get("max_tries")
    wait = retry.get("wait_sec")
    if not isinstance(tries, int) or isinstance(tries, bool) or tries < 1:
        tries = 1
    if not isinstance(wait, int) or isinstance(wait, bool) or wait < 0:
        wait = 0
    return tries, wait


def _declares_error(spec: NodeType | None) -> bool:
    if spec is None:
        return False
    return any(port.port == "error" for port in spec.outputs)


def _position(node: Mapping[str, Any]) -> tuple[float, float]:
    position = node.get("position") or {}
    return (float(position.get("y") or 0), float(position.get("x") or 0))
