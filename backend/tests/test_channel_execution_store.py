"""Node execution sequence and container round on the run store."""

from __future__ import annotations

import os
import uuid

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


def test_success_under_batch_read_stores_a_preview_and_keeps_the_runtime_output(monkeypatch) -> None:
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.engine import execute
    from backend.channel.graph import CONTAINER_TYPES, ContainerType
    from backend.channel.nodes.spec import NodeResult, NodeType, PortSpec
    from backend.channel.run_store import ChannelRunRecord, get_run_store, output_size
    from backend.channel.sandbox import SandboxSession
    from backend.core.time import utc_now

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    rows = list(range(120))
    tags = ["a", "b"]

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1, "total": 1, "batch_size": 1000},
                iterations=[{"current": 0}],
                ports=frozenset({"done"}),
            )
        if node["id"] == "inner":
            return NodeResult(
                status="succeeded",
                output={"current": 1, "index": 0, "count": 1},
                iterations=[{"current": 1, "index": 0, "count": 1}],
                ports=frozenset({"done"}),
            )
        return NodeResult(status="succeeded", output={"rows": rows, "tags": tags})

    def kind(type_id: str) -> NodeType:
        return NodeType(
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
            execute=run,
        )

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
            schedule={"schedule_id": None, "name": "", "scheduled_for": "2026-10-22T00:00:00Z"},
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
    assert step_row.preview_only is True
    assert step_row.preview_totals == {"rows": 120, "tags": 2}
    assert step_row.output["rows"] is not rows
    assert len(step_row.output["rows"]) == 100
    assert step_row.output["rows"] == list(range(100))
    assert step_row.output["tags"] == ["a", "b"]
    assert step_row.output_bytes == output_size({"rows": rows, "tags": tags})
    assert (step_row.container_seq, step_row.round) == (inner_row.seq, 0)
    assert (inner_row.container_seq, inner_row.round) == (batch_row.seq, 0)
    assert (batch_row.container_seq, batch_row.round) == (None, None)
    assert batch_row.preview_only is False
    assert batch_row.preview_totals == {}
    assert "iterations" not in batch_row.output
    assert inner_row.preview_only is True
    assert len(inner_row.output["iterations"][0]["step"]["rows"]) == 100
    assert inner_row.preview_totals["iterations.0.step.rows"] == 120
    assert inner_row.preview_totals["iterations"] == 1
    assert inner_row.output_bytes == output_size(full_inner)


def test_failed_execution_under_batch_read_stores_the_full_output(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType
    from backend.channel.nodes.spec import NodeResult
    from backend.channel.run_store import get_run_store

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    rows = list(range(120))

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1},
                iterations=[{"current": 0}],
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


def test_a_failed_retry_stores_the_full_output_and_the_success_stores_a_preview(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType
    from backend.channel.nodes.spec import NodeResult
    from backend.channel.run_store import get_run_store

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    calls = {"n": 0}
    held: list[list[int]] = []

    def run(node: dict, hooks: object) -> NodeResult:
        del hooks
        if node["id"] == "batch":
            return NodeResult(
                status="succeeded",
                output={"count": 1},
                iterations=[{"current": 0}],
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
    steps = [item for item in get_run_store().list_executions(job_id) if item.node_id == "step"]
    assert len(steps) == 2
    assert steps[0].status == "failed"
    assert steps[0].preview_only is False
    assert steps[0].output["rows"] is held[0]
    assert len(steps[0].output["rows"]) == 120
    assert steps[1].status == "succeeded"
    assert steps[1].preview_only is True
    assert len(steps[1].output["rows"]) == 100
    assert steps[1].output["rows"] is not held[1]
    assert len(held[1]) == 120


def test_note_killed_run_keeps_the_full_output() -> None:
    from backend.channel.run_store import ChannelRunRecord, get_run_store, note_killed_run
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


def _run_preview_graph(run, *, step_retry: dict | None) -> str:
    from backend.admin.user_store import UserRecord
    from backend.channel.channel_run import _RunHooks
    from backend.channel.engine import execute
    from backend.channel.nodes.spec import NodeType, PortSpec
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
        return NodeType(
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
            execute=run,
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
    hooks = _RunHooks(
        _QuietSandbox(),
        run_id=job_id,
        actor={"id": "usr_system", "name": "System"},
        started_at="2026-10-22T00:00:00Z",
        user=user,
        schedule={"schedule_id": None, "name": "", "scheduled_for": "2026-10-22T00:00:00Z"},
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


def _graph_node(node_id: str, type_id: str, y: int, *, parent: str | None = None) -> dict:
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
    monkeypatch.setenv("REDIS_URL", os.getenv("REFRAQ_INTEGRATION_REDIS_URL", "redis://127.0.0.1:6379/1"))
    from backend.channel.models import ChannelNodeExecutionRow, ChannelRow, ChannelRunRow
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
        store.finish_execution(preview)
        with session_scope() as session:
            raw = session.get(ChannelNodeExecutionRow, preview.id)
            assert raw is not None
            assert set(raw.output) == {"$refraq_preview", "$refraq_value"}
            assert raw.output["$refraq_value"] == {"rows": [0, 1, 2]}
            assert raw.output["$refraq_preview"]["preview_totals"] == {"rows": 150}
        loaded = store.get_execution(job_id, preview.seq)
        assert loaded is not None
        assert loaded.preview_only is True
        assert loaded.preview_totals == {"rows": 150}
        assert loaded.output == {"rows": [0, 1, 2]}
        assert loaded.output_bytes == 99
        assert (loaded.container_seq, loaded.round) == (4, 1)
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
