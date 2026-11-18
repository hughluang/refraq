"""Mirror checkpoint settlement shares the caller's management transaction."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend.channel import checkpoints


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
