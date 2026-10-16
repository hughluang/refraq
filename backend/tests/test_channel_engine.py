"""Pure control-flow engine."""

from __future__ import annotations

from backend.channel.engine import EngineHooks, NodeResult, execute
from backend.tests.channel_hooks_fake import FakeHooks


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
    outcome = execute(graph, "a", {"fake": _ok}, hooks, stop_at_node_id="d")
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
    outcome = execute(graph, "a", {"fake": _ok}, hooks)
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
    outcome = execute(graph, "a", {"fake": fail}, hooks)
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
    outcome = execute(graph, "a", {"fake": skip}, hooks)
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
        {"fake": _ok},
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
    outcome = execute(graph, "a", {"fake": _ok}, hooks)
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
        {"fake": _ok},
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
    outcome = execute(graph, "a", {"fake": _ok}, hooks)
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
    outcome = execute(graph, "a", {"fake": _ok}, hooks)
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
    outcome = execute(graph, "gate", {"transform.if": _branch, "fake": _branch}, hooks)
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
    outcome = execute(graph, "s", {"fake": _ok}, hooks)
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
    outcome = execute(graph, "walk", {"volume.for": _walk, "fake": _walk}, hooks, loop_ports={"volume.for": "each"})
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
    outcome = execute(graph, "walk", {"volume.for": _walk, "fake": _walk}, hooks, loop_ports={"volume.for": "each"})
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
        {"volume.for": _walk, "fake": _walk},
        hooks,
        loop_ports={"volume.for": "each"},
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
    outcome = execute(graph, "walk", {"volume.for": _walk, "fake": _ok}, hooks, loop_ports={"volume.for": "each"})
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
        {"fake": _ok, "volume.for": _walk},
        hooks,
        stop_at_node_id="step",
        loop_ports={"volume.for": "each"},
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
        {"volume.for": _walk, "fake": slow},
        hooks,
        timeout_sec=0.01,
        loop_ports={"volume.for": "each"},
    )
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_RUN_TIMEOUT"
    assert outcome.stopped_node_id == "tail"
    assert hooks.order == ["walk", "step"]
