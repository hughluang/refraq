"""Until container: validation's neighbor is the engine, asserted through execute."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from backend.channel.engine import execute
from backend.channel.nodes.spec import EngineHooks, NodeResult, NodeType, OutputView, PortSpec
from backend.channel.nodes.volume.until import NODE_TYPE as UNTIL
from backend.tests.channel_hooks_fake import FakeHooks


class _Resolver:
    def entity_head(self, entity_id: str) -> None:
        del entity_id
        return None

    def channel_exists(self, channel_id: str) -> bool:
        del channel_id
        return False

    def published_trigger_type(self, channel_id: str) -> str | None:
        del channel_id
        return None

    def source_exists(self, source_id: str) -> bool:
        del source_id
        return False


_RESOLVER = _Resolver()


class _Attr(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return _Attr((key, _wrap(item)) for key, item in value.items())
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


class _OutputView:
    def __init__(self, output: Any) -> None:
        self.output = _wrap(output)


class _SelfView:
    def __init__(self, outputs: dict[str, Any]) -> None:
        self._outputs = outputs

    def __getattr__(self, name: str) -> _OutputView:
        if name not in self._outputs:
            raise AttributeError(name)
        return _OutputView(self._outputs[name])


class RecordingHooks(FakeHooks):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.finished: list[tuple[str, NodeResult]] = []
        self.rounds: list[tuple[int, int, Any]] = []
        self.conditions: list[tuple[int, Any, list[str], str | None]] = []

    def on_finish(self, seq: int, node: dict, result: NodeResult) -> None:
        super().on_finish(seq, node, result)
        self.finished.append((str(node["id"]), result))

    def on_round(self, seq: int, index: int, step: Any) -> None:
        self.rounds.append((seq, index, step))

    def note_round_template(self, seq: int, index: int, path: str, entry: Any) -> None:
        del seq, path
        hold = [status for node_id, status in self.statuses if node_id == "hold"]
        self.conditions.append((index, entry, list(self.order), hold[-1] if hold else None))

    def drop_outputs(self, refs: list[str]) -> None:
        super().drop_outputs(refs)
        for ref in refs:
            self.outputs.pop(ref, None)

    def evaluate(self, expression: str) -> Any:
        if self._evaluate is not None:
            return self._evaluate(expression)
        return eval(  # noqa: S307 - test expressions name nodes the body just ran
            expression,
            {"__builtins__": {}},
            {"self": _SelfView(self.outputs)},
        )

    def stored(self, node_id: str) -> Any:
        found = [result.output for item_id, result in self.finished if item_id == node_id]
        return found[-1]


def _type(type_id: str, run: Callable[..., NodeResult]) -> NodeType:
    return NodeType(
        type_id=type_id,
        family="test",
        label=type_id,
        summary="Test node.",
        description="Test node. Used only by the Until engine suite.",
        trigger=False,
        inputs=(PortSpec("main", "Input."),),
        outputs=(PortSpec("main", "Output."),),
        config_schema={"type": "object"},
        execute=run,
        output_view=OutputView(kind="record"),
    )


def _node(
    node_id: str,
    y: float,
    type_id: str = "fake",
    *,
    parent: str | None = None,
    on_error: str = "stop",
) -> dict:
    node = {
        "id": node_id,
        "type": type_id,
        "name": node_id,
        "ref": node_id,
        "position": {"x": 0, "y": y},
        "config": {},
        "on_error": on_error,
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


def _hold(condition: str, cap: int, node_id: str = "hold", y: float = 0) -> dict:
    node = _node(node_id, y, "volume.until")
    node["config"] = {"until": condition, "max_iterations": cap}
    return node


def test_condition_true_on_round_zero_runs_the_body_once_then_done() -> None:
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        seen.append(dict(hooks.outputs["hold"]))
        return NodeResult(status="succeeded", output={"n": 1})

    graph = {
        "nodes": [_hold("true", 3), _node("step", 1, parent="hold"), _node("after", 2)],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded"
    assert outcome.outcome == "completed"
    assert hooks.order == ["hold", "step", "after"]
    assert seen == [{"previous": None, "index": 0}]
    assert hooks.stored("hold") == {
        "index": 0,
        "count": 1,
        "last": {"step": {"n": 1}},
    }
    assert "previous" not in hooks.stored("hold")
    assert hooks.rounds == [(1, 0, {"index": 0})]


def test_a_later_round_reads_the_previous_body_and_done_includes_that_round() -> None:
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["hold"]
        seen.append({"previous": current["previous"], "index": current["index"]})
        return NodeResult(status="succeeded", output={"n": current["index"]})

    graph = {
        "nodes": [
            _hold("{{ self.step.output.n == 1 }}", 5),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["hold", "step", "step", "after"]
    assert seen == [
        {"previous": None, "index": 0},
        {"previous": {"step": {"n": 0}}, "index": 1},
    ]
    assert hooks.stored("hold") == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert "previous" not in hooks.stored("hold")
    assert hooks.rounds == [(1, 0, {"index": 0}), (1, 1, {"index": 1})]


def test_the_condition_is_on_the_round_before_the_next_body_and_before_until_finishes() -> None:
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["hold"]
        if current["index"] == 1:
            seen.append(list(recording.conditions))
            seen.append([node_id for node_id, _result in recording.finished])
        return NodeResult(status="succeeded", output={"n": current["index"]})

    graph = {
        "nodes": [
            _hold("{{ self.step.output.n == 1 }}", 5),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    recording = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, recording)
    assert outcome.status == "succeeded", outcome.error_message
    assert seen[0] == [(0, {"value": False}, ["hold", "step"], "running")]
    assert "hold" not in seen[1]
    assert recording.conditions == [
        (0, {"value": False}, ["hold", "step"], "running"),
        (1, {"value": True}, ["hold", "step", "step"], "running"),
    ]


def test_a_condition_render_error_is_recorded_on_that_round() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": 1})

    def fail(expression: str) -> Any:
        del expression
        raise RuntimeError("bad condition")

    graph = {
        "nodes": [_hold("{{ flag }}", 3), _node("step", 1, parent="hold")],
        "edges": [_edge("hold", "step", "each")],
        "settings": {},
    }
    hooks = RecordingHooks(evaluate=fail)
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_NODE_FAILED"
    assert hooks.conditions == [
        (
            0,
            {"error": {"code": "CHANNEL_NODE_FAILED", "message": "bad condition"}},
            ["hold", "step"],
            "running",
        )
    ]
    assert hooks.rounds == [(1, 0, {"index": 0})]


def test_the_last_allowed_round_succeeds_when_the_condition_becomes_true() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": hooks.outputs["hold"]["index"]})

    graph = {
        "nodes": [
            _hold("{{ self.step.output.n == 1 }}", 2),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["hold", "step", "step", "after"]
    assert hooks.stored("hold")["index"] == 1
    assert hooks.stored("hold")["count"] == 2


def test_cap_exhausted_while_false_stores_the_rounds_and_skips_done() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": hooks.outputs["hold"]["index"]})

    graph = {
        "nodes": [
            _hold("false", 2),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_UNTIL_MAX_ITERATIONS"
    assert outcome.error_message == (
        "Until reached max_iterations before its condition became true."
    )
    assert outcome.failed_node_id == "hold"
    assert hooks.order == ["hold", "step", "step"]
    assert "after" not in hooks.order
    assert hooks.stored("hold") == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert hooks.rounds == [(1, 0, {"index": 0}), (1, 1, {"index": 1})]
    assert [entry for _index, entry, _order, _status in hooks.conditions] == [
        {"value": False},
        {"value": False},
    ]


def test_rounds_past_the_volume_cap_succeed_and_done_reads_last(
    monkeypatch,
) -> None:
    from backend.channel.variables import value_size

    blob = "x" * 30
    one_round = [{"step": {"n": 0, "blob": blob}}]
    combined = [one_round[0], {"step": {"n": 1, "blob": blob}}]
    cap = value_size(one_round)
    assert value_size(combined) > cap
    monkeypatch.setattr(
        "backend.channel.iteration_volume.ITERATION_VOLUME_MAX_BYTES",
        cap,
    )
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] == "after":
            held = hooks.outputs["hold"]
            seen.append({"last": held["last"], "count": held["count"]})
            return NodeResult(status="succeeded", output={"id": node["id"]})
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(
            status="succeeded",
            output={"n": hooks.outputs["hold"]["index"], "blob": blob},
        )

    graph = {
        "nodes": [
            _hold("{{ self.step.output.n == 1 }}", 3),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert outcome.error_code != "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert hooks.order == ["hold", "step", "step", "after"]
    assert hooks.stored("hold") == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1, "blob": blob}},
    }
    assert seen == [{"last": {"step": {"n": 1, "blob": blob}}, "count": 2}]
    assert [index for index, _entry, _order, _status in hooks.conditions] == [0, 1]


def test_a_body_stop_skips_done_and_keeps_the_earlier_round() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        if hooks.outputs["hold"]["index"] == 0:
            return NodeResult(status="succeeded", output={"kept": True})
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="nope",
        )

    graph = {
        "nodes": [
            _hold("false", 3),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "step"
    assert hooks.order == ["hold", "step", "step"]
    assert "after" not in hooks.order
    step_results = [result for node_id, result in hooks.finished if node_id == "step"]
    assert step_results[0].status == "succeeded"
    assert step_results[0].output == {"kept": True}
    assert step_results[1].status == "failed"
    assert [index for index, _entry, _order, _status in hooks.conditions] == [0]
    hold_stop = [result for node_id, result in hooks.finished if node_id == "hold"][-1]
    assert hold_stop.status == "failed"
    assert hold_stop.error_code == "CHANNEL_LOOP_BODY_STOPPED"
    assert hold_stop.error_message == "A loop body node stopped the run."
    assert hold_stop.error_detail == {"index": 1, "node_id": "step"}
    assert outcome.error_code == "CHANNEL_NODE_FAILED"
    assert outcome.error_message == "nope"


def test_continue_and_error_output_keep_their_meanings() -> None:
    def fail(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="nope",
        )

    continued = {
        "nodes": [
            _hold("true", 1),
            _node("step", 1, parent="hold", on_error="continue"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(continued, "hold", [UNTIL, _type("fake", fail)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["hold", "step", "after"]
    assert hooks.stored("hold")["last"] == {"step": None}

    fallible = NodeType(
        type_id="fake",
        family="test",
        label="fake",
        summary="Test node.",
        description="Test node. Declares an error output for error_output.",
        trigger=False,
        inputs=(PortSpec("main", "Input."),),
        outputs=(
            PortSpec("main", "Output."),
            PortSpec("error", "Taken when on_error is error_output."),
        ),
        config_schema={"type": "object"},
        execute=fail,
        output_view=OutputView(kind="record"),
    )
    routed = {
        "nodes": [
            _hold("true", 1),
            _node("step", 1, parent="hold", on_error="error_output"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    routed_hooks = RecordingHooks()
    routed_outcome = execute(routed, "hold", [UNTIL, fallible], _RESOLVER, routed_hooks)
    assert routed_outcome.status == "succeeded", routed_outcome.error_message
    assert routed_hooks.order == ["hold", "step", "after"]
    assert routed_hooks.stored("hold")["last"] == {
        "step": {"code": "CHANNEL_NODE_FAILED", "message": "nope", "detail": None}
    }


def test_a_nested_until_previous_is_its_own_prior_round() -> None:
    for_type = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["inner"]
        seen.append(current["previous"])
        return NodeResult(status="succeeded", output={"n": current["index"]})

    outer = _node("outer", 0, "volume.for")
    outer["config"] = {"items": '["K"]'}
    inner = _hold("{{ self.step.output.n == 1 }}", 3, "inner", 1)
    inner["parent"] = "outer"
    graph = {
        "nodes": [outer, inner, _node("step", 2, parent="inner")],
        "edges": [
            _edge("outer", "inner", "each"),
            _edge("inner", "step", "each"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "outer", [for_type, UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert seen == [None, {"step": {"n": 0}}]
    assert hooks.stored("outer")["current"] == "K"
    assert hooks.stored("outer")["iterations"] == [
        {
            "inner": {
                "index": 1,
                "count": 2,
                "last": {"step": {"n": 1}},
            }
        }
    ]
    assert "iterations" not in hooks.stored("inner")


def test_an_empty_round_still_evaluates_until_and_the_cap() -> None:
    stopped = {
        "nodes": [_hold("true", 4), _node("after", 1)],
        "edges": [_edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(stopped, "hold", [UNTIL, _type("fake", _idle)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["hold", "after"]
    assert hooks.stored("hold") == {"index": 0, "count": 1, "last": {}}
    assert hooks.rounds == [(1, 0, {"index": 0})]

    exhausted = {
        "nodes": [_hold("false", 2), _node("after", 1)],
        "edges": [_edge("hold", "after", "done")],
        "settings": {},
    }
    again = RecordingHooks()
    failed = execute(exhausted, "hold", [UNTIL, _type("fake", _idle)], _RESOLVER, again)
    assert failed.status == "failed"
    assert failed.error_code == "CHANNEL_UNTIL_MAX_ITERATIONS"
    assert again.order == ["hold"]
    assert again.stored("hold") == {"index": 1, "count": 2, "last": {}}
    assert again.rounds == [(1, 0, {"index": 0}), (1, 1, {"index": 1})]


def test_previous_omits_a_body_node_that_did_not_run() -> None:
    if_type = importlib.import_module("backend.channel.nodes.transform.if").NODE_TYPE
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "live":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["hold"]
        seen.append(current["previous"])
        return NodeResult(status="succeeded", output={"n": current["index"]})

    gate = _node("gate", 1, "transform.if", parent="hold")
    gate["config"] = {"condition": "true"}
    graph = {
        "nodes": [
            _hold("{{ self.live.output.n == 1 }}", 3),
            gate,
            _node("live", 2, parent="hold"),
            _node("dead", 3, parent="hold"),
            _node("after", 4),
        ],
        "edges": [
            _edge("hold", "gate", "each"),
            _edge("gate", "live", "true"),
            _edge("gate", "dead", "false"),
            _edge("hold", "after", "done"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(
        graph,
        "hold",
        [UNTIL, if_type, _type("fake", step)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded", outcome.error_message
    assert "dead" not in hooks.order
    assert seen[0] is None
    assert seen[1] == {"gate": {"value": True}, "live": {"n": 0}}
    assert "dead" not in seen[1]
    assert list(hooks.stored("hold")["last"]) == ["gate", "live"]
    assert hooks.stored("hold")["last"] == {"gate": {"value": True}, "live": {"n": 1}}
    assert "dead" not in hooks.stored("hold")["last"]
    assert "iterations" not in hooks.stored("hold")


def test_a_stored_until_round_keeps_index_and_records_the_condition() -> None:
    import uuid

    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.run_store import ChannelRunRecord, get_run_store
    from backend.channel.sandbox import SandboxSession
    from backend.channel.template_preview import node_sample
    from backend.core.time import utc_now

    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.evaluate("self.hold.output")
        if current["index"] == 1:
            store = get_run_store()
            hold = next(item for item in store.list_executions(job_id) if item.node_id == "hold")
            earlier = store.get_round(job_id, hold.seq, 0)
            seen.append(
                {
                    "status": hold.status,
                    "input": hold.input,
                    "step": None if earlier is None else earlier.step,
                }
            )
        return NodeResult(status="succeeded", output={"n": current["index"]})

    graph = {
        "nodes": [
            _hold("{{ self.step.output.n == 1 }}", 3),
            _node("step", 1, parent="hold"),
            _node("after", 2),
        ],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    user = UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )
    store = get_run_store()
    store.insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id="chn_until",
            target="draft",
            version=None,
            draft_revision=1,
            graph=graph,
            trigger_node_id="hold",
            ignore_checkpoints=False,
            outcome=None,
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=utc_now(),
        )
    )
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        hooks = _RunHooks(
            sandbox,
            run_id=job_id,
            actor={"id": "usr_system", "name": "System"},
            started_at="2026-10-26T00:00:00Z",
            user=user,
            schedule={"schedule_id": None, "name": "", "scheduled_for": "2026-10-26T00:00:00Z"},
            target="draft",
            channel_id="chn_until",
            run_version=None,
        )
        outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
        assert outcome.status == "succeeded", outcome.error_message
        assert "previous" not in sandbox.evaluate("self.hold.output")
    assert seen == [
        {
            "status": "running",
            "input": None,
            "step": {"index": 0, "until": {"value": False}},
        }
    ]
    stored = {item.node_id: item for item in store.list_executions(job_id)}
    assert stored["hold"].output == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert "until" not in (stored["hold"].input or {})
    rounds, total = store.query_rounds(job_id, stored["hold"].seq, limit=10, offset=0)
    assert total == 2
    assert [item.step for item in rounds] == [
        {"index": 0, "until": {"value": False}},
        {"index": 1, "until": {"value": True}},
    ]
    assert "previous" not in rounds[0].step
    first = node_sample(
        channel_id="chn_until",
        job_id=job_id,
        graph=graph,
        node_id="hold",
        container_round=0,
    )
    second = node_sample(
        channel_id="chn_until",
        job_id=job_id,
        graph=graph,
        node_id="hold",
        container_round=1,
    )
    assert first["node"]["input"]["until"] == {"value": False}
    assert second["node"]["input"]["until"] == {"value": True}
    assert "until" not in (store.get_execution(job_id, stored["hold"].seq).input or {})
    steps = [item for item in store.list_executions(job_id) if item.node_id == "step"]
    assert [(item.round, item.output) for item in steps] == [(0, {"n": 0}), (1, {"n": 1})]


class _Rounds:
    """Container Body stand-in. It returns scripted round outputs and conditions."""

    def __init__(self, outputs: list[dict[str, Any]], conditions: list[Any]) -> None:
        self.outputs = outputs
        self.conditions = conditions
        self.steps: list[Any] = []
        self.records: list[Any] = []
        self.templates: list[tuple[str, dict[str, Any]]] = []

    def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
        self.steps.append(step)
        self.records.append(record)
        return self.outputs[len(self.steps) - 1]

    def evaluate_round_template(
        self, path: str, schema: Mapping[str, Any]
    ) -> tuple[Any, NodeResult | None]:
        self.templates.append((path, dict(schema)))
        item = self.conditions[len(self.templates) - 1]
        if isinstance(item, NodeResult):
            return None, item
        return item, None


def _until_node(cap: object) -> dict[str, Any]:
    return {"id": "hold", "config": {"until": "true", "max_iterations": cap}}


def test_until_run_stops_when_the_condition_is_true() -> None:
    body = _Rounds([{"step": {"n": 1}}], [True])
    result = UNTIL.container.run(_until_node(3), FakeHooks(), body)
    assert result.status == "succeeded"
    assert result.ports == frozenset({"done"})
    assert result.output == {
        "index": 0,
        "count": 1,
        "last": {"step": {"n": 1}},
    }
    assert result.output["last"] is body.outputs[0]
    assert "previous" not in result.output
    assert body.steps == [{"previous": None, "index": 0}]
    assert body.records == [{"index": 0}]
    assert body.templates == [("until", {"type": "boolean"})]


def test_until_run_stores_an_empty_last_when_no_body_node_ran() -> None:
    body = _Rounds([{}], [True])
    result = UNTIL.container.run(_until_node(2), FakeHooks(), body)
    assert result.status == "succeeded"
    assert result.output == {"index": 0, "count": 1, "last": {}}
    assert result.output["last"] is body.outputs[0]


def test_until_run_fails_when_the_cap_is_reached_while_false() -> None:
    body = _Rounds([{"step": {"n": 0}}, {"step": {"n": 1}}], [False, False])
    result = UNTIL.container.run(_until_node(2), FakeHooks(), body)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_UNTIL_MAX_ITERATIONS"
    assert result.error_message == (
        "Until reached max_iterations before its condition became true."
    )
    assert result.output == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert result.output["last"] is body.outputs[1]
    assert [step["index"] for step in body.steps] == [0, 1]


def test_until_run_passes_the_previous_round_output() -> None:
    body = _Rounds([{"step": {"n": 0}}, {"step": {"n": 1}}], [False, True])
    result = UNTIL.container.run(_until_node(5), FakeHooks(), body)
    assert result.status == "succeeded"
    assert body.steps[0]["previous"] is None
    assert body.steps[1]["previous"] is body.outputs[0]
    assert body.records == [{"index": 0}, {"index": 1}]
    assert result.output == {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert result.output["last"] is body.outputs[1]


def test_until_run_returns_a_condition_error() -> None:
    error = NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message="bad condition",
        error_detail={"expression": "{{ flag }}"},
    )
    body = _Rounds([{"step": {"n": 1}}], [error])
    result = UNTIL.container.run(_until_node(3), FakeHooks(), body)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "bad condition"
    assert result.error_detail == {"expression": "{{ flag }}"}
    assert result.output is None
    assert len(body.steps) == 1
    assert len(body.templates) == 1


def test_until_run_keeps_the_last_round_past_the_volume_cap(monkeypatch: Any) -> None:
    from backend.channel.variables import value_size

    first = {"step": {"blob": "a" * 30}}
    second = {"step": {"blob": "b" * 30}}
    cap = value_size([first])
    assert value_size([first, second]) > cap
    monkeypatch.setattr(
        "backend.channel.iteration_volume.ITERATION_VOLUME_MAX_BYTES",
        cap,
    )
    body = _Rounds([first, second], [False, True])
    result = UNTIL.container.run(_until_node(3), FakeHooks(), body)
    assert result.status == "succeeded"
    assert result.error_code is None
    assert result.ports == frozenset({"done"})
    assert result.output == {"index": 1, "count": 2, "last": second}
    assert result.output["last"] is second
    assert body.steps[1]["previous"] is first
    assert body.templates == [("until", {"type": "boolean"}), ("until", {"type": "boolean"})]


def test_refined_done_schema_names_last_and_a_saved_until_validates() -> None:
    from backend.channel.graph import validate
    from backend.tests.test_channel_graph import FakeResolver, _edge, _graph, _node

    refined = UNTIL.refine({"until": "true", "max_iterations": 1}, {}, None)
    assert refined["each"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["previous", "index"],
        "properties": {
            "previous": {"type": ["object", "null"]},
            "index": {"type": "integer"},
        },
    }
    last = refined["done"]["properties"]["last"]
    assert refined["done"] == {
        "type": "object",
        "additionalProperties": False,
        "required": ["index", "count", "last"],
        "properties": {
            "index": {"type": "integer"},
            "count": {"type": "integer"},
            "last": {"type": ["object", "null"]},
        },
    }
    assert last == refined["each"]["properties"]["previous"]
    assert "properties" not in last
    assert UNTIL.output_view == OutputView(kind="container", metrics=("count",), item="index")
    assert UNTIL.type_version == 1
    assert set(UNTIL.config_schema["properties"]) == {"until", "max_iterations"}
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_hold",
                "volume.until",
                "Hold",
                {"until": "true", "max_iterations": 1},
            ),
        ],
        [_edge("ed_in", "nd_trigger", "nd_hold")],
    )
    assert [item for item in validate(graph, FakeResolver()) if item.severity == "error"] == []


def test_until_run_rejects_a_max_iterations_outside_the_limit() -> None:
    body = _Rounds([], [])
    for cap in (True, False, 0, 100_001, "2", None):
        result = UNTIL.container.run(_until_node(cap), FakeHooks(), body)
        assert result.status == "failed"
        assert result.error_code == "CHANNEL_NODE_CONFIG_INVALID"
        assert result.error_message == (
            "max_iterations must be an integer from 1 through 100000"
        )
    assert body.steps == []


def test_until_cap_with_retry_runs_the_rounds_as_two_executions() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": hooks.outputs["hold"]["index"]})

    hold = _hold("false", 2)
    hold["retry"] = {"max_tries": 2, "wait_sec": 0}
    graph = {
        "nodes": [hold, _node("step", 1, parent="hold"), _node("after", 2)],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.error_code == "CHANNEL_UNTIL_MAX_ITERATIONS"
    assert outcome.failed_node_id == "hold"
    assert hooks.order == ["hold", "step", "step", "hold", "step", "step"]
    assert "after" not in hooks.order
    assert [node_id for node_id, _result in hooks.finished if node_id == "hold"] == [
        "hold",
        "hold",
    ]
    assert hooks.rounds == [
        (1, 0, {"index": 0}),
        (1, 1, {"index": 1}),
        (4, 0, {"index": 0}),
        (4, 1, {"index": 1}),
    ]


def test_until_cap_with_continue_runs_done_with_an_empty_output() -> None:
    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": 0})

    hold = _hold("false", 1)
    hold["on_error"] = "continue"
    graph = {
        "nodes": [hold, _node("step", 1, parent="hold"), _node("after", 2)],
        "edges": [_edge("hold", "step", "each"), _edge("hold", "after", "done")],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "hold", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["hold", "step", "after"]
    assert hooks.stored("hold") is None
    finished = [result for node_id, result in hooks.finished if node_id == "hold"]
    assert finished[-1].status == "failed"
    assert finished[-1].output is None
    assert finished[-1].error_code == "CHANNEL_UNTIL_MAX_ITERATIONS"


def test_a_run_variable_holds_the_total_of_every_round() -> None:
    variable = importlib.import_module("backend.channel.nodes.state.variable").NODE_TYPE
    seed = _node("seed", -1, "state.variable")
    seed["config"] = {
        "operation": "set",
        "name": "total",
        "value": "0",
        "scope": "run",
    }
    read = _node("read", 1, "state.variable", parent="hold")
    read["config"] = {"operation": "get", "name": "total", "scope": "run"}
    add = _node("add", 2, "state.variable", parent="hold")
    add["config"] = {
        "operation": "set",
        "name": "total",
        "value": "{{ self.read.output.value + 1 }}",
        "scope": "run",
    }
    after = _node("after", 3, "state.variable")
    after["config"] = {"operation": "get", "name": "total", "scope": "run"}
    graph = {
        "nodes": [
            seed,
            _hold("{{ self.add.output.value == 3 }}", 5),
            read,
            add,
            after,
        ],
        "edges": [
            _edge("seed", "hold"),
            _edge("hold", "read", "each"),
            _edge("read", "add"),
            _edge("hold", "after", "done"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "seed", [UNTIL, variable], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert hooks.order == ["seed", "hold", "read", "add", "read", "add", "read", "add", "after"]
    written = [result.output["value"] for node_id, result in hooks.finished if node_id == "add"]
    assert written == [1, 2, 3]
    assert hooks.stored("after")["value"] == 3
    assert hooks.stored("hold") == {
        "index": 2,
        "count": 3,
        "last": {
            "read": {
                "name": "total",
                "found": True,
                "value": 2,
                "applied": False,
                "expires_at": None,
            },
            "add": {
                "name": "total",
                "found": True,
                "value": 3,
                "applied": True,
                "expires_at": None,
            },
        },
    }


def test_an_until_inside_an_until_stores_only_its_own_last_round() -> None:
    seen: list[Any] = []

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        current = hooks.outputs["inner"]
        seen.append(current["previous"])
        return NodeResult(status="succeeded", output={"n": current["index"]})

    outer = _hold("true", 2, "outer")
    inner = _hold("{{ self.step.output.n == 1 }}", 3, "inner", 1)
    inner["parent"] = "outer"
    graph = {
        "nodes": [outer, inner, _node("step", 2, parent="inner")],
        "edges": [
            _edge("outer", "inner", "each"),
            _edge("inner", "step", "each"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "outer", [UNTIL, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert seen == [None, {"step": {"n": 0}}]
    inner_output = {
        "index": 1,
        "count": 2,
        "last": {"step": {"n": 1}},
    }
    assert hooks.stored("inner") == inner_output
    assert hooks.stored("outer") == {
        "index": 0,
        "count": 1,
        "last": {"inner": inner_output},
    }
    assert "iterations" not in hooks.stored("inner")
    assert "iterations" not in hooks.stored("outer")


def test_a_for_inside_an_until_keeps_its_iterations() -> None:
    for_type = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"n": hooks.outputs["walk"]["index"]})

    outer = _hold("true", 2, "outer")
    walk = _node("walk", 1, "volume.for", parent="outer")
    walk["config"] = {"items": '["K", "L"]'}
    graph = {
        "nodes": [outer, walk, _node("step", 2, parent="walk")],
        "edges": [
            _edge("outer", "walk", "each"),
            _edge("walk", "step", "each"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "outer", [UNTIL, for_type, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "succeeded", outcome.error_message
    assert "iterations" not in hooks.stored("outer")
    assert hooks.stored("outer")["last"] == {
        "walk": {
            "current": "L",
            "index": 1,
            "count": 2,
            "iterations": [{"step": {"n": 0}}, {"step": {"n": 1}}],
        }
    }
    assert "last" not in hooks.stored("walk")


def test_a_for_inside_an_until_still_fails_at_the_volume_cap(monkeypatch: Any) -> None:
    from backend.channel.variables import value_size

    for_type = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE
    blob = "x" * 40
    one_round = [{"step": {"blob": blob}}]
    cap = value_size(one_round)
    assert value_size([one_round[0], {"step": {"blob": blob}}]) > cap
    monkeypatch.setattr(
        "backend.channel.iteration_volume.ITERATION_VOLUME_MAX_BYTES",
        cap,
    )

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"blob": blob})

    outer = _hold("true", 2, "outer")
    walk = _node("walk", 1, "volume.for", parent="outer")
    walk["config"] = {"items": '["K", "L"]'}
    graph = {
        "nodes": [outer, walk, _node("step", 2, parent="walk"), _node("after", 3)],
        "edges": [
            _edge("outer", "walk", "each"),
            _edge("walk", "step", "each"),
            _edge("outer", "after", "done"),
        ],
        "settings": {},
    }
    hooks = RecordingHooks()
    outcome = execute(graph, "outer", [UNTIL, for_type, _type("fake", step)], _RESOLVER, hooks)
    assert outcome.status == "failed"
    assert outcome.failed_node_id == "walk"
    assert outcome.error_code == "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert outcome.error_message == (
        "For iteration output exceeds 16 MiB. Read the items in batches."
    )
    assert "after" not in hooks.order
    walk_failure = [result for node_id, result in hooks.finished if node_id == "walk"][-1]
    assert walk_failure.error_code == "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert walk_failure.error_message == (
        "For iteration output exceeds 16 MiB. Read the items in batches."
    )
    outer_failure = [result for node_id, result in hooks.finished if node_id == "outer"][-1]
    assert outer_failure.error_code == "CHANNEL_LOOP_BODY_STOPPED"
    assert "Until iteration" not in (outer_failure.error_message or "")


def test_until_description_names_last_and_a_run_variable() -> None:
    assert "index, count, and last" in UNTIL.description
    assert "A total across rounds belongs in a Run Variable." in UNTIL.description
    assert "and iterations" not in UNTIL.description


def _idle(node: dict, hooks: EngineHooks) -> NodeResult:
    del hooks
    return NodeResult(status="succeeded", output={"id": node["id"]})
