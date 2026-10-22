"""Pure control-flow engine."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.channel.engine import execute
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, PortSpec
from backend.tests.channel_hooks_fake import FakeHooks


class _Resolver:
    def entity_head(self, entity_id: str) -> None:
        return None

    def channel_exists(self, channel_id: str) -> bool:
        return False

    def published_trigger_type(self, channel_id: str) -> str | None:
        del channel_id
        return None

    def source_exists(self, source_id: str) -> bool:
        return False


_RESOLVER = _Resolver()


def _type(
    type_id: str,
    run: Callable[..., NodeResult],
    *,
    refine: Callable[..., dict] | None = None,
) -> NodeType:
    return NodeType(
        type_id=type_id,
        family="test",
        label=type_id,
        summary="Test node.",
        description="Test node. Used only by the engine suite.",
        trigger=False,
        inputs=(PortSpec("main", "Input."), PortSpec("loop", "Loop return.")),
        outputs=(PortSpec("main", "Output."),),
        config_schema={"type": "object"},
        execute=run,
        refine=refine,
    )


def _catalog(bound: dict[str, Callable[..., NodeResult]]) -> list[NodeType]:
    return [_type(type_id, run) for type_id, run in bound.items()]


def _node(
    node_id: str,
    y: float,
    x: float = 0,
    type_id: str = "fake",
    *,
    parent: str | None = None,
) -> dict:
    node = {
        "id": node_id,
        "type": type_id,
        "name": node_id,
        "ref": node_id,
        "position": {"x": x, "y": y},
        "config": {},
        "on_error": "stop",
        "retry": None,
    }
    if parent is not None:
        node["parent"] = parent
    return node


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


def test_a_node_that_raises_because_the_run_stopped_is_not_marked_failed() -> None:
    def write(node: dict, hooks: EngineHooks) -> NodeResult:
        if hooks.cancelled() or hooks.superseded():
            raise RuntimeError("cancelled")
        return NodeResult(status="succeeded", output={"id": node["id"]})

    class _Superseded(FakeHooks):
        def superseded(self) -> bool:
            return "write" in self.order

    graph = {
        "nodes": [_node("a", 0), _node("write", 1)],
        "edges": [_edge("a", "write")],
        "settings": {},
    }
    cancelled = FakeHooks()
    cancelled.cancel_after = "write"
    with pytest.raises(RuntimeError, match="cancelled"):
        execute(graph, "a", _catalog({"fake": write}), _RESOLVER, cancelled)
    assert cancelled.statuses == [("a", "succeeded"), ("write", "running")]

    superseded = _Superseded()
    with pytest.raises(RuntimeError, match="cancelled"):
        execute(graph, "a", _catalog({"fake": write}), _RESOLVER, superseded)
    assert superseded.statuses == [("a", "succeeded"), ("write", "running")]


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
        output = {"current": None, "index": None, "count": 0}
    else:
        output = {"current": items[-1], "index": count - 1, "count": count}
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


def test_for_runs_the_body_once_per_element_and_records_iterations() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _walk}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk", "step", "step", "after"]
    assert hooks.outputs["walk"]["iterations"] == [
        {"step": {"saw": "a", "id": "step"}},
        {"step": {"saw": "b", "id": "step"}},
    ]
    assert "results" not in hooks.outputs["walk"]
    assert hooks.outputs["walk"]["current"] == "b"
    assert hooks.outputs["walk"]["index"] == 1
    assert hooks.dropped == [["step"], ["step"]]


def test_for_runs_each_element_of_a_non_list_iterable() -> None:
    def walk(node: dict, hooks: EngineHooks) -> NodeResult:
        result = _walk(node, hooks)
        if result.iterations is not None:
            result.iterations = tuple(result.iterations)
        return result

    walk_node = _node("walk", 0, type_id="volume.for")
    walk_node["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk_node, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": walk, "fake": walk}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk", "step", "step", "after"]
    assert hooks.outputs["walk"]["iterations"] == [
        {"step": {"saw": "a", "id": "step"}},
        {"step": {"saw": "b", "id": "step"}},
    ]


def test_for_empty_list_skips_the_body_and_still_runs_done() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": []}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _walk}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk", "after"]
    assert hooks.outputs["walk"]["iterations"] == []
    assert hooks.outputs["walk"]["count"] == 0
    assert hooks.outputs["walk"]["current"] is None
    assert hooks.outputs["walk"]["index"] is None
    assert hooks.dropped == []


def test_nested_for_records_the_inner_output_as_one_key() -> None:
    outer = _node("outer", 0, type_id="volume.for")
    outer["config"] = {"items": [1, 2]}
    inner = _node("inner", 1, type_id="volume.for", parent="outer")
    inner["config"] = {"items": ["x"]}
    graph = {
        "nodes": [outer, inner, _node("leaf", 2, parent="inner")],
        "edges": [
            _edge("outer", "inner", "each"),
            _edge("inner", "leaf", "each"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "outer",
        _catalog({"volume.for": _walk, "fake": _walk}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["outer", "inner", "leaf", "inner", "leaf"]
    assert set(hooks.outputs["outer"]["iterations"][0]) == {"inner"}
    assert hooks.outputs["outer"]["iterations"][0]["inner"]["iterations"] == [
        {"leaf": {"saw": 1, "id": "leaf"}}
    ]
    assert hooks.outputs["outer"]["iterations"][1]["inner"]["iterations"][0]["leaf"]["saw"] == 2
    assert hooks.dropped == [["inner"], ["leaf"], ["inner"], ["leaf"]]


def test_for_iteration_omits_the_branch_that_did_not_run() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": [1]}
    gate = _node("gate", 1, type_id="transform.if", parent="walk")
    gate["config"] = {"live": "true"}
    graph = {
        "nodes": [
            walk,
            gate,
            _node("live", 2, parent="walk"),
            _node("dead", 3, parent="walk"),
            _node("after", 4),
        ],
        "edges": [
            _edge("walk", "gate", "each"),
            _edge("gate", "live", "true"),
            _edge("gate", "dead", "false"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "walk",
        _catalog({"volume.for": _walk, "transform.if": _branch, "fake": _branch}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["walk", "gate", "live", "after"]
    assert hooks.outputs["walk"]["iterations"] == [
        {"gate": {"value": True}, "live": {"id": "live"}}
    ]


def test_a_container_in_the_set_runs_its_body_once_per_element(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(),
    )

    def batch(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["type"] != "volume.batch_read":
            current = hooks.outputs.get("batch") or {}
            return NodeResult(status="succeeded", output={"saw": current.get("current"), "id": node["id"]})
        items = list(node["config"].get("items") or [])
        iterations = [{"current": item, "index": index, "count": len(items)} for index, item in enumerate(items)]
        return NodeResult(
            status="succeeded",
            output={"count": len(items)},
            iterations=iterations,
            ports=frozenset({"done"}),
        )

    node = _node("batch", 0, type_id="volume.batch_read")
    node["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [node, _node("step", 1, parent="batch")],
        "edges": [_edge("batch", "step", "each")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "batch",
        _catalog({"volume.batch_read": batch, "fake": batch}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["batch", "step", "step"]
    assert hooks.outputs["batch"]["iterations"] == [
        {"step": {"saw": "a", "id": "step"}},
        {"step": {"saw": "b", "id": "step"}},
    ]


def test_a_container_that_does_not_accumulate_skips_the_16_mib_cap(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType
    from backend.channel.variables import value_size

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    blob = "x" * 30
    one_round = [{"step": {"blob": blob}}]
    monkeypatch.setattr(
        "backend.channel.engine.ITERATION_VOLUME_MAX_BYTES",
        value_size(one_round),
    )

    def batch(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["type"] == "volume.batch_read":
            items = list(node["config"].get("items") or [])
            iterations = [{"current": item} for item in items]
            return NodeResult(
                status="succeeded",
                output={"count": len(items)},
                iterations=iterations,
                ports=frozenset({"done"}),
            )
        return NodeResult(status="succeeded", output={"blob": blob})

    node = _node("batch", 0, type_id="volume.batch_read")
    node["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [node, _node("step", 1, parent="batch"), _node("after", 2)],
        "edges": [
            _edge("batch", "step", "each"),
            _edge("batch", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "batch",
        _catalog({"volume.batch_read": batch, "fake": batch}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert outcome.error_code is None
    assert hooks.order == ["batch", "step", "step", "after"]
    assert "iterations" not in hooks.outputs["batch"]
    assert hooks.outputs["batch"]["count"] == 2


def test_for_fails_when_iteration_output_exceeds_16_mib(monkeypatch) -> None:
    from backend.channel.engine import ITERATION_VOLUME_MAX_BYTES
    from backend.channel.variables import value_size

    assert ITERATION_VOLUME_MAX_BYTES == 16 * 1024 * 1024
    blob = "x" * 30
    one_round = [{"step": {"blob": blob}}]
    monkeypatch.setattr(
        "backend.channel.engine.ITERATION_VOLUME_MAX_BYTES",
        value_size(one_round),
    )

    def bulky(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["type"] == "volume.for":
            return _walk(node, hooks)
        return NodeResult(status="succeeded", output={"blob": blob})

    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": bulky, "fake": bulky}), _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert outcome.failed_node_id == "walk"
    assert outcome.error_message is not None
    assert "batch" in outcome.error_message.lower()
    assert hooks.order == ["walk", "step", "step"]
    assert "after" not in hooks.order


def test_engine_runs_volume_for_without_rejecting_the_each_schema() -> None:
    import importlib

    for_type = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE

    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": '["a", "b"]'}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "walk",
        [for_type, _type("fake", _ok)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert outcome.error_code is None
    assert hooks.order == ["walk", "step", "step", "after"]
    assert hooks.outputs["walk"]["iterations"] == [
        {"step": {"id": "step"}},
        {"step": {"id": "step"}},
    ]
    assert hooks.outputs["walk"]["count"] == 2
    assert hooks.outputs["walk"]["current"] == "b"


def test_body_execution_names_the_direct_container_and_round() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("after", 2)],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _walk}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.starts == [
        ("walk", None, None),
        ("step", 1, 0),
        ("step", 1, 1),
        ("after", None, None),
    ]


def test_nested_for_body_names_the_inner_container() -> None:
    outer = _node("outer", 0, type_id="volume.for")
    outer["config"] = {"items": [1, 2]}
    inner = _node("inner", 1, type_id="volume.for", parent="outer")
    inner["config"] = {"items": ["x"]}
    graph = {
        "nodes": [outer, inner, _node("leaf", 2, parent="inner")],
        "edges": [
            _edge("outer", "inner", "each"),
            _edge("inner", "leaf", "each"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "outer",
        _catalog({"volume.for": _walk, "fake": _walk}),
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.starts == [
        ("outer", None, None),
        ("inner", 1, 0),
        ("leaf", 2, 0),
        ("inner", 1, 1),
        ("leaf", 4, 0),
    ]


def test_cancel_inside_a_for_body() -> None:
    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a", "b"]}
    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("tail", 2, parent="walk")],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "tail"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    hooks.cancel_after = "step"
    outcome = execute(graph, "walk", _catalog({"volume.for": _walk, "fake": _ok}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert outcome.stopped_node_id == "tail"
    assert hooks.order == ["walk", "step"]


def test_stop_at_inside_a_for_body_excludes_the_back_edge_downstream() -> None:
    start = _node("start", 0)
    walk = _node("walk", 1, type_id="volume.for")
    walk["config"] = {"items": ["a"]}
    graph = {
        "nodes": [
            start,
            walk,
            _node("step", 2, parent="walk"),
            _node("tail", 3, parent="walk"),
            _node("side", 4, parent="walk"),
            _node("after", 5),
        ],
        "edges": [
            _edge("start", "walk"),
            _edge("walk", "step", "each"),
            _edge("step", "tail"),
            _edge("tail", "walk", "main", "loop"),
            _edge("walk", "side", "each"),
            _edge("walk", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "start",
        _catalog({"fake": _ok, "volume.for": _walk}),
        _RESOLVER,
        hooks,
        stop_at_node_id="step",
    )
    assert outcome.status == "succeeded"
    assert hooks.order == ["start", "walk", "step"]
    assert "tail" not in hooks.order
    assert "side" not in hooks.order
    assert hooks.outputs["walk"]["iterations"] == [{"step": {"id": "step"}}]


def test_timeout_inside_a_for_body() -> None:
    import time

    walk = _node("walk", 0, type_id="volume.for")
    walk["config"] = {"items": ["a"]}

    def slow(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "step":
            time.sleep(0.05)
        return _ok(node, hooks)

    graph = {
        "nodes": [walk, _node("step", 1, parent="walk"), _node("tail", 2, parent="walk")],
        "edges": [
            _edge("walk", "step", "each"),
            _edge("step", "tail"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        graph,
        "walk",
        _catalog({"volume.for": _walk, "fake": slow}),
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


def _error_type(run: Callable[..., NodeResult]) -> NodeType:
    return NodeType(
        type_id="fake",
        family="test",
        label="fake",
        summary="Test node.",
        description="Test node. Used only by the engine suite.",
        trigger=False,
        inputs=(PortSpec("main", "Input."),),
        outputs=(PortSpec("main", "Output."), PortSpec("error", "Error.")),
        config_schema={"type": "object"},
        execute=run,
    )


def test_continue_keeps_the_main_branch_and_the_run() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "b":
            return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="bad")
        return _ok(node, hooks)

    broken = _node("b", 1)
    broken["on_error"] = "continue"
    graph = {
        "nodes": [_node("a", 0), broken, _node("c", 2)],
        "edges": [_edge("a", "b"), _edge("b", "c")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": fail}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert outcome.failed_node_id is None
    assert hooks.order == ["a", "b", "c"]
    assert hooks.outputs["b"] is None
    assert hooks.statuses == [("a", "succeeded"), ("b", "failed"), ("c", "succeeded")]


def test_error_output_is_the_only_live_branch() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "b":
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="bad",
                error_detail={"row": 1},
            )
        return _ok(node, hooks)

    broken = _node("b", 1)
    broken["on_error"] = "error_output"
    graph = {
        "nodes": [_node("a", 0), broken, _node("c", 2), _node("d", 3)],
        "edges": [
            _edge("a", "b"),
            _edge("b", "c", "error"),
            _edge("b", "d", "main"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", [_error_type(fail)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert outcome.failed_node_id is None
    assert hooks.order == ["a", "b", "c"]
    assert hooks.outputs["b"] == {
        "code": "CHANNEL_NODE_FAILED",
        "message": "bad",
        "detail": {"row": 1},
    }


def test_retry_runs_again_until_success() -> None:
    calls = {"b": 0}

    def flaky(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "b":
            return _ok(node, hooks)
        calls["b"] += 1
        if calls["b"] < 3:
            return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="later")
        return _ok(node, hooks)

    retried = _node("b", 1)
    retried["retry"] = {"max_tries": 3, "wait_sec": 0}
    graph = {
        "nodes": [_node("a", 0), retried, _node("c", 2)],
        "edges": [_edge("a", "b"), _edge("b", "c")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": flaky}), _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["a", "b", "b", "b", "c"]
    assert calls["b"] == 3


def test_cancel_during_retry_wait_does_not_execute_again() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="bad")

    retried = _node("a", 0)
    retried["retry"] = {"max_tries": 3, "wait_sec": 30}
    graph = {"nodes": [retried], "edges": [], "settings": {}}
    hooks = FakeHooks()
    hooks.cancel_after = "a"
    outcome = execute(graph, "a", _catalog({"fake": fail}), _RESOLVER, hooks)
    assert outcome.status == "cancelled"
    assert hooks.order == ["a"]


def test_retries_exhausted_then_stop() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        return NodeResult(status="failed", error_code="CHANNEL_NODE_FAILED", error_message="bad")

    retried = _node("a", 0)
    retried["retry"] = {"max_tries": 2, "wait_sec": 0}
    retried["on_error"] = "stop"
    graph = {"nodes": [retried, _node("b", 1)], "edges": [_edge("a", "b")], "settings": {}}
    hooks = FakeHooks()
    outcome = execute(graph, "a", _catalog({"fake": fail}), _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "a"
    assert hooks.order == ["a", "a"]
    assert "b" not in hooks.order
