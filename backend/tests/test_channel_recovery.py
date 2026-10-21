"""Pinned versions, published retry jobs, error workflows, and failure streak."""

from __future__ import annotations

import os

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.channel.channel_run import mint_followup_run, mint_on_demand_run, set_dispatcher
from backend.channel.ids import new_channel_id
from backend.channel.runner import run_channel_job
from backend.channel.run_store import get_run_store
from backend.channel.store import ChannelRecord, get_channel_store
from backend.core.time import utc_now
from backend.jobs.store import get_job_store
from backend.worker.parameters import assemble_system_parameters

assemble_system_parameters()


def _node(node_id: str, ref: str, node_type: str, config: dict) -> dict:
    return {
        "id": node_id,
        "ref": ref,
        "type": node_type,
        "name": ref,
        "position": {"x": 0, "y": 0},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }


def _graph(code: str, *, limit: int | None, error_channel_id: str | None) -> dict:
    return {
        "nodes": [
            _node("nd_trigger", "start", "trigger.manual", {"payload": {}}),
            _node("nd_code", "work", "transform.code", {"code": code, "timeout_sec": 30}),
        ],
        "edges": [
            {
                "id": "ed_start_work",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_code", "port": "main"},
            }
        ],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": limit,
            "error_channel_id": error_channel_id,
        },
    }


def _error_graph() -> dict:
    return {
        "nodes": [_node("nd_error", "failed_run", "trigger.error", {})],
        "edges": [],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }


