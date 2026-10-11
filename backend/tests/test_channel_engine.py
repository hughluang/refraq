"""Pure control-flow engine."""

from __future__ import annotations

from backend.channel.engine import EngineHooks, NodeResult, execute


class RecordingHooks:
    def __init__(self) -> None:
        self.order: list[str] = []
        self.outputs: dict[str, object] = {}
        self.cancel_after: str | None = None

    def cancelled(self) -> bool:
        return bool(self.cancel_after and self.cancel_after in self.order)

    def on_start(self, node: dict) -> int:
        self.order.append(str(node["id"]))
        return len(self.order)

    def on_finish(self, seq: int, node: dict, result: NodeResult) -> None:
        del seq, node, result

    def on_output(self, node: dict, output: object) -> None:
        self.outputs[str(node["id"])] = output

    def evaluate(self, expression: str) -> object:
        return expression


def _node(node_id: str, y: float, x: float = 0) -> dict:
    return {
        "id": node_id,
        "type": "fake",
        "name": node_id,
        "ref": node_id,
        "position": {"x": x, "y": y},
        "config": {},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"{source}-{target}",
        "source": {"node_id": source, "port": "main"},
        "target": {"node_id": target, "port": "main"},
    }


def _ok(node: dict, hooks: EngineHooks) -> NodeResult:
    del hooks
    return NodeResult(status="succeeded", output={"id": node["id"]})


def test_branch_finishes_before_the_next_sibling() -> None:
    graph = {
        "nodes": [_node("a", 0), _node("b", 1), _node("c", 2), _node("d", 0)],
        "edges": [_edge("a", "b"), _edge("a", "c"), _edge("b", "d")],
        "settings": {},
    }
    hooks = RecordingHooks()
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
    hooks = RecordingHooks()
    outcome = execute(graph, "a", {"fake": fail}, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "b"
    assert hooks.order == ["a", "b"]


def test_cancel_between_nodes() -> None:
    graph = {
        "nodes": [_node("a", 0), _node("b", 1)],
        "edges": [_edge("a", "b")],
        "settings": {},
    }
    hooks = RecordingHooks()
    hooks.cancel_after = "a"
    outcome = execute(graph, "a", {"fake": _ok}, hooks)
    assert outcome.status == "cancelled"
    assert hooks.order == ["a"]
