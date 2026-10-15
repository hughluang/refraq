"""Editor execution seams that do not need PostgreSQL."""

from __future__ import annotations

from backend.channel.editor import EditorOptions, editor_executors
from backend.channel.engine import EngineHooks, NodeResult, execute
from backend.channel.executors import execute_variable
from backend.channel.reshape import run_for
from backend.channel.variables import get_variable_store


class _Hooks:
    def __init__(self, editor: EditorOptions | None) -> None:
        self.editor = editor
        self.statuses: list[tuple[str, str]] = []

    def cancelled(self) -> bool:
        return False

    def superseded(self) -> bool:
        return False

    def on_start(self, node: dict) -> int:
        self.statuses.append((str(node["id"]), "running"))
        return len(self.statuses)

    def on_finish(self, seq: int, node: dict, result: NodeResult) -> None:
        del node
        node_id, _status = self.statuses[seq - 1]
        self.statuses[seq - 1] = (node_id, result.status)

    def on_output(self, node: dict, output: object) -> None:
        del node, output

    def drop_outputs(self, refs: list[str]) -> None:
        del refs

    def evaluate(self, expression: str) -> object:
        raise AssertionError(expression)


def _called(node: dict, hooks: EngineHooks, seen: list[str]) -> NodeResult:
    del hooks
    seen.append(str(node["id"]))
    return NodeResult(status="succeeded", output={"id": node["id"]})


def _if_graph() -> dict:
    def node(node_id: str, type_id: str, y: int) -> dict:
        return {
            "id": node_id,
            "type": type_id,
            "name": node_id,
            "ref": node_id,
            "position": {"x": 0, "y": y},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }

    return {
        "nodes": [
            node("t", "trigger.manual", 0),
            node("g", "transform.if", 10),
            node("yes", "transform.set_fields", 20),
            node("no", "transform.set_fields", 30),
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"node_id": "t", "port": "main"},
                "target": {"node_id": "g", "port": "main"},
            },
            {
                "id": "e2",
                "source": {"node_id": "g", "port": "true"},
                "target": {"node_id": "yes", "port": "main"},
            },
            {
                "id": "e3",
                "source": {"node_id": "g", "port": "false"},
                "target": {"node_id": "no", "port": "main"},
            },
        ],
    }


def _pin_if(value: bool) -> tuple[list[str], list[tuple[str, str]]]:
    seen: list[str] = []

    def fake(node: dict, hooks: EngineHooks) -> NodeResult:
        return _called(node, hooks, seen)

    hooks = _Hooks(EditorOptions(row_limit=10, pinned={"g": {"value": value}}))
    outcome = execute(
        _if_graph(),
        "t",
        editor_executors(
            {
                "trigger.manual": fake,
                "transform.if": fake,
                "transform.set_fields": fake,
            }
        ),
        hooks,
    )
    assert outcome.status == "succeeded"
    return seen, hooks.statuses


def test_pinned_if_selects_the_live_port() -> None:
    false_seen, false_status = _pin_if(False)
    assert false_seen == ["t", "no"]
    assert ("g", "pinned") in false_status
    assert "yes" not in {node_id for node_id, _status in false_status}

    true_seen, true_status = _pin_if(True)
    assert true_seen == ["t", "yes"]
    assert ("g", "pinned") in true_status
    assert "no" not in {node_id for node_id, _status in true_status}


def _variable(operation: str, **config: object) -> dict:
    return {
        "id": "nd_var",
        "type": "state.variable",
        "config": {"operation": operation, "name": "lease", **config},
    }


def test_variable_writes_are_dry_and_reads_are_real() -> None:
    hooks = _Hooks(EditorOptions(row_limit=100, pinned={}))
    store = get_variable_store()

    written = execute_variable(_variable("set", value='"kept"'), hooks)
    assert written.status == "succeeded"
    assert written.output["applied"] is True
    assert written.output["dry_run"] is True
    assert written.output["value"] == "kept"
    assert store.apply(operation="get", name="lease").found is False

    absent = execute_variable(
        _variable("set_if_absent", name="other", value='"new"'), hooks
    )
    assert absent.output["applied"] is True
    assert absent.output["dry_run"] is True
    assert store.apply(operation="get", name="other").found is False

    store.apply(operation="set", name="lease", value="kept")
    held = execute_variable(_variable("set_if_absent", value='"other"'), hooks)
    assert held.output["applied"] is False
    assert held.output["value"] == "kept"
    assert held.output["dry_run"] is True

    matched = execute_variable(
        _variable("compare_and_set", value='"next"', expected='"kept"'), hooks
    )
    assert matched.output["applied"] is True
    assert matched.output["dry_run"] is True
    missed = execute_variable(
        _variable("compare_and_set", value='"next"', expected='"nope"'), hooks
    )
    assert missed.output["applied"] is False
    assert store.apply(operation="get", name="lease").value == "kept"

    removed = execute_variable(_variable("delete"), hooks)
    assert removed.output["applied"] is True
    assert removed.output["found"] is False
    assert removed.output["dry_run"] is True
    assert store.apply(operation="get", name="lease").value == "kept"

    read = execute_variable(_variable("get"), hooks)
    assert read.output["found"] is True
    assert read.output["value"] == "kept"
    assert "dry_run" not in read.output


def test_editor_for_iterates_at_most_row_limit() -> None:
    node = {"id": "nd_for", "config": {"items": "[1, 2, 3, 4, 5]"}}
    capped = run_for(node, _Hooks(EditorOptions(row_limit=2, pinned={})))
    assert capped.output["count"] == 2
    assert capped.iterations is not None
    assert [step["current"] for step in capped.iterations] == [1, 2]

    full = run_for(node, _Hooks(None))
    assert full.output["count"] == 5
