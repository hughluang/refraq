"""Offline worker assembly, transactional admission and terminal sealing contracts."""

from contextlib import contextmanager
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.channel import channel_run, mirror_reads, recovery
from backend.core.errors import AppError


@pytest.mark.parametrize("module", [
    "backend.channel.channel_run", "backend.channel.tasks", "backend.channel.runner",
    "backend.channel.recovery", "backend.channel.mirror_reads", "backend.channel.nodes",
    "backend.worker.tasks", "backend.worker.app",
])
def test_worker_modules_import_in_fresh_interpreter(module):
    env = {**os.environ, "REFRAQ_STORE_BACKEND": "memory", "CELERY_BROKER_URL": "memory://"}
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_channel_task_supplies_own_post_exit_finalizer(monkeypatch):
    from backend.channel import tasks

    events = []
    def supervised(job_id, target, *, after_exit):
        assert target == "backend.worker.tasks:execute_channel_run"
        assert after_exit is tasks.seal_mirror_run
        events.append("waited")
        after_exit(job_id)
        return {"status": "failed"}
    monkeypatch.setattr(tasks, "supervise", supervised)
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(store_backend="persistent"))
    monkeypatch.setattr(tasks.recovery, "seal_supervised_run", lambda job: events.append(("sealed", job)))
    monkeypatch.setattr(tasks, "seal_dataset_expiry", lambda job: None)
    monkeypatch.setattr(tasks, "_release_settled_inbound_dedup", lambda *a: None)
    assert tasks.run_job.run("j") == {"status": "failed"}
    assert events == ["waited", ("sealed", "j")]


def test_worker_child_enters_runtime_before_channel_execution(monkeypatch):
    from backend.worker import tasks

    events = []
    @contextmanager
    def runtime():
        events.append("opened")
        yield
        events.append("closed")
    monkeypatch.setattr(tasks, "channel_mirror_runtime", runtime)
    monkeypatch.setattr(tasks, "execute_run", lambda job: events.append(job) or {"status": "succeeded"})
    assert tasks.execute_channel_run("j") == {"status": "succeeded"}
    assert events == ["opened", "j", "closed"]


def test_runtime_assembles_and_closes_actual_adapters(monkeypatch):
    from backend import mirror_runtime as runtime

    events = []
    adapters = SimpleNamespace(reads=object(), history_target=object(), close=lambda: events.append("close"))
    monkeypatch.setattr(runtime, "bind_reads", lambda value: events.append(("reads", value)))
    monkeypatch.setattr(runtime, "bind_source_read_authorizer", lambda value: events.append(("auth", value)))
    monkeypatch.setattr(runtime, "get_session_factory", lambda: "sessions")
    monkeypatch.setattr(runtime, "bind_history", lambda value: events.append(("history", value)))
    def compose(settings, *, verify_terminal_proof):
        assert verify_terminal_proof is mirror_reads.validate_terminal_proof
        return adapters
    monkeypatch.setattr(runtime, "compose_mirrors", compose)
    with runtime.channel_mirror_runtime():
        assert ("reads", adapters.reads) in events
    assert events[-1] == "close"
    assert events[-4:] == [("history", None), ("reads", None), ("auth", None), "close"]


