"""Pure control-flow engine."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend.channel.engine import execute
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, OutputView, PortSpec
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
        output_view=OutputView(kind="record"),
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
        output_view=OutputView(kind="record"),
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


def test_batch_read_hands_each_round_one_page_and_stores_only_the_totals(monkeypatch) -> None:
    from datetime import datetime, timezone

    import backend.channel.nodes.volume.batch_read as batch_read
    from backend.channel.dataset_registry import DatasetRecord, MemoryDatasetStore

    pages = {
        0: [{"_ord": 1, "n": 1}, {"_ord": 2, "n": 2}],
        2: [{"_ord": 3, "n": 3}],
    }
    trace: list[tuple[str, int]] = []

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation
        assert limit == 2
        trace.append(("page", after_ord))
        return [dict(row) for row in pages[after_ord]]

    store = MemoryDatasetStore()
    store.save(
        DatasetRecord(
            id="dset",
            job_id="run",
            node_id="load",
            seq=1,
            relation='"channel_dataset"."ds_dset"',
            columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
            row_count=3,
            size_bytes=1,
            status="ready",
            created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        )
    )

    def used_bytes() -> int:
        raise AssertionError("quota checked on read")

    store.used_bytes = used_bytes  # type: ignore[method-assign]
    monkeypatch.setattr(batch_read, "get_dataset_store", lambda: store)
    monkeypatch.setattr(batch_read, "read_keyset_page", page)
    monkeypatch.setattr(batch_read, "any_row_exists", lambda relation: True)

    seen: list[dict] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["batch"]
        trace.append(("body", current["index"]))
        seen.append(dict(current))
        return NodeResult(status="succeeded", output={"rows": current["rows"]})

    node = _node("batch", 0, type_id="volume.batch_read")
    node["config"] = {
        "dataset": '{"dataset_id":"dset","columns":[{"name":"n","type":"integer"}],"count":3}',
        "batch_size": 2,
    }
    graph = {
        "nodes": [node, _node("step", 1, parent="batch"), _node("after", 2)],
        "edges": [
            _edge("batch", "step", "each"),
            _edge("batch", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "batch", [batch_read.NODE_TYPE, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert outcome.error_code is None
    assert trace == [("page", 0), ("body", 0), ("page", 2), ("body", 1)]
    assert seen == [
        {"rows": [{"n": 1}, {"n": 2}], "index": 0, "count": 2, "total": 3},
        {"rows": [{"n": 3}], "index": 1, "count": 2, "total": 3},
    ]
    assert hooks.order == ["batch", "step", "step", "after"]
    assert hooks.outputs["batch"] == {"count": 2, "total": 3, "batch_size": 2}
    assert "iterations" not in hooks.outputs["batch"]


def _plant_dataset(
    monkeypatch,
    batch_read,
    *,
    row_count: int,
    page,
    exists=None,
    job_id: str = "run",
    status: str = "ready",
    expires_at=None,
    dataset_id: str = "dset",
    save: bool = True,
) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetRecord, MemoryDatasetStore

    store = MemoryDatasetStore()
    if save:
        store.save(
            DatasetRecord(
                id=dataset_id,
                job_id=job_id,
                node_id="load",
                seq=1,
                relation='"channel_dataset"."ds_dset"',
                columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
                row_count=row_count,
                size_bytes=1,
                status=status,
                created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
                expires_at=expires_at,
            )
        )
    monkeypatch.setattr(batch_read, "get_dataset_store", lambda: store)
    monkeypatch.setattr(batch_read, "read_keyset_page", page)
    monkeypatch.setattr(
        batch_read,
        "any_row_exists",
        exists if exists is not None else (lambda relation: True),
    )


def _batch_node(*, batch_size: int | None = None) -> dict:
    config = {
        "dataset": '{"dataset_id":"dset","columns":[{"name":"n","type":"integer"}],"count":0}',
    }
    if batch_size is not None:
        config["batch_size"] = batch_size
    node = _node("batch", 0, type_id="volume.batch_read")
    node["config"] = config
    return node


def test_batch_read_empty_dataset_skips_the_body_and_still_runs_done(monkeypatch) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read

    calls = {"exists": 0, "page": 0}

    def exists(relation: str) -> bool:
        del relation
        calls["exists"] += 1
        return True

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation, after_ord, limit
        calls["page"] += 1
        return []

    _plant_dataset(monkeypatch, batch_read, row_count=0, page=page, exists=exists)
    node = _batch_node()
    graph = {
        "nodes": [node, _node("step", 1, parent="batch"), _node("after", 2)],
        "edges": [_edge("batch", "step", "each"), _edge("batch", "after", "done")],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "batch", [batch_read.NODE_TYPE, _type("fake", _ok)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["batch", "after"]
    assert hooks.outputs["batch"] == {"count": 0, "total": 0, "batch_size": 1000}
    assert "iterations" not in hooks.outputs["batch"]
    assert calls == {"exists": 0, "page": 0}


class _Finished(FakeHooks):
    def __init__(self) -> None:
        super().__init__()
        self.finished: list[tuple[str, str, dict | None]] = []

    def on_finish(self, seq: int, node: dict, result: NodeResult) -> None:
        super().on_finish(seq, node, result)
        self.finished.append((str(node["id"]), result.status, result.error_detail))


def test_batch_read_stop_names_the_failed_batch_and_skips_done(monkeypatch) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read

    _plant_dataset(
        monkeypatch,
        batch_read,
        row_count=2,
        page=lambda relation, *, after_ord, limit: [{"_ord": after_ord + 1, "n": after_ord}],
    )
    node = _batch_node(batch_size=1)

    def step(body: dict, hooks: EngineHooks) -> NodeResult:
        if body["id"] == "step" and hooks.outputs["batch"]["index"] == 1:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="bad row",
            )
        return NodeResult(status="succeeded", output={"index": hooks.outputs["batch"]["index"]})

    broken = _node("step", 1, parent="batch")
    graph = {
        "nodes": [node, broken, _node("after", 2)],
        "edges": [_edge("batch", "step", "each"), _edge("batch", "after", "done")],
        "settings": {},
    }
    hooks = _Finished()
    outcome = execute(graph, "batch", [batch_read.NODE_TYPE, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "step"
    assert hooks.order == ["batch", "step", "step"]
    assert "after" not in hooks.order
    assert ("step", "succeeded", None) in hooks.finished
    assert ("batch", "failed", {"index": 1}) in hooks.finished


def test_batch_read_and_for_nest_in_either_direction(monkeypatch) -> None:
    import importlib

    import backend.channel.nodes.volume.batch_read as batch_read

    for_type = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE

    def one_row(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation, limit
        return [{"_ord": after_ord + 1, "n": after_ord + 1}]

    _plant_dataset(monkeypatch, batch_read, row_count=1, page=one_row)
    batch = _batch_node(batch_size=1)
    inner = _node("inner", 1, type_id="volume.for", parent="batch")
    inner["config"] = {"items": "[10, 20]"}
    inside = {
        "nodes": [batch, inner, _node("leaf", 2, parent="inner")],
        "edges": [
            _edge("batch", "inner", "each"),
            _edge("inner", "leaf", "each"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(
        inside,
        "batch",
        [batch_read.NODE_TYPE, for_type, _type("fake", _ok)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded"
    assert hooks.starts == [
        ("batch", None, None),
        ("inner", 1, 0),
        ("leaf", 2, 0),
        ("leaf", 2, 1),
    ]
    assert "iterations" not in hooks.outputs["batch"]
    assert hooks.outputs["inner"]["iterations"] == [
        {"leaf": {"id": "leaf"}},
        {"leaf": {"id": "leaf"}},
    ]

    _plant_dataset(monkeypatch, batch_read, row_count=2, page=one_row)
    outer = _node("outer", 0, type_id="volume.for")
    outer["config"] = {"items": "[1]"}
    nested = _batch_node(batch_size=1)
    nested["parent"] = "outer"
    nested["position"] = {"x": 0, "y": 1}
    outside = {
        "nodes": [outer, nested, _node("leaf", 2, parent="batch")],
        "edges": [
            _edge("outer", "batch", "each"),
            _edge("batch", "leaf", "each"),
        ],
        "settings": {},
    }
    again = FakeHooks()
    outcome = execute(
        outside,
        "outer",
        [batch_read.NODE_TYPE, for_type, _type("fake", _ok)],
        _RESOLVER,
        again,
    )
    assert outcome.status == "succeeded"
    assert again.starts == [
        ("outer", None, None),
        ("batch", 1, 0),
        ("leaf", 2, 0),
        ("leaf", 2, 1),
    ]
    assert again.outputs["outer"]["iterations"] == [
        {"batch": {"count": 2, "total": 2, "batch_size": 1}}
    ]


def test_batch_read_continue_and_error_output_follow_the_body(monkeypatch) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read

    _plant_dataset(
        monkeypatch,
        batch_read,
        row_count=2,
        page=lambda relation, *, after_ord, limit: [{"_ord": after_ord + 1, "n": after_ord}],
    )

    def run(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "step" and hooks.outputs["batch"]["index"] == 0:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="bad",
                error_detail={"row": 1},
            )
        return NodeResult(status="succeeded", output={"id": node["id"]})

    continued = _node("step", 1, parent="batch")
    continued["on_error"] = "continue"
    graph = {
        "nodes": [_batch_node(batch_size=1), continued, _node("tail", 2, parent="batch"), _node("after", 3)],
        "edges": [
            _edge("batch", "step", "each"),
            _edge("step", "tail"),
            _edge("batch", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(graph, "batch", [batch_read.NODE_TYPE, _type("fake", run)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["batch", "step", "tail", "step", "tail", "after"]
    assert [status for node_id, status in hooks.statuses if node_id == "step"] == [
        "failed",
        "succeeded",
    ]

    routed = _node("step", 1, parent="batch")
    routed["on_error"] = "error_output"
    branched = {
        "nodes": [
            _batch_node(batch_size=1),
            routed,
            _node("bad", 2, parent="batch"),
            _node("good", 3, parent="batch"),
            _node("after", 4),
        ],
        "edges": [
            _edge("batch", "step", "each"),
            _edge("step", "bad", "error"),
            _edge("step", "good"),
            _edge("batch", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks()
    outcome = execute(branched, "batch", [batch_read.NODE_TYPE, _error_type(run)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert hooks.order == ["batch", "step", "bad", "step", "good", "after"]
    assert [status for node_id, status in hooks.statuses if node_id == "step"] == [
        "failed",
        "succeeded",
    ]


def test_batch_read_converts_json_values_like_sql_read(monkeypatch) -> None:
    from datetime import datetime, timezone
    from decimal import Decimal

    import backend.channel.nodes.volume.batch_read as batch_read

    seen = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation, after_ord, limit
        return [{"_ord": 1, "amount": Decimal("1.50"), "seen": seen}]

    _plant_dataset(monkeypatch, batch_read, row_count=1, page=page)
    caught: list[dict] = []

    def step(body: dict, hooks: EngineHooks) -> NodeResult:
        if body["id"] == "step":
            caught.append(hooks.outputs["batch"]["rows"][0])
        return NodeResult(status="succeeded", output={"id": body["id"]})

    graph = {
        "nodes": [_batch_node(batch_size=1), _node("step", 1, parent="batch")],
        "edges": [_edge("batch", "step", "each")],
        "settings": {},
    }
    outcome = execute(
        graph, "batch", [batch_read.NODE_TYPE, _type("fake", step)], _RESOLVER, FakeHooks()
    )
    assert outcome.status == "succeeded"
    assert caught == [{"amount": "1.50", "seen": "2026-10-22T12:00:00Z"}]


def test_batch_read_fails_before_the_body_when_the_dataset_is_unusable(monkeypatch) -> None:
    from datetime import datetime, timezone

    import backend.channel.nodes.volume.batch_read as batch_read
    from sqlalchemy.exc import ProgrammingError

    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    pages = {"n": 0}

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation, after_ord, limit
        pages["n"] += 1
        return []

    def ran(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        raise AssertionError(node["id"])

    cases = [
        ("not_found", {"save": False}, None),
        ("not_found", {"empty_id": True}, None),
        ("foreign_run", {"job_id": "other", "expires_at": past}, None),
        ("expired", {"expires_at": past}, None),
        ("expired", {"status": "dropped"}, None),
        ("not_found", {"status": "loading"}, None),
        ("lost", {"row_count": 2}, lambda relation: False),
    ]
    for reason, overrides, exists in cases:
        pages["n"] = 0
        _plant_dataset(
            monkeypatch,
            batch_read,
            row_count=overrides.get("row_count", 1),
            page=page,
            exists=exists,
            job_id=overrides.get("job_id", "run"),
            status=overrides.get("status", "ready"),
            expires_at=overrides.get("expires_at"),
            save=overrides.get("save", True),
        )
        node = _batch_node(batch_size=1)
        if overrides.get("save") is False:
            node["config"]["dataset"] = '{"dataset_id":"missing","columns":[],"count":0}'
        if overrides.get("empty_id") is True:
            node["config"]["dataset"] = '{"dataset_id":"","columns":[],"count":0}'
        graph = {
            "nodes": [node, _node("step", 1, parent="batch"), _node("after", 2)],
            "edges": [_edge("batch", "step", "each"), _edge("batch", "after", "done")],
            "settings": {},
        }
        hooks = _Finished()
        outcome = execute(
            graph, "batch", [batch_read.NODE_TYPE, _type("fake", ran)], _RESOLVER, hooks
        )
        assert outcome.status == "failed", reason
        assert outcome.error_code == "CHANNEL_DATASET_UNAVAILABLE", reason
        assert outcome.failed_node_id == "batch"
        assert hooks.order == ["batch"], reason
        assert ("batch", "failed", {"reason": reason}) in hooks.finished
        assert pages["n"] == 0

    def missing(relation: str) -> bool:
        del relation
        raise ProgrammingError(
            "SELECT 1",
            {},
            Exception('relation "channel_dataset"."ds_dset" does not exist'),
        )

    pages["n"] = 0
    _plant_dataset(monkeypatch, batch_read, row_count=2, page=page, exists=missing)
    hooks = _Finished()
    outcome = execute(
        {
            "nodes": [_batch_node(batch_size=1), _node("step", 1, parent="batch")],
            "edges": [_edge("batch", "step", "each")],
            "settings": {},
        },
        "batch",
        [batch_read.NODE_TYPE, _type("fake", ran)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_NODE_FAILED"
    assert "does not exist" in (outcome.error_message or "")
    assert hooks.order == ["batch"]
    assert pages["n"] == 0
    assert all(detail != {"reason": "lost"} for _node_id, _status, detail in hooks.finished)


def test_batch_read_stores_a_preview_of_a_successful_body_and_the_full_failed_body(
    monkeypatch,
) -> None:
    import uuid

    import backend.channel.nodes.volume.batch_read as batch_read
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.run_store import ChannelRunRecord, get_run_store, output_size
    from backend.channel.sandbox import SandboxSession
    from backend.core.time import utc_now

    rows = list(range(120))
    tags = ["a", "b"]

    def succeed(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        return NodeResult(status="succeeded", output={"rows": rows, "tags": tags})

    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        return NodeResult(
            status="failed",
            output={"rows": rows},
            error_code="CHANNEL_NODE_FAILED",
            error_message="bad row",
        )

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation, after_ord, limit
        return [{"_ord": 1, "n": 1}]

    user = UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )

    def run(body, *, on_error: str) -> str:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        _plant_dataset(monkeypatch, batch_read, row_count=1, page=page, job_id=job_id)
        step = _node("step", 1, parent="batch")
        step["on_error"] = on_error
        graph = {
            "nodes": [_batch_node(batch_size=1), step],
            "edges": [_edge("batch", "step", "each")],
            "settings": {},
        }
        get_run_store().insert_run(
            ChannelRunRecord(
                job_id=job_id,
                channel_id="chn_preview",
                target="draft",
                version=None,
                draft_revision=1,
                graph=graph,
                trigger_node_id="batch",
                ignore_checkpoints=False,
                outcome=None,
                failed_node_id=None,
                skipped_node_ids=[],
                created_at=utc_now(),
            )
        )
        return job_id, graph

    success_id, success_graph = run(succeed, on_error="stop")
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        hooks = _RunHooks(
            sandbox,
            run_id=success_id,
            actor={"id": "usr_system", "name": "System"},
            started_at="2026-10-22T00:00:00Z",
            user=user,
            schedule={"schedule_id": None, "name": "", "scheduled_for": "2026-10-22T00:00:00Z"},
            target="draft",
            channel_id="chn_preview",
            run_version=None,
        )
        outcome = execute(
            success_graph,
            "batch",
            [batch_read.NODE_TYPE, _type("fake", succeed)],
            _RESOLVER,
            hooks,
        )
        assert outcome.status == "succeeded"
        assert sandbox.evaluate("len(self.step.output.rows)") == 120
    stored = {item.node_id: item for item in get_run_store().list_executions(success_id)}
    assert stored["step"].preview_only is True
    assert stored["step"].preview_totals == {"rows": 120, "tags": 2}
    assert stored["step"].output["rows"] == list(range(100))
    assert stored["step"].output["tags"] == ["a", "b"]
    assert stored["step"].output_bytes == output_size({"rows": rows, "tags": tags})
    assert (stored["step"].container_seq, stored["step"].round) == (stored["batch"].seq, 0)
    assert stored["batch"].preview_only is False
    assert "iterations" not in stored["batch"].output

    failed_id, failed_graph = run(fail, on_error="stop")
    quiet = _PreviewSandbox()
    hooks = _RunHooks(
        quiet,
        run_id=failed_id,
        actor={"id": "usr_system", "name": "System"},
        started_at="2026-10-22T00:00:00Z",
        user=user,
        schedule={"schedule_id": None, "name": "", "scheduled_for": "2026-10-22T00:00:00Z"},
        target="draft",
        channel_id="chn_preview",
        run_version=None,
    )
    outcome = execute(
        failed_graph,
        "batch",
        [batch_read.NODE_TYPE, _type("fake", fail)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "failed"
    failed = {item.node_id: item for item in get_run_store().list_executions(failed_id)}
    assert failed["step"].preview_only is False
    assert failed["step"].preview_totals == {}
    assert failed["step"].output["rows"] is rows
    assert len(failed["step"].output["rows"]) == 120
    assert failed["batch"].error_detail == {"index": 0}


def test_dynamic_set_fields_and_downstream_code_still_succeed() -> None:
    from backend.channel.nodes import list_node_types

    types = [
        item
        for item in list_node_types()
        if item.type_id in {"trigger.manual", "transform.set_fields", "transform.code"}
    ]
    graph = {
        "nodes": [
            {
                "id": "nd_start",
                "type": "trigger.manual",
                "name": "Start",
                "ref": "start",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_fields",
                "type": "transform.set_fields",
                "name": "Fields",
                "ref": "fields",
                "position": {"x": 0, "y": 1},
                "config": {
                    "fields": [
                        {"name": "label", "value": '"ok"'},
                        {"name": "expr", "value": "{{ 1 + 1 }}"},
                    ]
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_code",
                "type": "transform.code",
                "name": "Code",
                "ref": "code",
                "position": {"x": 0, "y": 2},
                "config": {"code": "return {'ok': True}"},
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [_edge("nd_start", "nd_fields"), _edge("nd_fields", "nd_code")],
        "settings": {},
    }
    hooks = FakeHooks(run_code=lambda source, timeout: {"ok": True})
    outcome = execute(graph, "nd_start", types, _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["nd_start", "nd_fields", "nd_code"]
    assert hooks.outputs["nd_fields"] == {"label": "ok", "expr": "1 + 1"}
    assert hooks.outputs["nd_code"] == {"ok": True}


def test_empty_for_still_succeeds_when_current_is_typed() -> None:
    from backend.channel.nodes import list_node_types

    rows = {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code"],
                    "properties": {"code": {"type": "string"}},
                },
            }
        },
    }

    def source_refine(config: dict, upstream: dict, resolver: object) -> dict:
        del config, upstream, resolver
        return {"main": rows}

    def source_run(node: dict, hooks: EngineHooks) -> NodeResult:
        del node, hooks
        return NodeResult(status="succeeded", output={"rows": []})

    source = NodeType(
        type_id="test.source",
        family="test",
        label="Source",
        summary="Publishes an empty typed list.",
        description="Test source. Its refine names the row fields.",
        trigger=True,
        inputs=(),
        outputs=(PortSpec("main", "Rows."),),
        config_schema={"type": "object"},
        execute=source_run,
        refine=source_refine,
        output_view=OutputView(kind="rows", rows="rows"),
    )
    loop = next(item for item in list_node_types() if item.type_id == "volume.for")
    fields = next(item for item in list_node_types() if item.type_id == "transform.set_fields")
    tail = _node("tail", 2, type_id="transform.set_fields")
    tail["config"] = {
        "fields": [{"name": "current", "value": "{{ self.walk.output.current }}"}]
    }
    graph = {
        "nodes": [
            _node("src", 0, type_id="test.source"),
            {
                **_node("walk", 1, type_id="volume.for"),
                "config": {"items": "{{ self.src.output.rows }}"},
            },
            tail,
        ],
        "edges": [_edge("src", "walk"), _edge("walk", "tail", "done")],
        "settings": {},
    }

    def evaluate(expression: str) -> object:
        if expression == "self.src.output.rows":
            return []
        if expression == "self.walk.output.current":
            return None
        raise AssertionError(expression)

    hooks = FakeHooks(evaluate=evaluate)
    outcome = execute(graph, "src", [source, loop, fields], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.outputs["tail"] == {"current": None}


class _PreviewSandbox:
    def put_output(self, *, ref: str, name: str, output: object) -> None:
        del ref, name, output

    def drop_outputs(self, refs: list[str]) -> None:
        del refs

    def evaluate(self, expression: str) -> object:
        raise AssertionError(expression)

    def run_code(self, source: str, timeout_sec: float) -> object:
        raise AssertionError(source)
