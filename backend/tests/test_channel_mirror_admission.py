"""Offline final mirror composition and persistent admission contracts."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.channel import mirror_reads
from backend.metadata.mirrors import service as mirrors
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.source_access import authorize_source_read_on
from backend.core.errors import AppError
from backend.channel import service, channel_run
from backend.channel.models import ChannelRunRow, ChannelVersionRow
from backend.channel.store import empty_graph
from backend.core.time import utc_now
from backend.jobs.store import SqlJobStore, create_queued_job
from backend.jobs.models import JobRow
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def jsonb(element, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        for statement in (
            "CREATE TABLE users (id TEXT, status TEXT, identity_source TEXT, role_id TEXT)",
            "CREATE TABLE roles (id TEXT, key TEXT, permissions TEXT)",
            "CREATE TABLE source_memberships (subject_type TEXT, subject_id TEXT, target TEXT, level TEXT)",
            "CREATE TABLE user_groups (id TEXT)",
            "CREATE TABLE user_group_members (group_id TEXT, user_id TEXT)",
            "INSERT INTO users VALUES ('u', 'active', 'local', 'r')",
            "INSERT INTO roles VALUES ('r', 'reader', '[\"sources:data_read\"]')",
            "INSERT INTO source_memberships VALUES ('user', 'u', 's', 'viewer')",
        ):
            session.execute(text(statement))
        yield session
    engine.dispose()


@pytest.mark.parametrize("node_type", ["read.changes", "volume.changes_dataset"])
def test_incremental_preflight_rechecks_real_same_session_grants(session, monkeypatch, node_type):
    store = MemoryMirrorStore()
    store.mirrors["m"] = dict(id="m", source_id="s", object_id="o",
                              table_identity="o", qualified_table="public.orders")
    mirrors.bind_management(store=store)
    mirrors.bind_source_read_authorizer(authorize_source_read_on)
    monkeypatch.setattr(mirror_reads, "_reads", object())
    graph = {"nodes": [{"type": node_type, "config": {
        "source": {"kind": "mirror", "mirror_id": "m", "source_id": "untrusted"}}}]}
    try:
        mirror_reads.authorize_graph(graph, "u", session=session)
        session.execute(text("UPDATE roles SET permissions = '[]'"))
        with pytest.raises(AppError):
            mirror_reads.authorize_graph(graph, "u", session=session)
        session.execute(text('UPDATE roles SET permissions = \'["sources:data_read"]\''))
        session.execute(text("DELETE FROM source_memberships"))
        with pytest.raises(AppError):
            mirror_reads.authorize_graph(graph, "u", session=session)
        with pytest.raises(AppError):
            mirror_reads.authorize_graph(graph, None, session=session)
    finally:
        mirrors.bind_management()
        mirrors.bind_source_read_authorizer()


def test_same_session_revocation_and_role_identity_changes(session):
    check = lambda: authorize_source_read_on(session=session, execution_user_id="u", source_id="s")
    assert check() is None
    session.execute(text("DELETE FROM source_memberships"))
    with pytest.raises(AppError):
        check()
    session.execute(text("INSERT INTO source_memberships VALUES ('role', 'r', '*', 'maintainer')"))
    assert check() is None
    session.execute(text("UPDATE users SET identity_source = 'system'"))
    with pytest.raises(AppError):
        check()


def test_group_and_role_permission_intersection(session):
    session.execute(text("DELETE FROM source_memberships"))
    session.execute(text("INSERT INTO source_memberships VALUES ('group', 'g', 's', 'viewer')"))
    session.execute(text("INSERT INTO user_groups VALUES ('g')"))
    session.execute(text("INSERT INTO user_group_members VALUES ('g', 'u')"))
    assert authorize_source_read_on(session=session, execution_user_id="u", source_id="s") is None
    session.execute(text("UPDATE roles SET permissions = '[]'"))
    with pytest.raises(AppError):
        authorize_source_read_on(session=session, execution_user_id="u", source_id="s")


def test_object_resolver_forwards_exact_session_without_reservation(monkeypatch):
    marker = object()
    monkeypatch.setattr(mirror_reads, "_reads", object())
    calls = []
    monkeypatch.setattr(mirror_reads, "resolve_object_binding", lambda *a, **kw: calls.append((a, kw)) or {"needs_open": True})
    assert mirror_reads.resolve_object("o", session=marker) == {"needs_open": True}
    assert calls == [(("o",), {"session": marker})]


@pytest.mark.parametrize("status,outcome", [("running", "completed"), ("failed", "completed"), ("succeeded", None)])
def test_terminal_validator_rejects_resumable_or_incomplete_runs(monkeypatch, status, outcome):
    run = SimpleNamespace(outcome=outcome, stopped_node_id=None, failed_node_id=None,
                          mirror_execution_user_id="u", mirror_state={"pins": {"m": {"generation_id": "g", "source_id": "s"}}, "source_ids": ["s"]})
    job = SimpleNamespace(kind="channel_run", status=status, finished_at=object())
    @contextmanager
    def scope():
        yield SimpleNamespace(get=lambda *args: run)
    monkeypatch.setattr(mirror_reads, "session_scope", scope)
    monkeypatch.setattr(mirror_reads, "get_job_store", lambda: SimpleNamespace(get=lambda *a, **kw: job))
    with pytest.raises(AppError):
        mirror_reads.validate_terminal_proof(run_id="j", terminal_proof={"run_id": "j", **run.mirror_state})


def test_terminal_validator_checks_persistent_provenance(monkeypatch):
    state = {"pins": {"m": {"generation_id": "g", "source_id": "s"}}, "source_ids": ["s"]}
    run = SimpleNamespace(outcome="completed", stopped_node_id=None, failed_node_id=None,
                          mirror_execution_user_id="u", mirror_state=state)
    job = SimpleNamespace(kind="channel_run", status="succeeded", finished_at=object())
    @contextmanager
    def scope():
        yield SimpleNamespace(get=lambda *args: run)
    monkeypatch.setattr(mirror_reads, "session_scope", scope)
    monkeypatch.setattr(mirror_reads, "get_job_store", lambda: SimpleNamespace(get=lambda *a, **kw: job))
    assert mirror_reads.validate_terminal_proof(run_id="j", terminal_proof={"run_id": "j", **state}) is None
    for proof in (True, {"run_id": "other", **state}, {"run_id": "j", "pins": {}, "source_ids": ["s"]}):
        with pytest.raises(AppError):
            mirror_reads.validate_terminal_proof(run_id="j", terminal_proof=proof)


def test_real_persistent_terminal_evidence_and_release_order(monkeypatch):
    engine = create_engine("sqlite://")
    ChannelRunRow.__table__.create(engine)
    JobRow.__table__.create(engine)
    store = SqlJobStore()
    @contextmanager
    def scope():
        with Session(engine) as session, session.begin():
            yield session
    monkeypatch.setattr(mirror_reads, "session_scope", scope)
    monkeypatch.setattr(mirror_reads, "get_job_store", lambda: store)
    state = {"pins": {"m": {"generation_id": "g", "source_id": "s"}}, "source_ids": ["s"]}
    with scope() as session:
        job = create_queued_job(kind="channel_run", input={})
        job.status = "succeeded"
        job.finished_at = utc_now()
        store.create(job, session=session)
        session.add(ChannelRunRow(job_id=job.id, channel_id="c", target="published", graph=empty_graph(),
                                 trigger_node_id="n", ignore_checkpoints=False, outcome="completed",
                                 skipped_node_ids=[], mirror_execution_user_id="u", mirror_state=state,
                                 created_at=utc_now()))
    assert mirror_reads.validate_terminal_proof(run_id=job.id, terminal_proof={"run_id": job.id, **state}) is None
    with scope() as session:
        session.get(ChannelRunRow, job.id).mirror_state = {**state, "source_ids": ["other"]}
    with pytest.raises(AppError):
        mirror_reads.validate_terminal_proof(run_id=job.id, terminal_proof={"run_id": job.id, **state})
    engine.dispose()


@pytest.mark.parametrize("node_type", ["read.mirror", "read.changes", "volume.changes_dataset"])
def test_publish_forwards_explicit_confirmation_and_same_session(monkeypatch, node_type):
    graph = empty_graph()
    graph["nodes"] = [{"type": node_type, "config": {"object_id": "o", "source": {
        "kind": "mirror", "mirror_id": "m"}}}]
    record = SimpleNamespace(id="c", draft_revision=1, draft_graph=graph)
    version = SimpleNamespace(graph=graph, number=1, published_by_user_id="u")
    marker = object()
    confirmations = [{"source_id": "s", "object_id": "o", "mirror_id": "m"}]
    calls = []
    def publish(*args, **kwargs):
        kwargs["after"](marker, version)
        return version
    monkeypatch.setattr(service, "_require", lambda *a: record)
    monkeypatch.setattr(service, "_require_publish_permissions", lambda *a: None)
    monkeypatch.setattr(service, "_require_publish_source_levels", lambda *a: None)
    monkeypatch.setattr(service, "validate", lambda *a: [])
    monkeypatch.setattr(service, "require_inbound_publish", lambda *a: None)
    monkeypatch.setattr(service, "_confirmation", lambda *a: {"mirrors_to_open": confirmations})
    monkeypatch.setattr(service, "get_channel_store", lambda: SimpleNamespace(
        list_versions=lambda *a, **kw: ([], 0), publish_version=publish))
    monkeypatch.setattr(service, "authorize_graph", lambda *a, **kw: calls.append(("auth", kw["session"])))
    monkeypatch.setattr(service, "ensure_open_intent", lambda session, **kw: calls.append(("intent", session, kw)))
    monkeypatch.setattr(service, "reconcile_references", lambda session, **kw: calls.append(("refs", session)))
    monkeypatch.setattr(service, "sync_published_schedule", lambda *a: None)
    monkeypatch.setattr(service, "sync_published_inbound_path", lambda *a: None)
    monkeypatch.setattr(service, "_audit", lambda **kw: None)
    if node_type == "read.mirror":
        with pytest.raises(AppError):
            service.publish_channel(channel_id="c", draft_revision=1, actor_user_id="u", actor_token_id=None)
    service.publish_channel(channel_id="c", draft_revision=1, actor_user_id="u", actor_token_id=None,
                            mirrors_to_open=confirmations)
    assert calls[0] == ("auth", marker)
    assert calls[1][1] is marker
    assert calls[1][2]["confirmed_mirrors_to_open"] is confirmations
    assert calls[2] == ("refs", marker)
    graph["nodes"].append({"type": "trigger.scheduled", "config": {}})
    with pytest.raises(AppError, match="Unattended mirror graphs require an execution identity"):
        service.publish_channel(channel_id="c", draft_revision=1, actor_user_id="u", actor_token_id=None,
                                mirrors_to_open=confirmations)
    graph["settings"]["mirror_execution_user_id"] = "selected"
    calls.clear()
    service.publish_channel(channel_id="c", draft_revision=1, actor_user_id="u", actor_token_id=None,
                            mirrors_to_open=confirmations)
    assert calls[:2] == [("auth", marker), ("auth", marker)]


@pytest.mark.parametrize("node_type", ["read.mirror", "read.changes", "volume.changes_dataset"])
def test_scheduler_uses_admission_session_without_external_identity_reads(monkeypatch, node_type):
    graph = {"nodes": [{"type": node_type, "config": {"object_id": "o", "source": {
        "kind": "mirror", "mirror_id": "m"}}}],
             "settings": {"mirror_execution_user_id": "u"}}
    marker = SimpleNamespace(scalar=lambda *a: SimpleNamespace(graph=graph, number=3))
    events = []
    monkeypatch.setattr(channel_run, "authorize_graph", lambda g, u, **kw: events.append((u, kw["session"])))
    monkeypatch.setattr(channel_run, "create_queued_job", lambda **kw: events.append(kw) or SimpleNamespace(id="j"))
    monkeypatch.setattr(channel_run, "get_run_store", lambda: SimpleNamespace(insert_run=lambda r, **kw: events.append((r, kw))))
    monkeypatch.setattr(channel_run, "get_channel_store", lambda: pytest.fail("nested Channel session"))
    monkeypatch.setattr(channel_run, "get_job_store", lambda: pytest.fail("nested Job session"))
    now = utc_now()
    result = channel_run.mint_scheduled_run(schedule_id="t", channel_id="c", node_id="n",
        scheduled_for=now, is_delayed_recovery=False, now=now, session=marker)
    assert result.status == "queued"
    assert events[0] == ("u", marker)
    assert events[1]["input"]["version"] == 3
    assert events[2][0].version == 3
    assert events[2][0].mirror_execution_user_id == "u"
    assert events[2][1]["session"] is marker


def test_terminal_release_validates_before_any_target_sql(monkeypatch):
    from backend.metadata.mirrors.reads import Reads
    from backend.metadata.mirrors.composition import terminal_proof_adapter
    events = []
    class Engine:
        @contextmanager
        def begin(self):
            events.append("target")
            yield SimpleNamespace(execute=lambda *a: events.append("release"))
    def denied(**kwargs):
        events.append("proof")
        raise mirror_reads.MirrorReadUnavailable()
    gateway = Reads(Engine(), authorize_source_read=lambda **kw: None,
                    verify_terminal_proof=terminal_proof_adapter(denied))
    with pytest.raises(AppError):
        gateway.release_run_pins(run_id="j", terminal_proof={"run_id": "j"})
    assert events == ["proof"]
    def accepted(**kwargs):
        events.append("validated")
    gateway.verify_terminal_proof = terminal_proof_adapter(accepted)
    gateway.release_run_pins(run_id="j", terminal_proof={"run_id": "j"})
    assert events == ["proof", "validated", "target", "release"]


def test_success_settlement_releases_before_discard_and_retains_failed_release(monkeypatch):
    from backend.channel import recovery
    events = []
    run = SimpleNamespace(job_id="j", channel_id="c", target="published")
    monkeypatch.setattr(recovery, "release_completed_run", lambda r: events.append("release"))
    monkeypatch.setattr(recovery, "_write_streak", lambda *a: events.append("streak"))
    monkeypatch.setattr(recovery, "_discard_job", lambda *a: events.append("discard"))
    recovery.settle_success(run, checkpoints_settled=True)
    assert events == ["release", "streak", "discard"]
    events.clear()
    def unavailable(r):
        raise mirror_reads.MirrorReadUnavailable()
    monkeypatch.setattr(recovery, "release_completed_run", unavailable)
    recovery.settle_success(run, checkpoints_settled=True)
    assert events == []


def test_success_cas_authorizes_with_exact_settlement_session(monkeypatch):
    from backend.channel import runner
    marker = object()
    events = []
    @contextmanager
    def scope():
        yield marker
        events.append("commit")
    monkeypatch.setattr(runner, "session_scope", scope)
    monkeypatch.setattr(runner, "authorize_graph", lambda *a, **kw: events.append(("auth", kw["session"])))
    monkeypatch.setattr(runner, "mark_succeeded", lambda *a, **kw: events.append(("cas", kw["session"])) or SimpleNamespace(status="succeeded"))
    monkeypatch.setattr(runner, "advance_from_run_in_session", lambda s, r: events.append(("checkpoint", s)))
    run = SimpleNamespace(job_id="j", graph={"nodes": [{"type": "read.mirror"}]}, mirror_execution_user_id="u")
    assert runner.complete_mirror_success(run, {}).status == "succeeded"
    assert events == [("auth", marker), ("cas", marker), ("checkpoint", marker), "commit"]
