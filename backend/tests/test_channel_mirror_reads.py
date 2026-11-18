"""Offline contracts for run-scoped mirror reads and protected stored payloads."""

from types import SimpleNamespace

import pytest

from backend.channel import mirror_reads
from backend.core.errors import AppError


def run_record():
    return SimpleNamespace(
        job_id="job_read", graph={"nodes": [{"type": "read.mirror"}]},
        mirror_execution_user_id="usr_reader", mirror_state=None,
    )


def allow(monkeypatch):
    monkeypatch.setattr(mirror_reads, "get_user_store", lambda: SimpleNamespace(
        get_by_id=lambda user_id: SimpleNamespace(status="active")))
    monkeypatch.setattr(mirror_reads, "allows", lambda *args: True)


def test_manual_and_unattended_identity_never_use_entity_system_fallback(monkeypatch):
    allow(monkeypatch)
    graph = {"nodes": [{"type": "read.mirror"}], "settings": {}}
    assert mirror_reads.execution_identity(graph, trigger_kind="user", actor_id="usr_actor") == "usr_actor"
    with pytest.raises(AppError):
        mirror_reads.execution_identity(graph, trigger_kind="schedule", actor_id=None)
    graph["settings"]["mirror_execution_user_id"] = "usr_service"
    assert mirror_reads.execution_identity(graph, trigger_kind="schedule", actor_id=None) == "usr_service"


def test_read_requires_actual_gateway_and_never_saves_unavailable_success(monkeypatch):
    allow(monkeypatch)
    mirror_reads.bind_reads(None)
    saved = []
    monkeypatch.setattr(mirror_reads, "get_run_store", lambda: SimpleNamespace(update_run=saved.append))
    with pytest.raises(AppError) as error:
        mirror_reads.read_run_page(run_record(), mirror_id="mir_one", after_key=None, limit=10)
    assert error.value.code == "MIRROR_READ_UNAVAILABLE"
    assert saved == []


def test_actual_gateway_persists_pin_before_rows_and_revocation_denies_reuse(monkeypatch):
    from contextlib import contextmanager
    from backend.metadata.mirrors.reads import Reads

    allow(monkeypatch)
    run = run_record()
    saved = []
    calls = []
    monkeypatch.setattr(mirror_reads, "get_run_store", lambda: SimpleNamespace(
        update_run=lambda record: saved.append(dict(record.mirror_state))))

    class Connection:
        def execute(self, statement, params):
            calls.append((str(statement), params))
            if "resolve_source" in str(statement):
                value = "src_one"
            elif "acquire_pin" in str(statement):
                value = dict(run_id="job_read", mirror_id="mir_one", generation_id="gen_one", source_id="src_one")
            else:
                assert saved[-1]["source_ids"] == ["src_one"]
                value = dict(rows=[{"id": 1}], generation_id="gen_one", next_key=[1], freshness={"status": "ready"})
            return SimpleNamespace(scalar_one=lambda: value)

    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()

    gateway = Reads(Engine(), authorize_source_read=lambda **kwargs: None, verify_terminal_proof=lambda **kwargs: None)
    mirror_reads.bind_reads(gateway)
    try:
        page = mirror_reads.read_run_page(run, mirror_id="mir_one", after_key=None, limit=10)
        assert page["rows"] == [{"id": 1}]
        assert run.mirror_state["pins"] == {"mir_one": {"generation_id": "gen_one", "source_id": "src_one"}}
        assert run.mirror_state["freshness"] == {"mir_one": {"status": "ready"}}
        mirror_reads.read_run_page(run, mirror_id="mir_one", after_key=[1], limit=10)
        assert calls[-1][1]["after"] == "[1]"
        monkeypatch.setattr(mirror_reads, "allows", lambda *args: False)
        before = len(calls)
        with pytest.raises(AppError):
            mirror_reads.read_run_page(run, mirror_id="mir_one", after_key=[1], limit=10)
        assert len(calls) == before
    finally:
        mirror_reads.bind_reads(None)


def test_union_authorization_rechecks_every_source_and_disabled_identity(monkeypatch):
    allow(monkeypatch)
    run = run_record()
    run.mirror_state = {"source_ids": ["src_one", "src_two"]}
    checked = []
    def authorized(user, source, permission):
        checked.append((user, source, permission))
        return source != "src_two"
    monkeypatch.setattr(mirror_reads, "allows", authorized)
    with pytest.raises(AppError):
        mirror_reads.require_run_data_access(run, "usr_viewer")
    assert checked == [("usr_viewer", "src_one", "sources:data_read"), ("usr_viewer", "src_two", "sources:data_read")]
    monkeypatch.setattr(mirror_reads, "get_user_store", lambda: SimpleNamespace(
        get_by_id=lambda user: SimpleNamespace(status="disabled")))
    with pytest.raises(AppError):
        mirror_reads.require_run_data_access(run, "usr_viewer")


