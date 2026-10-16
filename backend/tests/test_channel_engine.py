"""Pure control-flow engine."""

from __future__ import annotations

from collections.abc import Callable

from backend.channel.engine import execute
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, PortSpec
from backend.tests.channel_hooks_fake import FakeHooks


class _Resolver:
    def entity_head(self, entity_id: str) -> None:
        return None

    def channel_exists(self, channel_id: str) -> bool:
        return False

    def source_exists(self, source_id: str) -> bool:
        return False


_RESOLVER = _Resolver()


def _type(
    type_id: str,
    run: Callable[..., NodeResult],
    *,
    loop_port: str | None = None,
    refine: Callable[..., dict] | None = None,
) -> NodeType:
    if loop_port is None:
        outputs = (PortSpec("main", "Output."),)
    else:
        outputs = (
            PortSpec(loop_port, "Loop.", loop_back=True),
            PortSpec("done", "Done."),
        )
    return NodeType(
        type_id=type_id,
        family="test",
        label=type_id,
        summary="Test node.",
        description="Test node. Used only by the engine suite.",
        entry=False,
        inputs=(PortSpec("main", "Input."), PortSpec("loop", "Loop return.")),
        outputs=outputs,
        config_schema={"type": "object"},
        execute=run,
        refine=refine,
    )


def _catalog(
    bound: dict[str, Callable[..., NodeResult]],
    *,
    loops: dict[str, str] | None = None,
) -> list[NodeType]:
    loops = loops or {}
    return [_type(type_id, run, loop_port=loops.get(type_id)) for type_id, run in bound.items()]


def _node(node_id: str, y: float, x: float = 0, type_id: str = "fake") -> dict:
    return {
        "id": node_id,
        "type": type_id,
        "name": node_id,
        "ref": node_id,
        "position": {"x": x, "y": y},
        "config": {},
        "on_error": "stop",
        "retry": None,
    }


def _edge(
    source: str,
    target: str,
    source_port: str = "main",
    target_port: str = "main",
) -> dict:
    return {
        "id": f"{source}-{source_port}-{target}-{target_port}",
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": target_port},
    }


def _ok(node: dict, hooks: EngineHooks) -> NodeResult:
    del hooks
    return NodeResult(status="succeeded", output={"id": node["id"]})