@pytest.mark.parametrize("node_type", ["read.mirror", "read.changes", "volume.changes_dataset"])
@pytest.mark.parametrize("kind", ["user", "inbound", "retry", "error"])
def test_mint_authorization_and_both_inserts_use_one_session(monkeypatch, kind, node_type):
    graph = {"nodes": [{"type": node_type, "config": {"object_id": "o", "source": {
        "kind": "mirror", "mirror_id": "m"}}}],
             "settings": {"mirror_execution_user_id": "selected"}}
    parent = SimpleNamespace(
        channel_id="c", version=3, graph=graph, mirror_execution_user_id="selected",
        mirror_state={"source_ids": ["s"]}, failed_node_id="failed", stopped_node_id=None,
    )
    parent_job = SimpleNamespace(kind="channel_run", trigger_kind="user", input={}, error_code="CHANNEL_NODE_FAILED")
    marker = SimpleNamespace(
        get=lambda model, key, **kw: parent if model is channel_run.ChannelRunRow else SimpleNamespace(),
        scalar=lambda *a: SimpleNamespace(graph=graph, number=3),
    )
    @contextmanager
    def scope():
        yield marker
    monkeypatch.setattr(channel_run, "_mint_session", scope)
    seen = []
    def authorize(g, identity, *, session):
        assert session is marker
        assert identity == ("actor" if kind == "user" else "selected")
        seen.append("authorized")
    monkeypatch.setattr(channel_run, "authorize_graph", authorize)
    def load_parent_job(job_id, *, session):
        assert job_id == "actor" and session is marker
        return parent_job
    def authorize_parent(record, identity, *, session):
        assert record is parent and identity == "selected" and session is marker
        seen.append("authorized inherited sources")
    monkeypatch.setattr(channel_run, "get_job_store", lambda: SimpleNamespace(get=load_parent_job))
    monkeypatch.setattr(channel_run, "require_run_data_access", authorize_parent)
    authorizations = ["authorized", "authorized inherited sources"] if kind in {"retry", "error"} else ["authorized"]
    def create(**kw):
        assert kw["session"] is marker
        assert seen == authorizations
        assert kw["input"]["version"] == 3
        assert recovery._is_on_demand_test(SimpleNamespace(trigger_kind=kind, input=kw["input"])) == (kind == "user")
        return SimpleNamespace(id="job")
    monkeypatch.setattr(channel_run, "create_queued_job", create)
    monkeypatch.setattr(channel_run, "get_run_store", lambda: SimpleNamespace(
        insert_run=lambda record, *, session: seen.append(session)))
    _, record = channel_run._mint_run(
        channel_id="c", channel_name="C", target="published", version=None,
        draft_revision=None, graph=None, trigger_node="t", ignore_checkpoints=False,
        stop_at_node_id=None, payload={"error_source": {"job_id": "actor", "channel_id": "c"}}
        if kind == "error" else {}, trigger_kind=kind, trigger_ref="actor",
    )
    assert seen == [*authorizations, marker]
    assert record.mirror_execution_user_id == ("actor" if kind == "user" else "selected")


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_failure_requires_exact_durable_seal(monkeypatch, status):
    pins = {"m": {"generation_id": "g", "source_id": "s"}}
    run = SimpleNamespace(outcome="failed", stopped_node_id=None, failed_node_id="n",
                          mirror_execution_user_id="u", mirror_state={"pins": pins, "source_ids": ["s"]})
    job = SimpleNamespace(kind="channel_run", status=status, finished_at=object())
    @contextmanager
    def scope():
        yield SimpleNamespace(get=lambda *a: run)
    monkeypatch.setattr(mirror_reads, "session_scope", scope)
    monkeypatch.setattr(mirror_reads, "get_job_store", lambda: SimpleNamespace(get=lambda *a, **kw: job))
    proof = {"run_id": "j", "pins": pins, "source_ids": ["s"]}
    with pytest.raises(AppError):
        mirror_reads.validate_terminal_proof(run_id="j", terminal_proof=proof)
    run.mirror_state["terminal_seal"] = {"status": status, "nonresumable": True}
    assert mirror_reads.validate_terminal_proof(run_id="j", terminal_proof=proof) is None
    job.status = "running"
    with pytest.raises(AppError):
        mirror_reads.validate_terminal_proof(run_id="j", terminal_proof=proof)


def test_supervisor_invokes_seal_only_after_wait_and_terminal_finish(monkeypatch):
    from backend.jobs import supervise as supervisor

    events = []
    monkeypatch.setattr(supervisor, "get_settings", lambda: SimpleNamespace(store_backend="persistent"))
    monkeypatch.setattr(supervisor, "claim_queued", lambda *a, **kw: object())
    monkeypatch.setattr(supervisor, "_spawn", lambda *a: "process")
    monkeypatch.setattr(supervisor, "watch_process", lambda *a: events.append("waited"))
    monkeypatch.setattr(supervisor, "_finish", lambda *a: events.append("finished") or {"status": "failed"})
    supervisor.supervise("j", "target:run", after_exit=lambda *a: events.append("sealed"))
    assert events == ["waited", "finished", "sealed"]


