"""Scheduled Task operator API and schedule-layer tests."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.source_jobs import fire_scheduled_structure  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.api import ensure_system_schedules, schedule_out  # noqa: E402
from backend.worker.app import celery_app  # noqa: E402
from backend.worker.cron import ZoneCronSchedule  # noqa: E402
from backend.worker.models import REAPER_SCHEDULE_KEY  # noqa: E402
from backend.worker.scheduler import DatabaseScheduler  # noqa: E402
from backend.worker.schedules import (  # noqa: E402
    ScheduledTaskRecord,
    get_schedule_store,
    reset_schedule_store,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_job_store()
    reset_schedule_store()
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=super_admin.id,
        status="active",
    )
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client


def _make_source(client: TestClient, key: str = "mes-prod") -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


def _post_daily(client: TestClient, source_id: str, cron: str = "0 2 * * *") -> dict:
    resp = client.post(
        f"/sources/{source_id}/schedules",
        json={
            "kind": "structure",
            "cron": cron,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    return resp


def test_post_inserts_multiple_structure_schedules(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    assert created.status_code == 201, created.text
    body = created.json()["schedule"]
    assert body["work_kind"] == "structure"
    assert body["target"]["source_id"] == source["id"]
    assert body["target"]["source_key"] == "mes-prod"
    assert body["key"] == f"structure:{source['id']}:{body['id']}"
    assert "task_name" not in body
    assert "args_json" not in body
    assert "kwargs_json" not in body
    assert "system" not in body

    second = _post_daily(client, source["id"], cron="0 3 * * *")
    assert second.status_code == 201, second.text
    other = second.json()["schedule"]
    assert other["id"] != body["id"]
    assert other["cron"] == "0 3 * * *"
    assert other["key"] != body["key"]

    listed = client.get("/schedules")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    related = client.get(f"/sources/{source['id']}/schedules")
    assert related.status_code == 200
    assert len(related.json()["items"]) == 2
    assert "task_name" not in related.json()["items"][0]


def test_post_rejects_unknown_kind(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "semantics_refresh", "cron": "0 2 * * *"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SCHEDULE_KIND_INVALID"


def test_system_schedules_excluded_and_immutable(client: TestClient) -> None:
    ensure_system_schedules()
    default_list = client.get("/schedules")
    assert default_list.status_code == 200
    assert default_list.json()["items"] == []

    debug_list = client.get("/schedules?system=true")
    assert debug_list.status_code == 200
    items = debug_list.json()["items"]
    assert len(items) == 1
    reaper_id = items[0]["id"]
    assert items[0]["work_kind"] is None

    stored = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert stored is not None
    assert stored.system is True

    patch = client.patch(f"/schedules/{reaper_id}", json={"enabled": False})
    assert patch.status_code == 409
    assert patch.json()["code"] == "SCHEDULE_SYSTEM_IMMUTABLE"

    delete = client.delete(f"/schedules/{reaper_id}")
    assert delete.status_code == 409
    assert delete.json()["code"] == "SCHEDULE_SYSTEM_IMMUTABLE"


def test_patch_and_delete_domain_schedule(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]

    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"enabled": False, "cron": "30 4 * * *"},
    )
    assert patched.status_code == 200
    assert patched.json()["schedule"]["enabled"] is False
    assert patched.json()["schedule"]["cron"] == "30 4 * * *"
    assert patched.json()["schedule"]["interval_seconds"] is None

    deleted = client.delete(f"/schedules/{schedule_id}")
    assert deleted.status_code == 204
    missing = client.get(f"/schedules/{schedule_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SCHEDULE_NOT_FOUND"
    related = client.get(f"/sources/{source['id']}/schedules")
    assert related.status_code == 200
    assert related.json()["items"] == []


def test_patch_empty_name_restores_default(client: TestClient) -> None:
    source = _make_source(client)
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "name": "custom schedule",
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    assert created.json()["schedule"]["name"] == "custom schedule"

    emptied = client.patch(f"/schedules/{schedule_id}", json={"name": ""})
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["schedule"]["name"] == "structure · mes-prod"

    renamed = client.patch(
        f"/schedules/{schedule_id}", json={"name": "keep me"}
    )
    assert renamed.status_code == 200
    blank = client.patch(f"/schedules/{schedule_id}", json={"name": "   "})
    assert blank.status_code == 200
    assert blank.json()["schedule"]["name"] == "structure · mes-prod"


def test_create_does_not_fire_immediately() -> None:
    clock = FixedClock(parse_instant("2026-08-13T10:15:00Z"))
    set_clock(clock)
    try:
        schedule = ZoneCronSchedule("0 2 * * *", schedule_timezone="UTC")
        due, _rem = schedule.is_due(clock.now())
        assert due is False
    finally:
        reset_clock()


def test_missed_cron_slot_does_not_catch_up() -> None:
    clock = FixedClock(parse_instant("2026-08-13T10:00:00Z"))
    set_clock(clock)
    try:
        schedule = ZoneCronSchedule("0 2 * * *", schedule_timezone="UTC")
        last = parse_instant("2026-08-01T02:00:00Z")
        due, rem = schedule.is_due(last)
        assert due is False
        nxt = clock.now() + timedelta(seconds=rem)
        assert nxt == parse_instant("2026-08-14T02:00:00Z")
    finally:
        reset_clock()


def test_current_matching_minute_fires_once() -> None:
    clock = FixedClock(parse_instant("2026-08-13T02:00:30Z"))
    set_clock(clock)
    try:
        schedule = ZoneCronSchedule("0 2 * * *", schedule_timezone="UTC")
        last = parse_instant("2026-08-12T02:00:00Z")
        due, _rem = schedule.is_due(last)
        assert due is True
    finally:
        reset_clock()


def test_reload_clears_heap_and_follows_new_cadence(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    assert created.status_code == 201
    scheduler = DatabaseScheduler(app=celery_app, lazy=True)
    assert scheduler.max_interval == 5
    scheduler.setup_schedule()
    assert scheduler._heap is None
    scheduler.populate_heap()
    assert scheduler._heap is not None

    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"cron": "* * * * *"},
    )
    assert patched.status_code == 200
    scheduler.sync()
    assert scheduler._heap is None


def test_overlap_skip_does_not_fail_schedule(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
        created_by="user_1",
        summary="structure · mes-prod",
        trigger_kind="user",
        trigger_ref="user_1",
    )
    result = fire_scheduled_structure(schedule_id)
    assert result["status"] == "skipped"
    assert result["reason"] == "already_active"
    assert len(get_job_store().list(kind="structure")) == 1


def test_disabled_source_tick_skips(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    disable = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disable.status_code == 200
    result = fire_scheduled_structure(schedule_id)
    assert result["status"] == "skipped"
    assert result["reason"] == "source_unusable"


def test_schedule_out_hides_celery_fields() -> None:
    ensure_system_schedules()
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert record is not None
    dumped = schedule_out(record).model_dump()
    assert "task_name" not in dumped
    assert dumped["work_kind"] is None


def test_patch_rejects_both_cadence_fields(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"cron": "0 5 * * *", "interval_seconds": 120},
    )
    assert patched.status_code == 400
    assert patched.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_patch_cron_clears_interval_with_null(client: TestClient) -> None:
    source = _make_source(client)
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "interval_seconds": 3600,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201
    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"cron": "0 5 * * *", "interval_seconds": None},
    )
    assert patched.status_code == 200
    body = patched.json()["schedule"]
    assert body["cron"] == "0 5 * * *"
    assert body["interval_seconds"] is None


def test_hard_delete_source_cascades_structure_schedules(client: TestClient) -> None:
    source = _make_source(client)
    first = _post_daily(client, source["id"])
    second = _post_daily(client, source["id"], cron="0 4 * * *")
    ids = [first.json()["schedule"]["id"], second.json()["schedule"]["id"]]
    assert client.patch(f"/sources/{source['id']}", json={"status": "disabled"}).status_code == 200
    assert client.delete(f"/sources/{source['id']}").status_code == 204
    for schedule_id in ids:
        missing = client.get(f"/schedules/{schedule_id}")
        assert missing.status_code == 404
        assert missing.json()["code"] == "SCHEDULE_NOT_FOUND"
    listed = client.get("/schedules")
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_missing_schedule_tick_skips() -> None:
    result = fire_scheduled_structure("sched_does_not_exist")
    assert result["status"] == "skipped"
    assert result["reason"] == "missing_target"


def test_missing_source_tick_skips() -> None:
    from backend.core.time import utc_now

    now = utc_now()
    get_schedule_store().upsert(
        ScheduledTaskRecord(
            id="sched_orphan",
            key="structure:src_does_not_exist:sched_orphan",
            name="orphan",
            enabled=True,
            interval_seconds=None,
            cron="0 2 * * *",
            task_name="backend.metadata.tasks.enqueue_scheduled_structure",
            args_json=[],
            kwargs_json={
                "source_id": "src_does_not_exist",
                "schedule_id": "sched_orphan",
            },
            system=False,
            schedule_timezone="UTC",
            last_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    result = fire_scheduled_structure("sched_orphan")
    assert result["status"] == "skipped"
    assert result["reason"] == "source_unusable"


def test_cadence_invalid(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "structure", "cron": "not-a-cron"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_cadence_rejects_non_positive_interval(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "structure", "interval_seconds": 0},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "SCHEDULE_CADENCE_INVALID"
    assert "positive" in body["detail"]


def test_patch_empty_timezone_rejected(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"schedule_timezone": ""},
    )
    assert patched.status_code == 400
    assert patched.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_run_now_enqueues_without_moving_last_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule = created.json()["schedule"]
    last_run = schedule["last_run_at"]
    ran = client.post(f"/schedules/{schedule['id']}/run")
    assert ran.status_code == 202, ran.text
    job = ran.json()["job"]
    assert job["trigger_kind"] == "schedule"
    assert job["trigger_ref"] == schedule["id"]
    assert job["trigger_schedule_name"] == schedule["name"]
    assert job["created_by_user_id"] is not None
    assert job["input"] == {"source_id": source["id"]}
    refreshed = client.get(f"/schedules/{schedule['id']}")
    assert refreshed.json()["schedule"]["last_run_at"] == last_run


def test_run_now_allowed_when_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    assert client.patch(
        f"/schedules/{schedule_id}", json={"enabled": False}
    ).status_code == 200
    ran = client.post(f"/schedules/{schedule_id}/run")
    assert ran.status_code == 202, ran.text


def test_run_now_rejects_system_schedule(client: TestClient) -> None:
    ensure_system_schedules()
    items = client.get("/schedules?system=true").json()["items"]
    reaper_id = items[0]["id"]
    ran = client.post(f"/schedules/{reaper_id}/run")
    assert ran.status_code == 409
    assert ran.json()["code"] == "SCHEDULE_SYSTEM_IMMUTABLE"


def test_run_now_single_flight_returns_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.jobs.store import create_queued_job, mark_running

    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    job = create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
    )
    mark_running(job.id)
    second = client.post(f"/schedules/{schedule_id}/run")
    assert second.status_code == 409
    assert second.json()["code"] == "JOB_ALREADY_ACTIVE"


def test_schedule_jobs_filtered_by_trigger_ref(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client)
    first = _post_daily(client, source["id"])
    second = _post_daily(client, source["id"], cron="0 5 * * *")
    first_id = first.json()["schedule"]["id"]
    second_id = second.json()["schedule"]["id"]
    job_a = client.post(f"/schedules/{first_id}/run").json()["job"]
    from backend.jobs.store import mark_succeeded

    mark_succeeded(job_a["id"])
    job_b = client.post(f"/schedules/{second_id}/run").json()["job"]
    listed_a = client.get(f"/schedules/{first_id}/jobs")
    listed_b = client.get(f"/schedules/{second_id}/jobs")
    assert listed_a.status_code == 200
    assert [item["id"] for item in listed_a.json()["items"]] == [job_a["id"]]
    assert [item["id"] for item in listed_b.json()["items"]] == [job_b["id"]]

    create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
        created_by="user_1",
        summary="structure · mes-prod",
        trigger_kind="user",
        trigger_ref="user_1",
    )
    listed_a_again = client.get(f"/schedules/{first_id}/jobs")
    assert [item["id"] for item in listed_a_again.json()["items"]] == [job_a["id"]]


def test_source_jobs_http_removed(client: TestClient) -> None:
    source = _make_source(client)
    post = client.post(f"/sources/{source['id']}/jobs", json={"kind": "structure"})
    assert post.status_code == 404
    get = client.get(f"/sources/{source['id']}/jobs")
    assert get.status_code == 404

