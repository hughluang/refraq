"""Mirror checkpoint settlement shares the caller's management transaction."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend.channel import checkpoints
from backend.tests.test_mirror_history import setup_history as setup_history


def mirror_run():
    return SimpleNamespace(
        channel_id="chn_a", outcome="completed", stop_at_node_id=None,
        mirror_execution_user_id="usr_a",
        checkpoint_proposals={
            "entity_node": {"ent_a": {"xact": 5, "seq": 1}},
            "mirror_node": {"mir_a": {
                "stream_kind": "mirror", "history_epoch": "epoch_a",
                "commit_seq": 12, "entry_seq": 2, "source_ids": ["src_a"],
            }},
        },
    )


def test_session_settlement_guards_all_before_any_checkpoint_write(monkeypatch):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def sqlite_syntax(connection, cursor, statement, parameters, context, many):
        return statement.replace(" FOR UPDATE", "").replace("CAST(? AS jsonb)", "?"), parameters

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE channel_checkpoints ("
            "channel_id TEXT, node_id TEXT, stream TEXT, position_xact BIGINT, "
            "position_seq BIGINT, stream_kind TEXT DEFAULT 'entity', history_epoch TEXT, "
            "source_ids JSON, updated_at TEXT, PRIMARY KEY(channel_id, node_id, stream))"))
    seen = []

    def guard(session, *, proposals, execution_user_id):
        assert session.in_transaction()
        assert execution_user_id == "usr_a"
        assert proposals == [{
            "mirror_id": "mir_a", "history_epoch": "epoch_a",
            "position": {"mirror_id": "mir_a", "history_epoch": "epoch_a", "commit_seq": 12, "entry_seq": 2},
            "source_ids": ["src_a"],
        }]
        assert session.scalar(text("SELECT count(*) FROM channel_checkpoints")) == 0
        seen.append(session)

    monkeypatch.setattr(checkpoints, "settlement_guard", guard)
    with Session(engine) as session:
        checkpoints.advance_from_run_in_session(session, mirror_run())
        assert seen == [session]
        assert session.scalar(text("SELECT count(*) FROM channel_checkpoints")) == 2
        row = session.execute(text("SELECT stream_kind, history_epoch, position_xact FROM channel_checkpoints WHERE stream='mir_a'")).one()
        assert tuple(row) == ("mirror", "epoch_a", 12)
        session.rollback()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM channel_checkpoints")) == 0


def test_guard_failure_never_advances_even_entity_proposals(monkeypatch):
    def deny(session, **kwargs):
        raise PermissionError("revoked")

    monkeypatch.setattr(checkpoints, "settlement_guard", deny)
    with Session(create_engine("sqlite://")) as session:
        with pytest.raises(PermissionError, match="revoked"):
            checkpoints.advance_from_run_in_session(session, mirror_run())
    assert checkpoints.get_checkpoint_store().read("chn_a", "entity_node", "ent_a") is None


def test_memory_mirror_settlement_fails_closed():
    with pytest.raises(ValueError, match="management transaction"):
        checkpoints.advance_from_run(mirror_run())
    assert checkpoints.get_checkpoint_store().read("chn_a", "entity_node", "ent_a") is None


@pytest.mark.parametrize("source_ids", [(), ("",)])
def test_mirror_position_rejects_unknown_provenance(source_ids):
    with pytest.raises(ValueError, match="provenance"):
        checkpoints.MirrorCheckpointPosition(
            history_epoch="epoch_a", commit_seq=1, entry_seq=1, source_ids=source_ids
        )


def test_unscoped_store_cannot_bypass_mirror_settlement():
    with pytest.raises(ValueError, match="management transaction"):
        checkpoints.get_checkpoint_store().advance(
            "chn_a", "node_a", "mir_a",
            checkpoints.MirrorCheckpointPosition(
                history_epoch="epoch_a", commit_seq=1, entry_seq=1, source_ids=("src_a",)
            ),
        )


def test_missing_mirror_identity_denies_before_guard_or_updates():
    run = mirror_run()
    run.mirror_execution_user_id = None
    with pytest.raises(ValueError, match="explicit execution identity"):
        checkpoints.advance_from_run_in_session(None, run)


def test_mirror_proposals_round_trip_without_entity_xact():
    position = checkpoints.MirrorCheckpointPosition(
        history_epoch="epoch_a", commit_seq=12, entry_seq=2, source_ids=("src_a",)
    )
    local = checkpoints.LocalCheckpoints()
    local.propose("node_a", "mir_a", position)
    assert local.proposed("node_a", "mir_a") == position
    with pytest.raises(ValueError, match="epoch"):
        local.propose(
            "node_a", "mir_a",
            checkpoints.MirrorCheckpointPosition(
                history_epoch="epoch_b", commit_seq=13, entry_seq=1, source_ids=("src_a",)
            ),
        )


def test_mirror_run_proposals_retain_epoch_and_provenance(monkeypatch):
    saved = []
    monkeypatch.setattr(
        checkpoints, "get_run_store",
        lambda: SimpleNamespace(set_checkpoint_proposals=lambda job_id, blob: saved.append(blob)),
    )
    run = SimpleNamespace(job_id="job_a", checkpoint_proposals=None)
    positions = checkpoints.RunCheckpoints("chn_a", run)
    positions.propose(
        "node_a", "mir_a",
        checkpoints.MirrorCheckpointPosition(
            history_epoch="epoch_a", commit_seq=12, entry_seq=2, source_ids=("src_a",)
        ),
    )
    assert saved == [{"node_a": {"mir_a": {
        "stream_kind": "mirror", "history_epoch": "epoch_a",
        "commit_seq": 12, "entry_seq": 2, "source_ids": ["src_a"],
    }}}]
    restored = checkpoints.RunCheckpoints("chn_a", run)
    assert restored.proposed("node_a", "mir_a") == positions.proposed("node_a", "mir_a")


@pytest.fixture
def worker_history(setup_history, monkeypatch):
    from backend.channel import channel_run, mirror_reads, runner

    history, factory, target, auth = setup_history
    monkeypatch.setattr(channel_run, "authorize_graph", lambda *args, **kw: None)
    monkeypatch.setattr(runner, "authorize_graph", lambda *args, **kw: None)
    monkeypatch.setattr(mirror_reads, "_reads", object())
    monkeypatch.setattr(mirror_reads, "_authorize", lambda *_: None)
    monkeypatch.setattr(mirror_reads, "authorize_source_data", history.authorize_source_read)
    monkeypatch.setattr(mirror_reads, "capture_bound", history.capture_bound)
    monkeypatch.setattr(mirror_reads, "read_incremental", history.read_incremental)
    monkeypatch.setattr(checkpoints, "settlement_guard", history.settlement_guard)
    return factory, target, auth


def publish_incremental_graph(*, second_policy=None, second_type="read.changes"):
    from backend.tests.test_channel_recovery import _graph, _node, _publish

    graph = _graph("return {}", limit=0, error_channel_id=None)
    graph["nodes"][1] = _node("nd_code", "first", "read.changes", {"source": {"kind": "mirror", "mirror_id": "a"}})
    if second_policy is not None:
        second = _node("nd_second", "second", second_type, {"source": {"kind": "mirror", "mirror_id": "b"}})
        graph["nodes"].append({**second, "on_error": second_policy})
        graph["edges"].append({"id": "ed_first_second", "source": {"node_id": "nd_code", "port": "main"},
                               "target": {"node_id": "nd_second", "port": "main"}})
    return _publish("Incremental checkpoint settlement", graph)


@pytest.mark.parametrize("policy", ["continue", "error_output"])
@pytest.mark.parametrize("second_type", ["read.changes", "volume.changes_dataset"])
@pytest.mark.parametrize("failure,expected_code", [
    ("invalidation", "MIRROR_HISTORY_INVALID"),
    ("outage", "MIRROR_READ_UNAVAILABLE"),
    ("revocation", "AUTH_FORBIDDEN"),
    ("durable_lineage", "CHANNEL_CHECKPOINT_INVALID"),
])
def test_mirror_history_failure_blocks_settlement(worker_history, monkeypatch, policy, second_type, failure, expected_code):
    from backend.channel import runner
    from backend.channel.run_store import get_run_store
    from backend.jobs.store import get_job_store
    from backend.metadata.mirrors.history_models import HistoryGateRow
    from backend.tests.test_channel_recovery import _run_published

    factory, target, auth = worker_history
    if failure == "invalidation":
        with factory.begin() as session:
            session.get(HistoryGateRow, "b").status = "invalidating"
    elif failure == "durable_lineage":
        monkeypatch.setattr(checkpoints.RunCheckpoints, "durable", lambda self, node_id, stream: (
            checkpoints.MirrorCheckpointPosition("old_epoch", 0, 0, ("source",)) if stream == "b" else None
        ))
    else:
        original_read = target.read_incremental

        def read(**kwargs):
            page = original_read(**kwargs)
            target.fail = failure == "outage"
            auth["allowed"] = failure != "revocation"
            return page

        monkeypatch.setattr(target, "read_incremental", read)
    settlements = []
    monkeypatch.setattr(runner, "complete_mirror_success", lambda *args: settlements.append(args))
    channel = publish_incremental_graph(second_policy=policy, second_type=second_type)
    job_id = _run_published(channel)

    run = get_run_store().get_run(job_id)
    assert "a" in run.checkpoint_proposals["nd_code"]
    assert run.failed_node_id == "nd_second"
    assert get_job_store().get(job_id).error_code == expected_code
    assert get_run_store().get_execution(job_id, 3).output is None
    assert not settlements


@pytest.mark.parametrize("failure,expected_code", [
    ("invalidation", "MIRROR_HISTORY_INVALID"),
    ("retention", "MIRROR_HISTORY_INVALID"),
    ("outage", "MIRROR_READ_UNAVAILABLE"),
    ("revocation", "AUTH_FORBIDDEN"),
    ("durable_lineage", "CHANNEL_CHECKPOINT_INVALID"),
])
def test_final_settlement_preserves_failure_and_rolls_back(worker_history, monkeypatch, failure, expected_code):
    from backend.channel import runner
    from backend.channel.run_store import get_run_store
    from backend.jobs.store import get_job_store
    from backend.metadata.mirrors.history_models import HistoryGateRow
    from backend.tests.test_channel_recovery import _run_published

    factory, target, auth = worker_history
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def sqlite_syntax(connection, cursor, statement, parameters, context, many):
        return statement.replace(" FOR UPDATE", "").replace("CAST(? AS jsonb)", "?"), parameters

    with factory.begin() as session:
        session.execute(text("CREATE TABLE job_success (job_id TEXT PRIMARY KEY)"))
        session.execute(text("CREATE TABLE channel_checkpoints (channel_id TEXT, node_id TEXT, "
                             "stream TEXT, stream_kind TEXT, history_epoch TEXT, source_ids JSON, "
                             "position_xact BIGINT, position_seq BIGINT, updated_at TEXT, "
                             "PRIMARY KEY(channel_id, node_id, stream))"))

    channel = publish_incremental_graph(second_policy="stop" if failure == "durable_lineage" else None)
    if failure == "durable_lineage":
        with factory.begin() as session:
            session.execute(text("INSERT INTO channel_checkpoints "
                                 "(channel_id, node_id, stream, stream_kind, history_epoch, source_ids) "
                                 "VALUES (:channel, 'nd_second', 'b', 'mirror', 'old_epoch', :sources)"),
                            {"channel": channel.id, "sources": '["source"]'})

    scope_calls = []
    earlier_writes = []

    @event.listens_for(engine, "after_cursor_execute")
    def record_checkpoint_write(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO channel_checkpoints"):
            earlier_writes.append(cursor.rowcount)

    def settlement_scope():
        scope_calls.append("settlement")
        with factory.begin() as session:
            gate = session.get(HistoryGateRow, "a")
            if failure == "invalidation":
                gate.status = "invalidating"
            elif failure == "retention":
                gate.lower_commit_seq = 3
                target.bounds["a"]["lower_bound"]["commit_seq"] = 3
                target.bounds["a"]["upper_bound"]["commit_seq"] = 3
        target.fail = failure == "outage"
        auth["allowed"] = failure != "revocation"
        return factory.begin()

    def record_success(job_id, *, result, session):
        session.execute(text("INSERT INTO job_success VALUES (:job_id)"), {"job_id": job_id})
        return SimpleNamespace(status="succeeded")

    monkeypatch.setattr(runner, "session_scope", settlement_scope)
    monkeypatch.setattr(runner, "mark_succeeded", record_success)
    job_id = _run_published(channel)

    assert scope_calls == ["settlement"]
    read = get_run_store().get_execution(job_id, 2)
    assert read.status == "succeeded"
    assert read.output["count"] == 1
    job = get_job_store().get(job_id)
    assert job.status == "failed"
    assert job.error_code == expected_code
    assert earlier_writes == ([1] if failure == "durable_lineage" else [])
    with factory.begin() as session:
        assert session.scalar(text("SELECT count(*) FROM job_success")) == 0
        rows = list(session.execute(text("SELECT stream, history_epoch FROM channel_checkpoints")))
        assert rows == ([("b", "old_epoch")] if failure == "durable_lineage" else [])
