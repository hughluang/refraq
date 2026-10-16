"""Channel Run minting through HTTP and the Beat due-tick task."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.channel_run import set_dispatcher  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.schedules import fire_scheduled_channel_run  # noqa: E402
from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock  # noqa: E402
from backend.jobs.store import get_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.worker.schedules import get_schedule_store  # noqa: E402

NOW = parse_instant("2026-08-15T02:00:05Z")
SLOT = parse_instant("2026-08-15T02:00:00Z")
EARLIER = parse_instant("2026-08-14T02:00:00Z")

MANUAL_GRAPH = {
    "nodes": [
        {
            "id": "nd_trigger",
            "ref": "run_manually",
            "type": "trigger.manual",
            "name": "Run manually",
            "position": {"x": 0, "y": 0},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}

SCHEDULED_GRAPH = {
    "nodes": [
        {
            "id": "nd_hourly",
            "ref": "hourly",
            "type": "trigger.scheduled",
            "name": "Hourly",
            "position": {"x": 0, "y": 0},
            "config": {"cron": "0 * * * *", "interval_seconds": None, "start_at": None},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": 60, "error_channel_id": None},
}


def _login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"account": "admin", "password": "secret"})
    assert response.status_code == 200, response.text


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        _login(test_client)
        yield test_client


@pytest.fixture()
def dispatched() -> list[str]:
    calls: list[str] = []

    def _capture(job_id: str) -> None:
        calls.append(job_id)

    previous = set_dispatcher(_capture)
    try:
        yield calls
    finally:
        set_dispatcher(previous)


def _save_draft(client: TestClient, channel_id: str, graph: dict) -> int:
    current = client.get(f"/channels/{channel_id}/draft")
    assert current.status_code == 200, current.text
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": current.json()["draft_revision"], "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    return int(saved.json()["draft_revision"])


def _activated_schedule(client: TestClient) -> tuple[str, str]:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    revision = _save_draft(client, channel_id, SCHEDULED_GRAPH)
    published = client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": revision}
    )
    assert published.status_code == 201, published.text
    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    row = get_schedule_store().get_by_key(f"channel_run:{channel_id}")
    assert row is not None
    assert row.enabled is True
    return channel_id, row.id


def _rewind_last_run(schedule_id: str) -> None:
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    get_schedule_store().upsert(replace(record, last_run_at=EARLIER))


def _fire(schedule_id: str, channel_id: str) -> dict[str, str]:
    return fire_scheduled_channel_run(
        schedule_id=schedule_id,
        due_at=SLOT,
        channel_id=channel_id,
        node_id="nd_hourly",
    )


def test_due_tick_mints_one_queued_channel_run_and_dispatches_once(
    client: TestClient, dispatched: list[str]
) -> None:
    set_clock(FixedClock(NOW))
    try:
        channel_id, schedule_id = _activated_schedule(client)
        minted = _fire(schedule_id, channel_id)
    finally:
        reset_clock()

    assert minted["status"] == "queued"
    jobs, _total = get_job_store().list(kind="channel_run", trigger_ref=schedule_id)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.status == "queued"
    assert job.id == minted["job_id"]
    assert job.input == {
        "channel_id": channel_id,
        "target": "published",
        "ignore_checkpoints": False,
    }
    assert job.summary == f"channel_run {channel_id}"
    assert job.trigger_kind == "schedule"
    assert job.trigger_ref == schedule_id
    assert job.created_by is None
    assert job.scheduled_for == SLOT
    assert job.running_timeout_sec is None
    assert job.log_body == "2026-08-15T02:00:05Z INFO queued channel run"
    assert job.created_at == NOW

    runs, total = get_run_store().list_runs(
        channel_id, status=None, target=None, limit=10, offset=0
    )
    assert total == 1
    record = runs[0]
    assert record.job_id == job.id
    assert record.channel_id == channel_id
    assert record.target == "published"
    assert record.version is None
    assert record.draft_revision is None
    assert record.graph is None
    assert record.trigger_node_id == "nd_hourly"
    assert record.ignore_checkpoints is False
    assert record.outcome is None
    assert record.failed_node_id is None
    assert record.skipped_node_ids == []
    assert record.stop_at_node_id is None
    assert record.created_at == NOW
    assert dispatched == [job.id]

    set_clock(FixedClock(NOW))
    try:
        again = _fire(schedule_id, channel_id)
    finally:
        reset_clock()
    assert again["status"] == "skip_cross_slot"
    jobs_after, _ = get_job_store().list(kind="channel_run", trigger_ref=schedule_id)
    assert [item.id for item in jobs_after] == [job.id]
    runs_after, total_after = get_run_store().list_runs(
        channel_id, status=None, target=None, limit=10, offset=0
    )
    assert total_after == 1
    assert runs_after[0].job_id == job.id
    assert dispatched == [job.id]


def test_redelivered_tick_redispatches_a_queued_job_only_while_enabled(
    client: TestClient, dispatched: list[str]
) -> None:
    set_clock(FixedClock(NOW))
    try:
        channel_id, schedule_id = _activated_schedule(client)
        minted = _fire(schedule_id, channel_id)
        assert minted["status"] == "queued"
        job_id = minted["job_id"]

        _rewind_last_run(schedule_id)
        redelivered = _fire(schedule_id, channel_id)
        assert redelivered == {"status": "already_minted", "job_id": job_id}
        jobs, _ = get_job_store().list(kind="channel_run", trigger_ref=schedule_id)
        assert [job.id for job in jobs] == [job_id]
        assert jobs[0].status == "queued"
        _runs, total = get_run_store().list_runs(
            channel_id, status=None, target=None, limit=10, offset=0
        )
        assert total == 1
        assert dispatched == [job_id, job_id]

        disabled = client.post(f"/channels/{channel_id}/deactivate")
        assert disabled.status_code == 200, disabled.text
        _rewind_last_run(schedule_id)
        while_disabled = _fire(schedule_id, channel_id)
    finally:
        reset_clock()

    assert while_disabled["status"] == "cancelled"
    assert while_disabled["job_id"] == job_id
    stored = get_job_store().get(job_id)
    assert stored is not None
    assert stored.status == "cancelled"
    jobs_after, _ = get_job_store().list(kind="channel_run", trigger_ref=schedule_id)
    assert [job.id for job in jobs_after] == [job_id]
    _runs_after, total_after = get_run_store().list_runs(
        channel_id, status=None, target=None, limit=10, offset=0
    )
    assert total_after == 1
    assert dispatched == [job_id, job_id]


def test_on_demand_run_persists_draft_and_published_records_and_dispatches_once(
    client: TestClient, dispatched: list[str]
) -> None:
    actor = get_user_store().get_by_account("admin")
    assert actor is not None
    set_clock(FixedClock(NOW))
    try:
        created = client.post("/channels", json={"name": "Material", "description": None})
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        revision = _save_draft(client, channel_id, MANUAL_GRAPH)
        draft = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
        assert draft.status_code == 202, draft.text
        published_version = client.post(
            f"/channels/{channel_id}/publish", json={"draft_revision": revision}
        )
        assert published_version.status_code == 201, published_version.text
        published = client.post(
            f"/channels/{channel_id}/runs", json={"target": "published"}
        )
        assert published.status_code == 202, published.text
    finally:
        reset_clock()

    draft_body = draft.json()["run"]
    published_body = published.json()["run"]
    assert draft_body["status"] == "queued"
    assert draft_body["target"] == "draft"
    assert draft_body["version"] is None
    assert draft_body["draft_revision"] == revision
    assert draft_body["trigger_node_id"] == "nd_trigger"
    assert draft_body["trigger_kind"] == "user"
    assert draft_body["trigger_ref"] == actor.id
    assert draft_body["ignore_checkpoints"] is False
    assert draft_body["stop_at_node_id"] is None
    assert draft_body["created_at"] == "2026-08-15T02:00:05Z"
    assert published_body["status"] == "queued"
    assert published_body["target"] == "published"
    assert published_body["version"] == 1
    assert published_body["draft_revision"] is None
    assert published_body["trigger_node_id"] == "nd_trigger"
    assert published_body["ignore_checkpoints"] is False
    assert published_body["stop_at_node_id"] is None
    assert published_body["created_at"] == "2026-08-15T02:00:05Z"

    draft_detail = client.get(f"/channels/{channel_id}/runs/{draft_body['job_id']}")
    assert draft_detail.status_code == 200, draft_detail.text
    assert draft_detail.json()["graph"] == {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "run_manually",
                "type": "trigger.manual",
                "name": "Run manually",
                "position": {"x": 0.0, "y": 0.0},
                "config": {},
                "on_error": "stop",
                "retry": None,
                "type_version": 1,
            }
        ],
        "edges": [],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    published_detail = client.get(
        f"/channels/{channel_id}/runs/{published_body['job_id']}"
    )
    assert published_detail.status_code == 200, published_detail.text
    assert published_detail.json()["graph"] is None

    jobs, _total = get_job_store().list(kind="channel_run")
    by_id = {job.id: job for job in jobs}
    assert set(by_id) == {draft_body["job_id"], published_body["job_id"]}
    for target, body in (("draft", draft_body), ("published", published_body)):
        job = by_id[body["job_id"]]
        assert job.status == "queued"
        assert job.input == {
            "channel_id": channel_id,
            "target": target,
            "ignore_checkpoints": False,
            "stop_at_node_id": None,
        }
        assert job.summary == "channel_run Material"
        assert job.trigger_kind == "user"
        assert job.trigger_ref == actor.id
        assert job.created_by == actor.id
        assert job.scheduled_for is None
        assert job.log_body == ""
        record = get_run_store().get_run(job.id)
        assert record is not None
        assert record.created_at == NOW
        assert record.outcome is None
        assert record.failed_node_id is None
        assert record.skipped_node_ids == []
    assert dispatched == [draft_body["job_id"], published_body["job_id"]]
