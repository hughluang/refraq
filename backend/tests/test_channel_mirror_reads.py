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


def forbidden(**kwargs):
    raise mirror_reads.MirrorDataForbidden()


def allow(monkeypatch):
    monkeypatch.setattr(mirror_reads, "get_user_store", lambda: SimpleNamespace(
        get_by_id=lambda user_id: SimpleNamespace(status="active")))
    monkeypatch.setattr(mirror_reads, "authorize_source_data", lambda **kwargs: None)


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
        update_run=lambda record: saved.append(dict(record.mirror_state or {}))))

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
        monkeypatch.setattr(mirror_reads, "authorize_source_data", forbidden)
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
    def authorized(*, execution_user_id, source_id, session=None):
        checked.append((execution_user_id, source_id))
        if source_id == "src_two":
            forbidden()
    monkeypatch.setattr(mirror_reads, "authorize_source_data", authorized)
    with pytest.raises(AppError):
        mirror_reads.require_run_data_access(run, "usr_viewer")
    assert checked == [("usr_viewer", "src_one"), ("usr_viewer", "src_two")]
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
    monkeypatch.setattr(mirror_reads, "authorize_source_data", forbidden)
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
    from backend.jobs.store import create_queued_job

    run = run_record()
    run.channel_id = "channel_one"
    job = create_queued_job(
        kind="channel_run", input={"channel_id": run.channel_id, "target": "draft"},
        trigger_kind="user", trigger_ref="usr_reader",
    )
    run.job_id = job.id
    monkeypatch.setattr(runs, "get_run_store", lambda: SimpleNamespace(
        get_run=lambda job_id: run if job_id == run.job_id else None,
    ))
    actor = SimpleNamespace(id="usr_viewer")
    calls = {
        "executions": lambda: runs.http_list_executions(run.channel_id, job.id, actor, page=PageParams(limit=10, offset=0)),
        "output": lambda: runs.http_execution_output(run.channel_id, job.id, 1, actor),
        "rounds": lambda: runs.http_execution_rounds(run.channel_id, job.id, 1, actor),
        "dataset": lambda: runs.http_dataset_rows(run.channel_id, job.id, "dataset_one", actor),
        "sample": lambda: runs.http_node_sample(run.channel_id, job.id, None, actor),
        "preview": lambda: runs.http_preview_template(run.channel_id, job.id, None, actor),
    }
    with pytest.raises(AppError) as error:
        calls[endpoint]()
    assert error.value.code == "AUTH_FORBIDDEN"


def test_release_response_loss_retains_evidence_until_acknowledged(monkeypatch):
    from backend.channel import tasks
    from backend.channel.run_store import ChannelRunRecord, get_run_store
    from backend.core.time import utc_now
    from backend.jobs.store import claim_queued, create_queued_job, get_job_store, mark_succeeded

    runs = get_run_store()
    job = create_queued_job(kind="channel_run", input={"on_demand_test": True, "pin_version": True},
                            trigger_kind="user", trigger_ref="u")
    claim_queued(job.id)
    assert mark_succeeded(job.id).status == "succeeded"
    state = {"pins": {"m": {"source_id": "s", "generation_id": "g"}}, "source_ids": ["s"]}
    run = ChannelRunRecord(
        job_id=job.id, channel_id="c", target="published", version=1, draft_revision=None,
        graph={"settings": {"keep_test_runs": False}}, trigger_node_id="t",
        ignore_checkpoints=False, outcome="completed",
        failed_node_id=None, skipped_node_ids=[], created_at=utc_now(), mirror_state=state,
        mirror_execution_user_id="u", mirror_pin_state="held",
    )
    runs.insert_run(run)
    monkeypatch.setattr(tasks, "channel_run_record_retention_days", lambda: 30)
    monkeypatch.setattr(tasks, "drop_orphan_dataset_tables", lambda: None)
    proofs = []

    def release(**kwargs):
        proofs.append(kwargs["terminal_proof"])
        if len(proofs) == 1:
            raise ConnectionError("lost reply")

    monkeypatch.setattr(mirror_reads, "_reads", SimpleNamespace(release_run_pins=release))
    with pytest.raises(ConnectionError):
        mirror_reads.release_completed_run(run)
    tasks.recovery.discard_unkept_run(job.id)
    assert runs.get_run(job.id).mirror_state == state
    assert not runs.get_run(job.id).can_discard
    tasks.purge_expired_run_records()
    assert proofs[0] == proofs[1]
    assert run.mirror_state == state
    assert run.mirror_pin_state == "released"
    assert runs.get_run(job.id) is None
    assert get_job_store().get(job.id) is None