def test_stop_at_runs_both_incoming_branches_and_not_downstream() -> None:
    graph = {
        "nodes": [_node("a", 0), _node("b", 1), _node("c", 2), _node("d", 3), _node("e", 4)],
        "edges": [
            _edge("a", "b"),
            _edge("a", "c"),
            _edge("b", "d"),
            _edge("c", "d"),
            _edge("d", "e"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": _ok}), _RESOLVER, hooks, stop_at_node_id="d")
    assert outcome.status == "succeeded"
    assert outcome.outcome == "completed"
    assert outcome.stopped_node_id is None
    assert hooks.order == ["a", "b", "c", "d"]
    assert "e" not in hooks.order


def test_branch_finishes_before_the_next_sibling() -> None:
    graph = {
        "nodes": [_node("a", 0), _node("b", 1), _node("c", 2), _node("d", 0)],
        "edges": [_edge("a", "b"), _edge("a", "c"), _edge("b", "d")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["a", "b", "d", "c"]


def test_stop_failure_does_not_run_downstream() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "b":
            return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="nope")
        return _ok(node, hooks)

    graph = {
        "nodes": [_node("a", 0), _node("b", 1), _node("c", 2)],
        "edges": [_edge("a", "b"), _edge("b", "c")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": fail}), _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "b"
    assert hooks.order == ["a", "b"]


def test_skipped_node_records_the_output_later_nodes_read() -> None:
    class FinishingHooks(FakeHooks):
        def __init__(self) -> None:
            super().__init__()
            self.recorded: dict[str, object] = {}

        def on_finish(self, seq: int, node: dict, result: NodeResult) -> None:
            del seq
            self.recorded[str(node["id"])] = result.output

    def skip(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "a":
            return NodeResult(status="skipped", error_message="nothing new")
        return _ok(node, hooks)

    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = FinishingHooks()
    outcome = execute(graph, "a", _catalog({"fake": skip}), _RESOLVER, hooks)
    assert outcome.skipped_node_ids == ["a"]
    assert hooks.recorded["a"] == {"skipped": True, "reason": "nothing new"}
    assert hooks.outputs["a"] == hooks.recorded["a"]


def test_timeout_records_the_node_about_to_run() -> None:
    import time

    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "a",
        _catalog({"fake": _ok}), _RESOLVER,
        hooks,
        timeout_sec=1,
        started=time.monotonic() - 5,
    )
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_RUN_TIMEOUT"
    assert outcome.stopped_node_id == "a"
    assert hooks.order == []


def test_supersede_stops_before_the_next_node() -> None:
    class Superseding(FakeHooks):
        def superseded(self) -> bool:
            return "a" in self.order

    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = Superseding()
    outcome = execute(graph, "a", _catalog({"fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert outcome.stopped_node_id == "b"
    assert hooks.order == ["a"]


def test_timeout_records_the_node_that_would_run() -> None:
    import time

    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "a",
        _catalog({"fake": _ok}), _RESOLVER,
        hooks,
        timeout_sec=1,
        started=time.monotonic() - 5,
    )
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_RUN_TIMEOUT"
    assert outcome.stopped_node_id == "a"
    assert hooks.order == []


def test_supersede_stops_before_the_next_node() -> None:
    class Superseding(FakeHooks):
        def superseded(self) -> bool:
            return "a" in self.order

    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = Superseding()
    outcome = execute(graph, "a", _catalog({"fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert outcome.stopped_node_id == "b"
    assert hooks.order == ["a"]


def test_cancel_between_nodes() -> None:
    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = FakeHooks()
    hooks.cancel_after = "a"
    outcome = execute(graph, "a", _catalog({"fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert outcome.stopped_node_id == "b"
    assert hooks.order == ["a"]


def _branch(node: dict, hooks: EngineHooks) -> NodeResult:
    del hooks
    if node["id"] == "gate":
        live = node["config"].get("live", "true")
        return NodeResult(status="succeeded", output={"value": live == "true"}, ports=frozenset({live}))
    return NodeResult(status="succeeded", output={"id": node["id"]})


def _walk(node: dict, hooks: EngineHooks) -> NodeResult:
    if node["type"] != "volume.for":
        current = hooks.outputs.get("outer") or hooks.outputs.get("walk") or {}
        return NodeResult(status="succeeded", output={"saw": current.get("current"), "id": node["id"]})
    items = list(node["config"].get("items") or [])
    count = len(items)
    iterations = [{"current": item, "index": index, "count": count} for index, item in enumerate(items)]
    if count == 0:
        output = {"current": None, "index": None, "count": 0, "results": []}
    else:
        output = {"current": items[-1], "index": count - 1, "count": count, "results": []}
    return NodeResult(status="succeeded", output=output, iterations=iterations, ports=frozenset({"done"}))


def test_if_dead_branch_does_not_run_and_the_join_does() -> None:
    graph = {
        "nodes": [
            _node("gate", 0, type_id="transform.if"),
            _node("live", 2),
            _node("dead", 1),
            _node("child", 3),
            _node("join", 4),
        ],
        "edges": [
            _edge("gate", "live", "true"),
            _edge("gate", "dead", "false"),
            _edge("dead", "child"),
            _edge("live", "join"),
            _edge("dead", "join"),
        ],
        "settings": {},
    }
    gate = graph["nodes"][0]
    gate["config"] = {"live": "true"}
    hooks = FakeHooks()
    outcome = execute(graph, "gate", _catalog({"transform.if": _branch, "fake": _branch}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["gate", "live", "join"]
    assert "dead" not in hooks.order
    assert "child" not in hooks.order


def test_join_waits_for_both_inputs() -> None:
    graph = {
        "nodes": [_node("s", 0), _node("a", 1), _node("a2", 2), _node("b", 3), _node("m", 4)],
        "edges": [_edge("s", "a"), _edge("s", "b"), _edge("a", "a2"), _edge("a2", "m"), _edge("b", "m")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "s", _catalog({"fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order.index("m") > hooks.order.index("a2")
    assert hooks.order.index("m") > hooks.order.index("b")
    assert hooks.order == ["s", "a", "a2", "b", "m"]


def test_for_runs_the_body_once_per_element_and_collects_results() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "walk", "main", "loop"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _walk}, loops={"volume.for": "each"}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk", "step", "step", "after"]
    assert hooks.outputs["walk"]["results"] == [{"saw": "a", "id": "step"}, {"saw": "b", "id": "step"}]
    assert hooks.outputs["walk"]["current"] == "b"
    assert hooks.outputs["walk"]["index"] == 1
    assert hooks.dropped == [["step"], ["step"]]


def test_for_empty_list_skips_the_body() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": []}
    graph = {
        "nodes": [walk, _node("step", 1)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "walk", "main", "loop"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _walk}, loops={"volume.for": "each"}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk"]
    assert hooks.outputs["walk"]["results"] == []
    assert hooks.outputs["walk"]["current"] is None
    assert hooks.outputs["walk"]["index"] is None
    assert hooks.dropped == []


def test_nested_for_collects_inner_results() -> None:
    outer = _node("outer", 0, type_id="volume.for")
    outer["config"] = {"items": [1, 2]}
    inner = _node("inner", 1, type_id="volume.for")
    inner["config"] = {"items": ["x"]}
    graph = {
        "nodes": [outer, inner, _node("leaf", 2)],
        "edges": [
            _edge("outer", "inner", "each"),
            _edge("inner", "leaf", "each"),
            _edge("leaf", "inner", "main", "loop"),
            _edge("inner", "outer", "done", "loop"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "outer",
        _catalog({"volume.for": _walk, "fake": _walk}, loops={"volume.for": "each"}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["outer", "inner", "leaf", "inner", "leaf"]
    assert [item["saw"] for item in hooks.outputs["outer"]["results"][0]["results"]] == [1]
    assert hooks.outputs["outer"]["results"][1]["results"][0]["saw"] == 2


def test_cancel_inside_a_for_body() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1), _node("tail", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "tail"),
            _edge("tail", "walk", "main", "loop"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    hooks.cancel_after = "step"
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _ok}, loops={"volume.for": "each"}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert outcome.stopped_node_id == "tail"
    assert hooks.order == ["walk", "step"]


def test_stop_at_inside_a_for_body_excludes_the_rest() -> None:
    start = _node("start", 0)
    walk = _node("walk", 1, type_id="volume.for")
    walk["config"] = {"items": ["a"]}
    graph = {
        "nodes": [start, walk, _node("step", 2), _node("side", 3), _node("after", 4)],
        "edges": [
            _edge("start", "walk"),
            _edge("walk", "step", "each"),
            _edge("walk", "side", "each"),
            _edge("step", "walk", "main", "loop"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "start",
        _catalog({"fake": _ok, "volume.for": _walk}, loops={"volume.for": "each"}),
        _RESOLVER,
        hooks,
        stop_at_node_id="step",
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["start", "walk", "step"]
    assert hooks.outputs["walk"]["results"] == [{"id": "step"}]


def test_timeout_inside_a_for_body() -> None:
    import time

    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a"]}

    def slow(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "step":
            time.sleep(0.05)
        return _ok(node, hooks)

    graph = {
        "nodes": [walk, _node("step", 1), _node("tail", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "tail"),
            _edge("tail", "walk", "main", "loop"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "walk",
        _catalog({"volume.for": _walk, "fake": slow}, loops={"volume.for": "each"}),
        _RESOLVER,
        hooks,
        timeout_sec=0.01,
    )
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_RUN_TIMEOUT"
    assert outcome.stopped_node_id == "tail"
    assert hooks.order == ["walk", "step"]


_STRICT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"n": {"type": "integer"}},
    "required": ["n"],
}
_OPEN = {"type": "object"}


def test_output_check_uses_the_upstream_refined_schema() -> None:
    def source_refine(config: dict, upstream: dict, resolver: object) -> dict:
        del config, upstream, resolver
        return {"main": _STRICT}

    def sink_refine(config: dict, upstream: dict, resolver: object) -> dict:
        del config, resolver
        produced = upstream.get("src")
        if isinstance(produced, dict) and produced.get("main") == _STRICT:
            return {"main": _STRICT}
        return {"main": _OPEN}

    def emit(node: dict, hooks: EngineHooks, value: dict) -> NodeResult:
        del hooks
        if node["id"] == "src":
            return NodeResult(status="succeeded", output={"n": 1})
        return NodeResult(status="succeeded", output=value)

    graph = {
        "nodes": [_node("src", 0, type_id="source"), _node("sink", 1, type_id="sink")],
        "edges": [_edge("src", "sink")],
        "settings": {},
    }

    def catalog(value: dict) -> list[NodeType]:
        return [
            _type("source", lambda node, hooks: emit(node, hooks, value), refine=source_refine),
            _type("sink", lambda node, hooks: emit(node, hooks, value), refine=sink_refine),
        ]

    mismatch = execute(graph, "src", catalog({"n": "x"}), _RESOLVER, FakeHooks())
    assert mismatch.status == "failed"
    assert mismatch.error_code == "CHANNEL_OUTPUT_SCHEMA_MISMATCH"
    assert mismatch.error_message == "Output does not match the declared schema"
    assert mismatch.failed_node_id == "sink"

    matched = execute(graph, "src", catalog({"n": 1}), _RESOLVER, FakeHooks())
    assert matched.status == "succeeded"


def test_pinned_output_bypasses_execute() -> None:
    def ran(node: dict, hooks: EngineHooks) -> NodeResult:
        del node, hooks
        return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="ran")

    hooks = FakeHooks(pinned={"a": {"kept": True}})
    outcome = execute(
        {"nodes": [_node("a", 0)], "edges": [], "settings": {}},
        "a",
        [_type("fake", ran)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.outputs["a"] == {"kept": True}
    assert ("a", "pinned") in hooks.statuses


def test_pinned_if_selects_the_branch_from_value() -> None:
    if_type = next(item for item in list_node_types() if item.type_id == "transform.if")

    def ran(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        return NodeResult(status="succeeded", output={"id": node["id"]})

    def graph() -> dict:
        return {
            "nodes": [
                _node("g", 0, type_id="transform.if"),
                _node("yes", 1),
                _node("no", 2),
            ],
            "edges": [_edge("g", "yes", "true"), _edge("g", "no", "false")],
            "settings": {},
        }

    catalog = [if_type, _type("fake", ran)]
    true_hooks = FakeHooks(pinned={"g": {"value": True}})
    true_outcome = execute(graph(), "g", catalog, _RESOLVER, true_hooks)
    assert true_outcome.status == "succeeded"
    assert true_hooks.order == ["g", "yes"]

    false_hooks = FakeHooks(pinned={"g": {"value": False}})
    false_outcome = execute(graph(), "g", catalog, _RESOLVER, false_hooks)
    assert false_outcome.status == "succeeded"
    assert false_hooks.order == ["g", "no"]

    missing = execute(
        {"nodes": [_node("g", 0, type_id="transform.if")], "edges": [], "settings": {}},
        "g",
        [if_type],
        _RESOLVER,
        FakeHooks(pinned={"g": {}}),
    )
    assert missing.status == "failed"
    assert missing.error_code == "CHANNEL_NODE_FAILED"
    assert missing.error_message == "Pinned If output has no value"
