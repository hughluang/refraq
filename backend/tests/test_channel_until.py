"""Until container: validation's neighbor is the engine, asserted through execute."""

from __future__ import annotations

import importlib
from collections.abc import Callable
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

    def note_round_condition(self, seq: int, index: int, entry: Any) -> None:
        del seq
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
        "iterations": [{"step": {"n": 1}}],
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
        "iterations": [{"step": {"n": 0}}, {"step": {"n": 1}}],
    }
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
        "iterations": [{"step": {"n": 0}}, {"step": {"n": 1}}],
    }
    assert hooks.rounds == [(1, 0, {"index": 0}), (1, 1, {"index": 1})]
    assert [entry for _index, entry, _order, _status in hooks.conditions] == [
        {"value": False},
        {"value": False},
    ]


def test_until_fails_when_iteration_output_exceeds_16_mib_and_keeps_the_body(
    monkeypatch,
) -> None:
    from backend.channel.variables import value_size

    blob = "x" * 30
    one_round = [{"step": {"blob": blob}}]
    monkeypatch.setattr(
        "backend.channel.engine.ITERATION_VOLUME_MAX_BYTES",
        value_size(one_round),
    )

    def step(node: dict, hooks: EngineHooks) -> NodeResult:
        del hooks
        if node["id"] != "step":
            return NodeResult(status="succeeded", output={"id": node["id"]})
        return NodeResult(status="succeeded", output={"blob": blob})

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
    assert outcome.error_code == "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert outcome.error_message == "Until iteration output exceeds 16 MiB."
    assert "batch" not in (outcome.error_message or "").lower()
    assert hooks.order == ["hold", "step", "step"]
    assert "after" not in hooks.order
    assert [result.status for node_id, result in hooks.finished if node_id == "step"] == [
        "succeeded",
        "succeeded",
    ]
    assert hooks.stored("hold") is None
    assert [index for index, _entry, _order, _status in hooks.conditions] == [0]


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
    assert hooks.stored("hold")["iterations"] == [{"step": None}]

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
    assert routed_hooks.stored("hold")["iterations"] == [
        {"step": {"code": "CHANNEL_NODE_FAILED", "message": "nope", "detail": None}}
    ]


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
                "iterations": [{"step": {"n": 0}}, {"step": {"n": 1}}],
            }
        }
    ]


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
    assert hooks.stored("hold") == {"index": 0, "count": 1, "iterations": [{}]}
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
    assert again.stored("hold") == {"index": 1, "count": 2, "iterations": [{}, {}]}
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
        "iterations": [{"step": {"n": 0}}, {"step": {"n": 1}}],
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


def _idle(node: dict, hooks: EngineHooks) -> NodeResult:
    del hooks
    return NodeResult(status="succeeded", output={"id": node["id"]})
