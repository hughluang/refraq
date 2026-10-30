"""Node execution sequence and container round on the run store."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.channel.run_store import MemoryRunStore

_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)


def test_start_execution_stores_container_seq_and_round() -> None:
    store = MemoryRunStore()
    outside = store.start_execution("job_1", "nd_a")
    assert outside.seq == 1
    assert outside.container_seq is None
    assert outside.round is None
    inside = store.start_execution("job_1", "nd_b", container_seq=1, round=0)
    assert (inside.seq, inside.container_seq, inside.round) == (2, 1, 0)
    again = store.get_execution("job_1", 2)
    assert again is not None
    assert (again.container_seq, again.round) == (1, 0)


def test_set_round_template_writes_the_entry_under_its_path() -> None:
    store = MemoryRunStore()
    store.insert_round(
        "job_1",
        container_seq=1,
        round=0,
        step={"index": 0},
        step_totals={},
    )
    store.set_round_template(
        "job_1",
        container_seq=1,
        round=0,
        path="flag",
        entry={"value": True},
    )
    found = store.get_round("job_1", 1, 0)
    assert found is not None
    assert found.step == {"index": 0, "flag": {"value": True}}
    with pytest.raises(RuntimeError):
        store.set_round_template(
            "job_1",
            container_seq=1,
            round=1,
            path="flag",
            entry={"value": False},
        )


def test_start_execution_assigns_one_past_the_highest_seq() -> None:
    store = MemoryRunStore()
    first = store.start_execution("job_1", "nd_a")
    second = store.start_execution("job_1", "nd_b")
    third = store.start_execution("job_1", "nd_c")
    assert [first.seq, second.seq, third.seq] == [1, 2, 3]
    del store._execs[second.id]
    fourth = store.start_execution("job_1", "nd_d")
    assert fourth.seq == 4
    other = store.start_execution("job_2", "nd_a")
    assert other.seq == 1


def test_success_under_batch_read_stores_the_full_output() -> None:
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.engine import execute
    from backend.channel.nodes.spec import (
        ContainerSpec,
        NodeResult,
        NodeType,
        OutputView,
        PortSpec,
    )
    from backend.channel.run_store import (
        ChannelRunRecord,
        get_run_store,
        output_page,
        output_preview_with_truncated,
        output_size,
    )
    from backend.channel.sandbox import SandboxSession
    from backend.core.time import utc_now

    rows = list(range(120))
    tags = ["a", "b"]
    rounds = {
        "batch": [{"current": 0}],
        "inner": [{"current": 1, "index": 0, "count": 1}],
    }

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1, "total": 1, "batch_size": 1000},
                ports=frozenset({"done"}),
            )
        if node["id"] == "inner":
            return NodeResult(
                status="succeeded",
                output={"current": 1, "index": 0, "count": 1},
                ports=frozenset({"done"}),
            )
        return NodeResult(status="succeeded", output={"rows": rows, "tags": tags})

    def kind(type_id: str) -> NodeType:
        shared = dict(
            type_id=type_id,
            family="test",
            label=type_id,
            summary="Test node.",
            description="Test node.",
            trigger=False,
            inputs=(PortSpec("main", "Input.", coarse_type="object"),),
            outputs=(
                PortSpec("main", "Output.", coarse_type="object"),
                PortSpec("each", "Each round.", coarse_type="object"),
                PortSpec("done", "After the rounds.", coarse_type="object"),
            ),
            config_schema={"type": "object"},
            output_view=OutputView(kind="record"),
        )
        if type_id == "fake":
            return NodeType(**shared, execute=run)
        accumulate = type_id == "volume.for"

        def container_run(node, hooks, body, _accumulate=accumulate):
            result = run(node, hooks)
            collected = [body.run_round(step) for step in rounds[node["id"]]]
            if _accumulate and isinstance(result.output, dict):
                result.output = {**result.output, "iterations": collected}
            return result

        return NodeType(**shared, container=ContainerSpec(run=container_run))

    batch = _graph_node("batch", "volume.batch_read", 0)
    inner = _graph_node("inner", "volume.for", 1, parent="batch")
    step = _graph_node("step", "fake", 2, parent="inner")
    graph = {
        "nodes": [batch, inner, step],
        "edges": [
            _graph_edge("batch", "inner", "each"),
            _graph_edge("inner", "step", "each"),
        ],
        "settings": {},
    }
    job_id = f"job_{uuid.uuid4().hex[:12]}"
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
    user = UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        hooks = _RunHooks(
            sandbox,
            run_id=job_id,
            actor={"id": "usr_system", "name": "System"},
            started_at="2026-10-22T00:00:00Z",
            user=user,
            schedule={
                "schedule_id": None,
                "name": "",
                "scheduled_for": "2026-10-22T00:00:00Z",
            },
            target="draft",
            channel_id="chn_preview",
            run_version=None,
        )
        outcome = execute(
            graph,
            "batch",
            [kind("volume.batch_read"), kind("volume.for"), kind("fake")],
            _resolver(),
            hooks,
        )
        assert outcome.status == "succeeded"
        assert sandbox.evaluate("len(self.step.output.rows)") == 120
        assert sandbox.evaluate("len(self.inner.output.iterations[0].step.rows)") == 120
        full_inner = sandbox.evaluate("self.inner.output")
    assert len(rows) == 120
    stored = {item.node_id: item for item in get_run_store().list_executions(job_id)}
    step_row = stored["step"]
    inner_row = stored["inner"]
    batch_row = stored["batch"]
    assert step_row.preview_only is False
    assert step_row.preview_totals == {}
    assert step_row.output["rows"] is rows
    assert step_row.output["rows"] == list(range(120))
    assert step_row.output["tags"] == ["a", "b"]
    assert step_row.output_bytes == output_size({"rows": rows, "tags": tags})
    assert (step_row.container_seq, step_row.round) == (inner_row.seq, 0)
    assert (inner_row.container_seq, inner_row.round) == (batch_row.seq, 0)
    assert (batch_row.container_seq, batch_row.round) == (None, None)
    assert batch_row.preview_only is False
    assert batch_row.preview_totals == {}
    assert "iterations" not in batch_row.output
    assert inner_row.preview_only is False
    assert inner_row.preview_totals == {}
    assert inner_row.output["iterations"][0]["step"]["rows"] is rows
    assert inner_row.output["iterations"][0]["step"]["rows"] == list(range(120))
    assert inner_row.output_bytes == output_size(full_inner)
    listed, truncated = output_preview_with_truncated(step_row.output)
    assert truncated is True
    assert listed["rows"] == list(range(100))
    assert listed["tags"] == ["a", "b"]
    page = output_page(step_row.output, "rows", limit=50, offset=100)
    assert page == {
        "items": list(range(100, 120)),
        "total": 120,
        "limit": 50,
        "offset": 100,
    }
    inner_listed, inner_truncated = output_preview_with_truncated(inner_row.output)
    assert inner_truncated is True
    assert len(inner_listed["iterations"][0]["step"]["rows"]) == 100
    assert len(inner_row.output["iterations"][0]["step"]["rows"]) == 120


def test_failed_execution_under_batch_read_stores_the_full_output() -> None:
    from backend.channel.nodes.spec import NodeResult
    from backend.channel.run_store import get_run_store

    rows = list(range(120))

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1},
                ports=frozenset({"done"}),
            )
        return NodeResult(
            status="failed",
            output={"rows": rows},
            error_code="CHANNEL_NODE_FAILED",
            error_message="no",
        )

    job_id = _run_preview_graph(run, step_retry=None)
    stored = {item.node_id: item for item in get_run_store().list_executions(job_id)}
    assert stored["step"].preview_only is False
    assert stored["step"].preview_totals == {}
    assert stored["step"].output == {"rows": rows}
    assert stored["step"].output["rows"] is rows
    assert len(rows) == 120


def test_a_failed_retry_and_the_following_success_store_the_full_output() -> None:
    from backend.channel.nodes.spec import NodeResult
    from backend.channel.run_store import get_run_store

    calls = {"n": 0}
    held: list[list[int]] = []

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1},
                ports=frozenset({"done"}),
            )
        calls["n"] += 1
        rows = list(range(120))
        held.append(rows)
        if calls["n"] == 1:
            return NodeResult(
                status="failed",
                output={"rows": rows},
                error_code="CHANNEL_NODE_FAILED",
                error_message="no",
            )
        return NodeResult(status="succeeded", output={"rows": rows})

    job_id = _run_preview_graph(run, step_retry={"max_tries": 2, "wait_sec": 0})
    steps = [
        item
        for item in get_run_store().list_executions(job_id)
        if item.node_id == "step"
    ]
    assert len(steps) == 2
    assert steps[0].status == "failed"
    assert steps[0].preview_only is False
    assert steps[0].output["rows"] is held[0]
    assert len(steps[0].output["rows"]) == 120
    assert steps[1].status == "succeeded"
    assert steps[1].preview_only is False
    assert steps[1].preview_totals == {}
    assert steps[1].output["rows"] is held[1]
    assert len(steps[1].output["rows"]) == 120
    assert len(held[1]) == 120


def test_success_under_batch_read_stores_a_clipped_input_and_the_full_output() -> None:
    import json

    from backend.channel.node_support import render_field
    from backend.channel.nodes.spec import NodeResult
    from backend.channel.run_store import get_run_store

    numbers = list(range(120))

    def run(node: dict, hooks: object) -> NodeResult:
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1},
                ports=frozenset({"done"}),
            )
        rendered, error = render_field(
            hooks, json.dumps(numbers), {"type": "array"}, path="nums"
        )
        assert error is None
        assert rendered == numbers
        return NodeResult(status="succeeded", output={"rows": numbers})

    job_id = _run_preview_graph(run, step_retry=None)
    stored = {item.node_id: item for item in get_run_store().list_executions(job_id)}
    step = stored["step"]
    assert step.preview_only is False
    assert step.output["rows"] is numbers
    assert step.output["rows"] == list(range(120))
    assert step.input["nums"]["value"] == list(range(100))
    assert step.input_totals == {"nums": 120}


def test_note_killed_run_keeps_the_full_output() -> None:
    from backend.channel.run_store import (
        ChannelRunRecord,
        get_run_store,
        note_killed_run,
    )
    from backend.core.time import utc_now

    rows = list(range(120))
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    store = get_run_store()
    store.insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id="chn_preview",
            target="draft",
            version=None,
            draft_revision=1,
            graph={"nodes": [], "edges": [], "settings": {}},
            trigger_node_id="step",
            ignore_checkpoints=False,
            outcome=None,
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=utc_now(),
        )
    )
    running = store.start_execution(job_id, "step", container_seq=2, round=0)
    running.output = {"rows": rows}
    running.output_bytes = 120
    note_killed_run(job_id)
    stored = store.get_execution(job_id, running.seq)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message == "cancelled"
    assert stored.output["rows"] is rows
    assert len(stored.output["rows"]) == 120
    assert stored.preview_only is False
    assert (stored.container_seq, stored.round) == (2, 0)


def test_render_field_keeps_the_last_value_on_one_path() -> None:
    from backend.channel.node_support import (
        InputCapture,
        bind_execution_input,
        render_field,
        reset_execution_input,
    )
    from backend.tests.channel_hooks_fake import FakeHooks

    calls = {"n": 0}

    def evaluate(expression: str) -> int:
        del expression
        calls["n"] += 1
        return calls["n"]

    capture = InputCapture()
    token = bind_execution_input(capture)
    try:
        first, first_error = render_field(
            FakeHooks(evaluate=evaluate), "{{ n }}", {"type": "string"}, path="sql"
        )
        second, second_error = render_field(
            FakeHooks(evaluate=evaluate), "{{ n }}", {"type": "string"}, path="sql"
        )
    finally:
        reset_execution_input(token)
    assert first_error is None and second_error is None
    assert (first, second) == ("1", "2")
    assert capture.fields == {"sql": {"value": "2"}}


def test_identical_template_text_records_each_filter_condition_path() -> None:
    from backend.channel.nodes.transform.filter import NODE_TYPE
    from backend.channel.node_support import (
        InputCapture,
        bind_execution_input,
        reset_execution_input,
    )
    from backend.tests.channel_hooks_fake import FakeHooks

    text = "{{ n }}"
    config = {
        "items": "{{ rows }}",
        "combinator": "all",
        "conditions": [
            {"key": "n", "operator": "eq", "value": text},
            {"key": "n", "operator": "ne", "value": text},
        ],
    }
    calls = {"n": 0}

    def evaluate(expression: str) -> Any:
        if expression == "rows":
            return [{"n": 1}]
        calls["n"] += 1
        return calls["n"]

    capture = InputCapture()
    token = bind_execution_input(capture)
    try:
        NODE_TYPE.execute(
            {"id": "nd_filter", "config": config}, FakeHooks(evaluate=evaluate)
        )
    finally:
        reset_execution_input(token)
    assert capture.fields["conditions.0.value"] == {"value": 1}
    assert capture.fields["conditions.1.value"] == {"value": 2}
    assert capture.fields["items"]["value"] == [{"n": 1}]


def test_recorded_input_paths_exist_on_each_node_config(monkeypatch) -> None:
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()
    from types import SimpleNamespace

    from backend.channel.nodes import list_node_types
    from backend.channel.node_support import (
        InputCapture,
        bind_execution_input,
        reset_execution_input,
    )
    from backend.tests.channel_hooks_fake import FakeHooks

    monkeypatch.setattr(
        "backend.channel.nodes.read.sql.run_channel_sql",
        lambda *args, **kwargs: {"rows": [], "count": 0, "rowcount": 0},
    )
    monkeypatch.setattr(
        "backend.channel.nodes.read.source_query.run_controlled_query",
        lambda **kwargs: SimpleNamespace(columns=["n"], rows=[[1]], truncated=False),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.write.entity.head_target",
        lambda entity_id: SimpleNamespace(attributes=()),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.write.entity.write_reasons",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "backend.channel.nodes.action.email.get_email_account_store",
        lambda: SimpleNamespace(get=lambda account_id: object()),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.action.email.prepare_message",
        lambda *args, **kwargs: ["a@b.c"],
    )
    monkeypatch.setattr(
        "backend.channel.nodes.action.email.deliver",
        lambda *args, **kwargs: SimpleNamespace(ok=True),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.action.webhook.get_webhook_store",
        lambda: SimpleNamespace(get=lambda webhook_id: object()),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.action.webhook.deliver",
        lambda *args, **kwargs: SimpleNamespace(ok=True, status_code=200),
    )
    monkeypatch.setattr(
        "backend.channel.nodes.state.variable.get_variable_store",
        lambda: SimpleNamespace(
            apply=lambda **kwargs: SimpleNamespace(
                name="alpha",
                found=False,
                value=None,
                applied=True,
                expires_at=None,
            )
        ),
    )
    rows = "{{ rows }}"
    same = "{{ n }}"
    samples = {
        "trigger.error": {},
        "trigger.manual": {},
        "trigger.scheduled": {},
        "read.changes": {"entity_id": "ent_1"},
        "read.sql": {"source": {"kind": "entity"}, "sql": "{{ sql }}"},
        "read.source_query": {"source_id": "src_1", "sql": "{{ sql }}"},
        "transform.set_fields": {
            "fields": [
                {"name": "a", "value": same},
                {"name": "b", "value": same},
            ]
        },
        "transform.code": {"code": "1"},
        "transform.if": {"condition": "{{ flag }}"},
        "transform.filter": {
            "items": rows,
            "conditions": [
                {"key": "n", "operator": "eq", "value": same},
                {"key": "n", "operator": "ne", "value": same},
            ],
        },
        "transform.merge": {"mode": "append", "inputs": [rows, rows]},
        "transform.deduplicate": {"items": rows, "keys": ["n"]},
        "volume.for": {"items": "{{ items }}"},
        "volume.batch_read": {"dataset": "{{ dataset }}"},
        "volume.dataset_query": {"source": {"kind": "other"}, "sql": "{{ sql }}"},
        "volume.materialize": {"items": "{{ empty }}"},
        "volume.until": {"until": "{{ flag }}", "max_iterations": 1},
        "state.variable": {
            "operation": "compare_and_set",
            "name": "{{ name }}",
            "value": "{{ value }}",
            "expected": "{{ expected }}",
        },
        "write.entity": {
            "entity_id": "ent_1",
            "mode": "create",
            "source": "{{ source }}",
        },
        "action.email": {
            "email_account_id": "acct",
            "to": "{{ text }}",
            "subject": "{{ text }}",
            "body": "{{ text }}",
        },
        "action.http": {
            "method": "POST",
            "url": "{{ text }}",
            "query": [{"name": "{{ text }}", "value": "{{ text }}"}],
            "headers": [{"name": "X-Test", "value": "{{ text }}"}],
            "body_mode": "json",
            "body": "{{ body }}",
            "content_type": "{{ text }}",
        },
        "action.webhook": {"webhook_id": "hook", "body": "{{ body }}"},
    }
    expected = {
        "trigger.error": set(),
        "trigger.manual": set(),
        "trigger.scheduled": set(),
        "read.changes": set(),
        "read.sql": {"sql"},
        "read.source_query": {"sql"},
        "transform.set_fields": {"fields.0.value", "fields.1.value"},
        "transform.code": set(),
        "transform.if": {"condition"},
        "transform.filter": {"items", "conditions.0.value", "conditions.1.value"},
        "transform.merge": {"inputs.0", "inputs.1"},
        "transform.deduplicate": {"items"},
        "volume.for": {"items"},
        "volume.batch_read": {"dataset"},
        "volume.dataset_query": {"sql"},
        "volume.materialize": {"items"},
        "volume.until": set(),
        "state.variable": {"name", "value", "expected"},
        "write.entity": {"source"},
        "action.email": {"to", "subject", "body"},
        "action.http": {
            "url",
            "query.0.name",
            "query.0.value",
            "headers.0.name",
            "headers.0.value",
            "body",
            "content_type",
        },
        "action.webhook": {"body"},
    }
    values = {
        "rows": [{"n": 1}],
        "empty": [],
        "n": 1,
        "sql": "select 1",
        "flag": True,
        "items": [1],
        "dataset": {
            "dataset_id": "ds_1",
            "columns": [{"name": "n", "type": "integer"}],
            "count": 1,
        },
        "name": "alpha",
        "value": {"ok": True},
        "expected": {"ok": False},
        "source": [{"n": 1}],
        "text": "hello",
        "body": "{}",
    }

    def evaluate(expression: str) -> Any:
        return values[expression]

    types = list_node_types()
    assert {item.type_id for item in types} == set(samples)
    hooks = FakeHooks(evaluate=evaluate, run_code=lambda source, timeout: 1)
    for spec in types:
        config = samples[spec.type_id]
        capture = InputCapture()
        token = bind_execution_input(capture)
        try:
            if spec.execute is not None:
                spec.execute({"id": spec.type_id, "config": config}, hooks)
            elif spec.container is not None:
                spec.container.run(
                    {"id": spec.type_id, "config": config},
                    hooks,
                    _NoRound(),
                )
        finally:
            reset_execution_input(token)
        assert set(capture.fields) == expected[spec.type_id]
        for path in capture.fields:
            assert _config_at(config, path) is not None


class _NoRound:
    """Body that does not render. Round templates stay out of this capture."""

    def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
        del step, record
        return {}

    def evaluate_round_template(self, path: str, schema: Any) -> tuple[Any, None]:
        del path, schema
        return True, None


def _config_at(config: Any, path: str) -> Any:
    current = config
    for segment in path.split("."):
        if isinstance(current, list):
            current = current[int(segment)]
        else:
            current = current[segment]
    return current


def test_batch_round_stores_clipped_rows_and_the_body_reads_every_row(
    monkeypatch,
) -> None:
    from datetime import datetime, timezone

    import backend.channel.nodes.volume.batch_read as batch_read
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.dataset_registry import DatasetRecord, MemoryDatasetStore
    from backend.channel.engine import execute
    from backend.channel.nodes.spec import NodeResult, NodeType, OutputView, PortSpec
    from backend.channel.run_store import ChannelRunRecord, get_run_store
    from backend.channel.sandbox import SandboxSession
    from backend.core.time import utc_now

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    store = MemoryDatasetStore()
    store.save(
        DatasetRecord(
            id="dset",
            job_id=job_id,
            node_id="load",
            seq=1,
            relation='"channel_dataset"."ds_dset"',
            columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
            row_count=120,
            size_bytes=1,
            status="ready",
            created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        )
    )

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict]:
        del relation
        assert after_ord == 0
        assert limit == 1000
        return [{"_ord": index + 1, "n": index} for index in range(120)]

    monkeypatch.setattr(batch_read, "get_dataset_store", lambda: store)
    monkeypatch.setattr(batch_read, "read_keyset_page", page)
    monkeypatch.setattr(batch_read, "any_row_exists", lambda relation: True)

    seen: list[int] = []

    def step(node: dict, hooks: Any) -> NodeResult:
        if node["id"] == "step":
            seen.append(hooks.evaluate("len(self.batch.output.rows)"))
        return NodeResult(status="succeeded", output={"ok": True})

    batch = _graph_node("batch", "volume.batch_read", 0)
    batch["config"] = {
        "dataset": (
            '{"dataset_id":"dset","columns":[{"name":"n","type":"integer"}],"count":120}'
        ),
        "batch_size": 1000,
    }
    body = _graph_node("step", "fake", 1, parent="batch")
    graph = {
        "nodes": [batch, body],
        "edges": [_graph_edge("batch", "step", "each")],
        "settings": {},
    }
    get_run_store().insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id="chn_rounds",
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
    user = UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )
    kind = NodeType(
        type_id="fake",
        family="test",
        label="fake",
        summary="Test node.",
        description="Test node.",
        trigger=False,
        inputs=(PortSpec("main", "Input.", coarse_type="object"),),
        outputs=(PortSpec("main", "Output.", coarse_type="object"),),
        config_schema={"type": "object"},
        execute=step,
        output_view=OutputView(kind="record"),
    )
    with SandboxSession() as sandbox:
        sandbox.set_context(channel={}, run={}, platform={})
        hooks = _RunHooks(
            sandbox,
            run_id=job_id,
            actor={"id": "usr_system", "name": "System"},
            started_at="2026-10-22T00:00:00Z",
            user=user,
            schedule={
                "schedule_id": None,
                "name": "",
                "scheduled_for": "2026-10-22T00:00:00Z",
            },
            target="draft",
            channel_id="chn_rounds",
            run_version=None,
        )
        outcome = execute(
            graph, "batch", [batch_read.NODE_TYPE, kind], _resolver(), hooks
        )
    assert outcome.status == "succeeded"
    assert seen == [120]
    executions = {
        item.node_id: item for item in get_run_store().list_executions(job_id)
    }
    rounds, total = get_run_store().query_rounds(
        job_id, executions["batch"].seq, limit=50, offset=0
    )
    assert total == 1
    assert len(rounds) == 1
    recorded = rounds[0]
    assert recorded.round == 0
    assert recorded.step["index"] == 0
    assert recorded.step["count"] == 1
    assert recorded.step["total"] == 120
    assert [row["n"] for row in recorded.step["rows"]] == list(range(100))
    assert recorded.step_totals == {"rows": 120}
    assert get_run_store().round_status_counts(job_id, executions["batch"].seq) == {
        0: {"succeeded": 1}
    }
    page_rows, page_total = get_run_store().query_rounds(
        job_id, executions["batch"].seq, limit=1, offset=1
    )
    assert page_total == 1
    assert page_rows == []


def _run_preview_graph(run, *, step_retry: dict | None) -> str:
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.engine import execute
    from backend.channel.nodes.spec import ContainerSpec, NodeType, OutputView, PortSpec
    from backend.channel.run_store import ChannelRunRecord, get_run_store
    from backend.core.time import utc_now

    batch = _graph_node("batch", "volume.batch_read", 0)
    step = _graph_node("step", "fake", 1, parent="batch")
    if step_retry is not None:
        step["retry"] = step_retry
    graph = {
        "nodes": [batch, step],
        "edges": [_graph_edge("batch", "step", "each")],
        "settings": {},
    }
    job_id = f"job_{uuid.uuid4().hex[:12]}"
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

    def kind(type_id: str) -> NodeType:
        shared = dict(
            type_id=type_id,
            family="test",
            label=type_id,
            summary="Test node.",
            description="Test node.",
            trigger=False,
            inputs=(PortSpec("main", "Input.", coarse_type="object"),),
            outputs=(
                PortSpec("main", "Output.", coarse_type="object"),
                PortSpec("each", "Each round.", coarse_type="object"),
                PortSpec("done", "After the rounds.", coarse_type="object"),
            ),
            config_schema={"type": "object"},
            output_view=OutputView(kind="record"),
        )
        if type_id == "fake":
            return NodeType(**shared, execute=run)

        def container_run(node, hooks, body):
            result = run(node, hooks)
            body.run_round({"current": 0})
            return result

        return NodeType(**shared, container=ContainerSpec(run=container_run))

    user = UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )
    hooks = _RunHooks(
        _QuietSandbox(),
        run_id=job_id,
        actor={"id": "usr_system", "name": "System"},
        started_at="2026-10-22T00:00:00Z",
        user=user,
        schedule={
            "schedule_id": None,
            "name": "",
            "scheduled_for": "2026-10-22T00:00:00Z",
        },
        target="draft",
        channel_id="chn_preview",
        run_version=None,
    )
    execute(
        graph,
        "batch",
        [kind("volume.batch_read"), kind("fake")],
        _resolver(),
        hooks,
    )
    return job_id


class _QuietSandbox:
    def put_output(self, *, ref: str, name: str, output: object) -> None:
        del ref, name, output

    def drop_outputs(self, refs: list[str]) -> None:
        del refs


def _graph_node(
    node_id: str, type_id: str, y: int, *, parent: str | None = None
) -> dict:
    node = {
        "id": node_id,
        "type": type_id,
        "name": node_id,
        "ref": node_id,
        "position": {"x": 0, "y": y},
        "config": {},
        "on_error": "stop",
        "retry": None,
    }
    if parent is not None:
        node["parent"] = parent
    return node


def _graph_edge(source: str, target: str, source_port: str = "main") -> dict:
    return {
        "id": f"ed_{source}_{target}_{source_port}",
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": "main"},
    }


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


def _resolver() -> _Resolver:
    return _Resolver()


def test_sql_store_writes_the_columns_and_one_past_the_highest_seq(monkeypatch) -> None:
    if not _postgres_up():
        pytest.skip("Postgres is not available")
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", _DATABASE_URL)
    monkeypatch.setenv(
        "REDIS_URL",
        os.getenv("REFRAQ_INTEGRATION_REDIS_URL", "redis://127.0.0.1:6379/1"),
    )
    from backend.channel.models import (
        ChannelNodeExecutionRow,
        ChannelRow,
        ChannelRunRow,
    )
    from backend.channel.run_store import SqlRunStore
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons, session_scope
    from backend.core.time import utc_now
    from backend.core.upgrade import migrate_with_advisory_lock

    reset_settings_cache()
    reset_db_singletons()
    migrate_with_advisory_lock(_DATABASE_URL)
    reset_db_singletons()
    channel_id = f"chn_{uuid.uuid4().hex[:12]}"
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = utc_now()
    store = SqlRunStore()
    try:
        with session_scope() as session:
            session.add(
                ChannelRow(
                    id=channel_id,
                    name="container round",
                    description=None,
                    active=True,
                    draft_graph={"nodes": [], "edges": [], "settings": {}},
                    draft_revision=1,
                    draft_updated_at=now,
                    created_at=now,
                    updated_at=now,
                    failure_streak=0,
                )
            )
            session.add(
                ChannelRunRow(
                    job_id=job_id,
                    channel_id=channel_id,
                    target="draft",
                    version=None,
                    draft_revision=1,
                    graph=None,
                    trigger_node_id="nd_a",
                    ignore_checkpoints=False,
                    outcome=None,
                    failed_node_id=None,
                    stopped_node_id=None,
                    stop_at_node_id=None,
                    skipped_node_ids=[],
                    context=None,
                    created_at=now,
                )
            )
        first = store.start_execution(job_id, "nd_a")
        second = store.start_execution(job_id, "nd_b", container_seq=1, round=0)
        third = store.start_execution(job_id, "nd_c", container_seq=1, round=1)
        assert [first.seq, second.seq, third.seq] == [1, 2, 3]
        assert (second.container_seq, second.round) == (1, 0)
        with session_scope() as session:
            row = session.get(ChannelNodeExecutionRow, second.id)
            assert row is not None
            assert (row.container_seq, row.round) == (1, 0)
            session.delete(row)
        fourth = store.start_execution(job_id, "nd_d")
        assert fourth.seq == 4
        stored = store.get_execution(job_id, 3)
        assert stored is not None
        assert (stored.container_seq, stored.round) == (1, 1)
        preview = store.start_execution(job_id, "nd_preview", container_seq=4, round=1)
        preview.status = "succeeded"
        preview.finished_at = now
        preview.output = {"rows": [0, 1, 2]}
        preview.output_bytes = 99
        preview.preview_only = True
        preview.preview_totals = {"rows": 150}
        preview.input = {"sql": {"value": "select 1"}}
        preview.input_totals = {"nums": 101}
        store.finish_execution(preview)
        with session_scope() as session:
            raw = session.get(ChannelNodeExecutionRow, preview.id)
            assert raw is not None
            assert set(raw.output) == {"$refraq_preview", "$refraq_value"}
            assert raw.output["$refraq_value"] == {"rows": [0, 1, 2]}
            assert raw.output["$refraq_preview"]["preview_totals"] == {"rows": 150}
            assert raw.input == {"sql": {"value": "select 1"}}
            assert raw.input_totals == {"nums": 101}
        loaded = store.get_execution(job_id, preview.seq)
        assert loaded is not None
        assert loaded.preview_only is True
        assert loaded.preview_totals == {"rows": 150}
        assert loaded.output == {"rows": [0, 1, 2]}
        assert loaded.output_bytes == 99
        assert (loaded.container_seq, loaded.round) == (4, 1)
        assert loaded.input == {"sql": {"value": "select 1"}}
        assert loaded.input_totals == {"nums": 101}
        unfinished = store.get_execution(job_id, fourth.seq)
        assert unfinished is not None
        assert unfinished.input is None
        assert unfinished.input_totals is None
        store.insert_round(
            job_id,
            container_seq=1,
            round=0,
            step={"rows": [0], "index": 0, "count": 2, "total": 150},
            step_totals={"rows": 150},
        )
        store.insert_round(
            job_id,
            container_seq=1,
            round=1,
            step={"rows": [1], "index": 1, "count": 2, "total": 150},
            step_totals={"rows": 150},
        )
        store.set_round_template(
            job_id,
            container_seq=1,
            round=0,
            path="flag",
            entry={"value": True},
        )
        recorded = store.get_round(job_id, 1, 0)
        assert recorded is not None
        assert recorded.step == {
            "rows": [0],
            "index": 0,
            "count": 2,
            "total": 150,
            "flag": {"value": True},
        }
        with pytest.raises(RuntimeError):
            store.set_round_template(
                job_id,
                container_seq=1,
                round=9,
                path="flag",
                entry={"value": False},
            )
        paged, round_total = store.query_rounds(job_id, 1, limit=1, offset=1)
        assert round_total == 2
        assert len(paged) == 1
        assert paged[0].round == 1
        assert paged[0].step == {"rows": [1], "index": 1, "count": 2, "total": 150}
        assert paged[0].step_totals == {"rows": 150}
        failed_child = store.start_execution(
            job_id, "nd_child", container_seq=1, round=1
        )
        failed_child.status = "failed"
        failed_child.finished_at = now
        store.finish_execution(failed_child)
        counts = store.round_status_counts(job_id, 1)
        assert counts[1] == {"running": 1, "failed": 1}
        assert 0 not in counts
        assert store.round_status_counts(job_id, 4) == {1: {"succeeded": 1}}
    finally:
        reset_db_singletons()
        with session_scope() as session:
            channel = session.get(ChannelRow, channel_id)
            if channel is not None:
                session.delete(channel)
        reset_settings_cache()
        reset_db_singletons()


def _postgres_up() -> bool:
    try:
        engine = create_engine(_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return False
    return True
