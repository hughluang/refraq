"""Focused tests for GraphSettings concurrency='forbid' and per-channel run locks."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.channel.channel_run import mint_on_demand_run, set_dispatcher
from backend.channel.locks import (
    reset_channel_run_locks_for_tests,
    try_acquire_channel_run_lock,
)
from backend.channel.recovery import settle_success
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.channel.runner import run_channel_job
from backend.channel.schemas.channels import GraphSettingsIn
from backend.channel.store import ChannelRecord, get_channel_store, reset_channel_store
from backend.core.config import reset_settings_cache
from backend.jobs.store import get_job_store, reset_job_store
from backend.worker.parameters import assemble_system_parameters


@pytest.fixture(autouse=True)
def _memory_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    assemble_system_parameters()
    reset_channel_store()
    reset_job_store()
    reset_channel_run_locks_for_tests()
    set_dispatcher(lambda *args, **kwargs: None)
    yield
    set_dispatcher(None)
    reset_channel_run_locks_for_tests()
    reset_job_store()
    reset_channel_store()
    reset_settings_cache()


def test_graph_settings_defaults_concurrency_to_allow() -> None:
    assert GraphSettingsIn().concurrency == "allow"
    assert GraphSettingsIn(concurrency="forbid").concurrency == "forbid"


def test_forbid_skips_overlapping_run_and_preserves_failure_streak() -> None:
    now = datetime.now(timezone.utc)
    graph = {
        "nodes": [
            {
                "id": "nd_trig",
                "ref": "trig",
                "type": "trigger.manual",
                "name": "Manual",
                "position": {"x": 0, "y": 0},
                "config": {},
            }
        ],
        "edges": [],
        "settings": {"concurrency": "forbid"},
    }
    channel = get_channel_store().create(
        ChannelRecord(
            id="chn_conc",
            name="Concurrent",
            description=None,
            active=True,
            draft_graph=graph,
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
            failure_streak=2,
        )
    )
    job, _run = mint_on_demand_run(
        channel_id=channel.id,
        channel_name=channel.name,
        target="draft",
        ignore_checkpoints=False,
        actor_id="usr_admin",
        trigger_node_id="nd_trig",
        version=None,
        draft_revision=1,
        graph=graph,
        stop_at_node_id=None,
    )
    job_id = job.id

    held = try_acquire_channel_run_lock("chn_conc")
    assert held is not None
    try:
        assert try_acquire_channel_run_lock("chn_conc") is None
        outcome = run_channel_job(job_id)
        assert outcome == {"status": "succeeded"}
        finished = get_job_store().get(job_id)
        assert finished is not None
        assert finished.result["outcome"] == "skipped"
        run = get_run_store().get_run(job_id)
        assert run is not None
        assert run.outcome == "skipped"
        updated = get_channel_store().get("chn_conc")
        assert updated is not None
        assert updated.failure_streak == 2
    finally:
        held.release()

    reacquired = try_acquire_channel_run_lock("chn_conc")
    assert reacquired is not None
    reacquired.release()


def test_settle_success_only_clears_failure_streak_on_completed() -> None:
    now = datetime.now(timezone.utc)
    get_channel_store().create(
        ChannelRecord(
            id="chn_streak",
            name="Streak",
            description=None,
            active=True,
            draft_graph={"nodes": [], "edges": [], "settings": {}},
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
            failure_streak=2,
        )
    )
    skipped_run = ChannelRunRecord(
        job_id="job_skip",
        channel_id="chn_streak",
        target="published",
        version=1,
        draft_revision=None,
        graph={"nodes": [], "edges": [], "settings": {}},
        trigger_node_id="nd_trig",
        ignore_checkpoints=False,
        outcome="skipped",
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=now,
    )
    settle_success(skipped_run)
    assert get_channel_store().get("chn_streak").failure_streak == 2

    completed_run = ChannelRunRecord(
        job_id="job_ok",
        channel_id="chn_streak",
        target="published",
        version=1,
        draft_revision=None,
        graph={"nodes": [], "edges": [], "settings": {}},
        trigger_node_id="nd_trig",
        ignore_checkpoints=False,
        outcome="completed",
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=now,
    )
    settle_success(completed_run)
    assert get_channel_store().get("chn_streak").failure_streak == 0