def _publish(name: str, graph: dict, *, active: bool = True) -> ChannelRecord:
    now = utc_now()
    store = get_channel_store()
    created = store.create(
        ChannelRecord(
            id=new_channel_id(),
            name=name,
            description=None,
            active=False,
            draft_graph={"nodes": [], "edges": [], "settings": {}},
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    drafted = store.replace_draft(
        created.id, base_revision=1, graph=graph, now=utc_now()
    )
    store.publish_version(
        created.id,
        draft_revision=drafted.draft_revision,
        published_at=utc_now(),
        published_by_user_id="usr_test",
    )
    record = store.get(created.id)
    assert record is not None
    record.active = active
    return store.save(record)


def _republish(channel_id: str, graph: dict) -> None:
    store = get_channel_store()
    current = store.get(channel_id)
    assert current is not None
    drafted = store.replace_draft(
        channel_id,
        base_revision=current.draft_revision,
        graph=graph,
        now=utc_now(),
    )
    store.publish_version(
        channel_id,
        draft_revision=drafted.draft_revision,
        published_at=utc_now(),
        published_by_user_id="usr_test",
    )


def _run_published(channel: ChannelRecord) -> str:
    job, _record = mint_on_demand_run(
        channel_id=channel.id,
        channel_name=channel.name,
        target="published",
        ignore_checkpoints=False,
        actor_id="usr_author",
        trigger_node_id="nd_trigger",
        version=None,
        draft_revision=None,
        graph=None,
        stop_at_node_id=None,
    )
    assert run_channel_job(job.id)["status"] in {"succeeded", "failed", "cancelled"}
    return job.id


def _jobs(channel_id: str, trigger_kind: str) -> list:
    rows, _total = get_job_store().list(kind="channel_run", trigger_kind=trigger_kind)
    return [row for row in rows if (row.input or {}).get("channel_id") == channel_id]


def test_pinned_run_keeps_its_version_when_a_newer_one_is_published() -> None:
    channel = _publish("Pin", _graph("return {'n': 1}", limit=0, error_channel_id=None))
    _republish(channel.id, _graph("return {'n': 2}", limit=0, error_channel_id=None))
    job, _record = mint_followup_run(
        channel_id=channel.id,
        channel_name=channel.name,
        trigger_kind="retry",
        trigger_ref="job_origin",
        trigger_node="nd_trigger",
        version=1,
        job_input={
            "channel_id": channel.id,
            "target": "published",
            "ignore_checkpoints": False,
            "pin_version": True,
            "version": 1,
            "retry_of_job_id": "job_origin",
        },
    )
    assert run_channel_job(job.id) == {"status": "succeeded"}
    run = get_run_store().get_run(job.id)
    assert run is not None and run.version == 1
    outputs = [
        item.output
        for item in get_run_store().list_executions(job.id)
        if item.node_id == "nd_code"
    ]
    assert outputs == [{"n": 1}]


def test_missing_pinned_version_cancels_the_run() -> None:
    channel = _publish("Missing pin", _graph("return {'n': 1}", limit=0, error_channel_id=None))
    job, _record = mint_followup_run(
        channel_id=channel.id,
        channel_name=channel.name,
        trigger_kind="retry",
        trigger_ref="job_origin",
        trigger_node="nd_trigger",
        version=9,
        job_input={
            "channel_id": channel.id,
            "target": "published",
            "ignore_checkpoints": False,
            "pin_version": True,
            "version": 9,
            "retry_of_job_id": "job_origin",
        },
    )
    assert run_channel_job(job.id) == {"status": "cancelled"}
    followups, _total = get_job_store().list(kind="channel_run", trigger_ref=job.id)
    assert followups == []


def test_retry_budget_holds_the_error_workflow_until_the_last_failure() -> None:
    calls: list[str] = []
    previous = set_dispatcher(calls.append)
    try:
        error = _publish("On error", _error_graph())
        channel = _publish(
            "Retries",
            _graph("raise RuntimeError('boom')", limit=1, error_channel_id=error.id),
        )
        first = _run_published(channel)
        retries = _jobs(channel.id, "retry")
        assert len(retries) == 1
        assert retries[0].input["pin_version"] is True
        assert retries[0].input["version"] == 1
        assert retries[0].input["retry_of_job_id"] == first
        assert _jobs(error.id, "error") == []
        assert get_channel_store().get(channel.id).failure_streak == 0
        assert run_channel_job(retries[0].id) == {"status": "failed"}
        started = _jobs(error.id, "error")
        assert len(started) == 1
        source = started[0].input["error_source"]
        assert source["channel_id"] == channel.id
        assert source["job_id"] == retries[0].id
        assert source["version"] == 1
        assert source["attempt"] == 2
        assert source["error"]["code"] == "CHANNEL_NODE_FAILED"
        assert source["error"]["node_id"] == "nd_code"
        assert run_channel_job(started[0].id) == {"status": "succeeded"}
        trigger_output = [
            item.output
            for item in get_run_store().list_executions(started[0].id)
            if item.node_id == "nd_error"
        ]
        assert trigger_output == [source]
        assert get_channel_store().get(channel.id).failure_streak == 1
        assert get_channel_store().get(channel.id).active is True
    finally:
        set_dispatcher(previous)


def test_error_run_does_not_start_another_run() -> None:
    calls: list[str] = []
    previous = set_dispatcher(calls.append)
    try:
        error = _publish("Loop", _error_graph())
        _republish(
            error.id,
            {
                "nodes": [
                    _node("nd_error", "failed_run", "trigger.error", {}),
                    _node(
                        "nd_code",
                        "work",
                        "transform.code",
                        {"code": "raise RuntimeError('boom')", "timeout_sec": 30},
                    ),
                ],
                "edges": [
                    {
                        "id": "ed_error_work",
                        "source": {"node_id": "nd_error", "port": "main"},
                        "target": {"node_id": "nd_code", "port": "main"},
                    }
                ],
                "settings": {
                    "run_timeout_sec": None,
                    "run_retry_limit": 2,
                    "error_channel_id": error.id,
                },
            },
        )
        source = _publish("Source", _graph("return {'n': 1}", limit=0, error_channel_id=None))
        job, _record = mint_followup_run(
            channel_id=error.id,
            channel_name=error.name,
            trigger_kind="error",
            trigger_ref="job_source",
            trigger_node="nd_error",
            version=None,
            job_input={
                "channel_id": error.id,
                "target": "published",
                "ignore_checkpoints": False,
                "error_source": {"channel_id": source.id, "job_id": "job_source"},
            },
        )
        assert run_channel_job(job.id) == {"status": "failed"}
        followups, _total = get_job_store().list(kind="channel_run", trigger_ref=job.id)
        assert followups == []
        assert get_channel_store().get(source.id).failure_streak == 0
    finally:
        set_dispatcher(previous)


def test_three_published_failures_mark_the_streak_and_success_clears_it() -> None:
    calls: list[str] = []
    previous = set_dispatcher(calls.append)
    try:
        channel = _publish(
            "Streak",
            _graph("raise RuntimeError('boom')", limit=0, error_channel_id=None),
        )
        for _ in range(3):
            _run_published(channel)
        record = get_channel_store().get(channel.id)
        assert record is not None
        assert record.failure_streak == 3
        assert record.active is True
        _republish(channel.id, _graph("return {'ok': True}", limit=0, error_channel_id=None))
        assert run_channel_job(
            mint_on_demand_run(
                channel_id=channel.id,
                channel_name=channel.name,
                target="published",
                ignore_checkpoints=False,
                actor_id="usr_author",
                trigger_node_id="nd_trigger",
                version=None,
                draft_revision=None,
                graph=None,
                stop_at_node_id=None,
            )[0].id
        ) == {"status": "succeeded"}
        cleared = get_channel_store().get(channel.id)
        assert cleared is not None and cleared.failure_streak == 0
    finally:
        set_dispatcher(previous)


def test_draft_failure_starts_the_error_workflow_without_a_retry_or_streak() -> None:
    calls: list[str] = []
    previous = set_dispatcher(calls.append)
    try:
        error = _publish("Draft errors", _error_graph())
        now = utc_now()
        channel = get_channel_store().create(
            ChannelRecord(
                id=new_channel_id(),
                name="Draft",
                description=None,
                active=False,
                draft_graph=_graph(
                    "raise RuntimeError('boom')", limit=2, error_channel_id=error.id
                ),
                draft_revision=1,
                draft_updated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        job, _record = mint_on_demand_run(
            channel_id=channel.id,
            channel_name=channel.name,
            target="draft",
            ignore_checkpoints=False,
            actor_id="usr_author",
            trigger_node_id="nd_trigger",
            version=None,
            draft_revision=1,
            graph=channel.draft_graph,
            stop_at_node_id=None,
        )
        assert run_channel_job(job.id) == {"status": "failed"}
        assert _jobs(channel.id, "retry") == []
        started = _jobs(error.id, "error")
        assert len(started) == 1
        assert started[0].trigger_ref == job.id
        saved = get_channel_store().get(channel.id)
        assert saved is not None and saved.failure_streak == 0
    finally:
        set_dispatcher(previous)