@pytest.mark.parametrize("retryable", [False, True])
def test_seal_commits_before_release_and_preserves_retry_pins(monkeypatch, retryable):
    from backend.channel import recovery

    events = []
    run = SimpleNamespace(target="published", version=1, mirror_state={"pins": {"m": {}}})
    job = SimpleNamespace(status="failed", trigger_kind="schedule", finished_at=object())
    monkeypatch.setattr(recovery, "_ancestors", lambda job: 0)
    monkeypatch.setattr(recovery, "_limit", lambda run: 1 if retryable else 0)
    monkeypatch.setattr(recovery, "get_job_store", lambda: SimpleNamespace(get=lambda *a, **kw: job))
    monkeypatch.setattr(recovery, "get_run_store", lambda: SimpleNamespace(get_run=lambda *a: run))
    @contextmanager
    def scope():
        yield SimpleNamespace(get=lambda *a, **kw: run)
        events.append("committed")
    monkeypatch.setattr(recovery, "session_scope", scope)
    monkeypatch.setattr(recovery, "release_completed_run", lambda run: events.append("released"))
    monkeypatch.setattr(recovery, "discard_unkept_run", lambda job_id: None)
    recovery.seal_supervised_run("j")
    if retryable:
        assert events == []
        assert "terminal_seal" not in run.mirror_state
    else:
        assert events == ["committed", "released"]
        assert run.mirror_state["terminal_seal"] == {"status": "failed", "nonresumable": True}


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("identity", ["original_actor", None])
def test_retry_retains_original_execution_identity_and_rechecks_it(monkeypatch, persistent, identity):
    graph = {"nodes": [{"type": "read.mirror", "config": {"object_id": "o"}}],
             "settings": {"mirror_execution_user_id": "different_selected_user"}}
    parent = SimpleNamespace(channel_id="c", version=3, mirror_execution_user_id=identity,
                             graph=graph, mirror_state={"source_ids": ["s"]})
    parent_job = SimpleNamespace(kind="channel_run", trigger_kind="user", input={})
    marker = SimpleNamespace(
        get=lambda model, key, **kw: parent if key == "parent" else SimpleNamespace(),
        scalar=lambda *a: SimpleNamespace(graph=graph, number=3),
    )
    @contextmanager
    def scope():
        yield marker if persistent else None
    monkeypatch.setattr(channel_run, "_mint_session", scope)
    monkeypatch.setattr(channel_run, "get_channel_store", lambda: SimpleNamespace(
        get_version=lambda *a: SimpleNamespace(graph=graph)))
    records = []
    monkeypatch.setattr(channel_run, "get_run_store", lambda: SimpleNamespace(
        get_run=lambda *a: parent, insert_run=lambda r, **kw: records.append(r)))
    monkeypatch.setattr(channel_run, "get_job_store", lambda: SimpleNamespace(get=lambda *a, **kw: parent_job))
    def authorize(g, selected, **kw):
        assert selected == identity
        assert kw.get("session") is (marker if persistent else None)
        if selected is None:
            raise mirror_reads.MirrorDataForbidden()
    monkeypatch.setattr(channel_run, "authorize_graph", authorize)
    def authorize_parent(record, selected, *, session):
        assert record is parent and selected == identity
        assert session is (marker if persistent else None)
    monkeypatch.setattr(channel_run, "require_run_data_access", authorize_parent)
    monkeypatch.setattr(channel_run, "create_queued_job", lambda **kw: SimpleNamespace(id="child"))
    def mint():
        return channel_run.mint_followup_run(
            channel_id="c", channel_name="C", trigger_kind="retry", trigger_ref="parent",
            trigger_node="t", version=3, job_input={"retry_of_job_id": "parent"})
    if identity is None:
        with pytest.raises(AppError):
            mint()
        assert records == []
    else:
        _, run = mint()
        assert run.mirror_execution_user_id == identity