def test_run_identity_and_pin_state_survive_sql_store_reload(monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import JSON, create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import Session
    from backend.channel import run_store
    from backend.channel.models import ChannelRunRow
    from backend.core.time import utc_now

    @compiles(JSONB, "sqlite")
    def compile_json(element, compiler, **kwargs):
        return compiler.visit_JSON(JSON(), **kwargs)

    engine = create_engine("sqlite://")
    ChannelRunRow.__table__.create(engine)

    @contextmanager
    def scope():
        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(run_store, "session_scope", scope)
    store = run_store.SqlRunStore()
    record = run_store.ChannelRunRecord(
        job_id="job_read", channel_id="channel_one", target="published", version=1,
        draft_revision=None, graph={"nodes": []}, trigger_node_id="trigger",
        ignore_checkpoints=False, outcome=None, failed_node_id=None,
        skipped_node_ids=[], created_at=utc_now(), mirror_execution_user_id="usr_reader",
        mirror_state={"source_ids": ["src_one"], "pins": {"mir_one": {"generation_id": "gen_one"}}},
    )
    store.insert_run(record)
    loaded = store.get_run("job_read")
    assert loaded.mirror_execution_user_id == "usr_reader"
    assert loaded.mirror_state == record.mirror_state
    loaded.mirror_state = {**loaded.mirror_state, "freshness": {"mir_one": "stale"}}
    store.update_run(loaded)
    assert store.get_run("job_read").mirror_state["freshness"] == {"mir_one": "stale"}


def test_retry_refuses_revoked_provenance_before_mint(monkeypatch):
    from backend.channel import recovery
    allow(monkeypatch)
    run = run_record()
    run.channel_id = "channel_one"
    run.version = 1
    run.trigger_node_id = "trigger"
    run.mirror_state = {"source_ids": ["src_one"]}
    monkeypatch.setattr(mirror_reads, "allows", lambda *args: False)
    monkeypatch.setattr(recovery, "get_channel_store", lambda: SimpleNamespace(get=lambda channel: None))
    minted = []
    logged = []
    monkeypatch.setattr(recovery.channel_run, "mint_followup_run", lambda **kwargs: minted.append(kwargs))
    monkeypatch.setattr(recovery, "append_job_log", lambda *args, **kwargs: logged.append(kwargs))
    recovery._queue_retry(SimpleNamespace(id="job_read"), run)
    assert minted == []
    assert len(logged) == 1


def test_unknown_mirror_provenance_denies_and_entity_payload_keeps_existing_rule(monkeypatch):
    allow(monkeypatch)
    with pytest.raises(AppError) as error:
        mirror_reads.require_run_data_access(run_record(), "usr_viewer")
    assert error.value.code == "AUTH_FORBIDDEN"
    mirror_reads.require_run_data_access(SimpleNamespace(graph={"nodes": []}), "usr_viewer")


@pytest.mark.parametrize("endpoint", ["executions", "output", "rounds", "dataset", "sample", "preview"])
def test_stored_data_endpoints_refuse_unknown_provenance(monkeypatch, endpoint):
    from backend.channel.routers import runs
    from backend.core.pagination import PageParams

    run = run_record()
    run.channel_id = "channel_one"
    monkeypatch.setattr(runs, "get_run_store", lambda: SimpleNamespace(get_run=lambda job_id: run))
    actor = SimpleNamespace(id="usr_viewer")
    calls = {
        "executions": lambda: runs.http_list_executions("channel_one", "job_read", actor, page=PageParams(limit=10, offset=0)),
        "output": lambda: runs.http_execution_output("channel_one", "job_read", 1, actor),
        "rounds": lambda: runs.http_execution_rounds("channel_one", "job_read", 1, actor),
        "dataset": lambda: runs.http_dataset_rows("channel_one", "job_read", "dataset_one", actor),
        "sample": lambda: runs.http_node_sample("channel_one", "job_read", None, actor),
        "preview": lambda: runs.http_preview_template("channel_one", "job_read", None, actor),
    }
    with pytest.raises(AppError) as error:
        calls[endpoint]()
    assert error.value.code == "AUTH_FORBIDDEN"