def test_retry_of_known_mirror_keeps_other_uncertain_acquisition(monkeypatch):
    allow(monkeypatch)
    run = run_record()
    run.mirror_state = {"pins": {"known": {"generation_id": "g", "source_id": "s"}}, "source_ids": ["s"]}
    run.mirror_pin_state = "held"
    monkeypatch.setattr(mirror_reads, "get_run_store", lambda: SimpleNamespace(update_run=lambda _: None))
    requested = []

    def acquire(**kwargs):
        mirror_id = kwargs["mirror_id"]
        requested.append(mirror_id)
        if requested == ["pending"]:
            raise ConnectionError("target reply lost")
        return SimpleNamespace(run_id=run.job_id, mirror_id=mirror_id, generation_id="g", source_id="s")

    monkeypatch.setattr(mirror_reads, "_reads", SimpleNamespace(
        acquire_pin=acquire, read_page=lambda **kw: {"generation_id": "g", "source_ids": ["s"]},
    ))
    def read(mirror_id):
        return mirror_reads.read_run_page(run, mirror_id=mirror_id, after_key=None, limit=1)

    with pytest.raises(ConnectionError):
        read("pending")
    read("known")
    assert run.mirror_pin_state == "acquiring"
    assert run.pending_pin_mirror_id == "pending"
    with pytest.raises(mirror_reads.MirrorReadUnavailable):
        read("other")
    read("pending")
    assert requested == ["pending", "known", "pending"]
    assert run.mirror_pin_state == "held"
    assert run.pending_pin_mirror_id is None


@pytest.mark.parametrize("backend", ["memory", "sql"])
def test_terminal_ttl_retains_every_uncertain_pin_state(monkeypatch, backend):
    from contextlib import contextmanager
    from datetime import timedelta
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from backend.channel import run_store
    from backend.channel.models import ChannelRunRow
    from backend.core.time import utc_now

    states = {"history": "unused", "released": "released", "unknown": None,
              "held": "held", "acquiring": "acquiring"}
    cutoff = utc_now()
    if backend == "sql":
        from sqlalchemy.ext.compiler import compiles
        from sqlalchemy.dialects.postgresql import JSONB

        @compiles(JSONB, "sqlite")
        def json_type(element, compiler, **kw):
            return "JSON"

        engine = create_engine("sqlite://")
        ChannelRunRow.__table__.create(engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT)"))
            conn.execute(text("INSERT INTO jobs VALUES (:id, 'succeeded')"), [{"id": k} for k in states])

        @contextmanager
        def scope():
            with Session(engine) as session, session.begin():
                yield session

        monkeypatch.setattr(run_store, "session_scope", scope)
        runs = run_store.SqlRunStore()
    else:
        jobs = {name: SimpleNamespace(status="succeeded") for name in states}
        monkeypatch.setattr(run_store, "get_job_store", lambda: jobs)
        runs = run_store.MemoryRunStore()

    for job_id, pin_state in states.items():
        runs.insert_run(run_store.ChannelRunRecord(
            job_id=job_id, channel_id="c", target="published", version=1,
            draft_revision=None, graph={"nodes": []}, trigger_node_id="t", ignore_checkpoints=False,
            outcome="completed", failed_node_id=None, skipped_node_ids=[], created_at=cutoff-timedelta(days=5),
            mirror_state={"source_ids": ["s"]}, mirror_execution_user_id="u", mirror_pin_state=pin_state,
        ))
    assert runs.terminal_runs_with_pins() == ["held"]
    assert set(runs.job_ids_due(cutoff)) == {"history", "released"}
    assert runs.delete_expired_terminal_runs(cutoff) == 2
    for key in ("held", "unknown", "acquiring"):
        assert runs.get_run(key).mirror_state == {"source_ids": ["s"]}
