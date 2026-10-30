"""Checkpoint advance is the greater position, and only a completed run moves it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.channel.checkpoints import (
    CheckpointPosition,
    RunCheckpoints,
    advance_from_run,
    get_checkpoint_store,
)
from backend.channel.recovery import settle_success
from backend.channel.service import create_channel, delete_channel


def test_a_later_advance_does_not_move_the_cursor_backwards() -> None:
    store = get_checkpoint_store()
    high = CheckpointPosition(xact=4, seq=1)
    low = CheckpointPosition(xact=3, seq=99)
    store.advance("chn_a", "nd_read", "ent_a", high)
    store.advance("chn_a", "nd_read", "ent_a", low)
    assert store.read("chn_a", "nd_read", "ent_a") == high


def test_a_completed_draft_run_advances_and_a_stopped_run_does_not() -> None:
    completed = SimpleNamespace(
        channel_id="chn_b",
        target="draft",
        outcome="completed",
        stop_at_node_id=None,
        checkpoint_proposals={"nd_read": {"ent_b": {"xact": 8, "seq": 2}}},
    )
    settle_success(completed)
    assert get_checkpoint_store().read(
        "chn_b", "nd_read", "ent_b"
    ) == CheckpointPosition(xact=8, seq=2)

    stopped = SimpleNamespace(
        channel_id="chn_b",
        target="draft",
        outcome="completed",
        stop_at_node_id="nd_read",
        checkpoint_proposals={"nd_read": {"ent_b": {"xact": 9, "seq": 1}}},
    )
    settle_success(stopped)
    assert get_checkpoint_store().read(
        "chn_b", "nd_read", "ent_b"
    ) == CheckpointPosition(xact=8, seq=2)


def test_a_failed_or_cancelled_outcome_leaves_the_cursor() -> None:
    store = get_checkpoint_store()
    store.advance("chn_c", "nd_read", "ent_c", CheckpointPosition(xact=1, seq=1))
    for outcome in ("failed", "cancelled", None):
        settle_success(
            SimpleNamespace(
                channel_id="chn_c",
                target="published",
                outcome=outcome,
                stop_at_node_id=None,
                checkpoint_proposals={"nd_read": {"ent_c": {"xact": 5, "seq": 1}}},
            )
        )
    assert store.read("chn_c", "nd_read", "ent_c") == CheckpointPosition(xact=1, seq=1)


def test_a_proposal_for_a_missing_run_fails() -> None:
    run = SimpleNamespace(job_id="job_missing", checkpoint_proposals=None)
    session = RunCheckpoints("chn_missing", run)
    with pytest.raises(RuntimeError, match="job_missing"):
        session.propose("nd_read", "ent_missing", CheckpointPosition(xact=1, seq=1))


def test_deleting_a_channel_drops_its_checkpoints() -> None:
    channel = create_channel(
        name="Reads changes",
        description=None,
        actor_user_id="usr_test",
        actor_token_id=None,
    )
    get_checkpoint_store().advance(
        channel.id, "nd_read", "ent_d", CheckpointPosition(xact=2, seq=3)
    )
    delete_channel(
        channel_id=channel.id,
        actor_user_id="usr_test",
        actor_token_id=None,
    )
    assert get_checkpoint_store().read(channel.id, "nd_read", "ent_d") is None
