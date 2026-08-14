"""Scheduled Task operator API and clock-layer tests."""

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
from backend.worker.schedules import get_schedule_store, reset_schedule_store  # noqa: E402


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


def _put_daily(client: TestClient, source_id: str, cron: str = "0 2 * * *") -> dict:
    resp = client.put(
        f"/sources/{source_id}/schedule",
        json={
            "kind": "structure",
            "cron": cron,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    return resp


def test_put_creates_one_structure_schedule_per_source(client: TestClient) -> None:
    source = _make_source(client)
    created = _put_daily(client, source["id"])
    assert created.status_code == 201, created.text
    body = created.json()["schedule"]
    assert body["work_kind"] == "structure"
    assert body["target"]["source_id"] == source["id"]
    assert body["target"]["source_key"] == "mes-prod"
    assert "task_name" not in body
    assert "args_json" not in body
    assert "kwargs_json" not in body
    assert "system" not in body

    again = _put_daily(client, source["id"], cron="0 3 * * *")
    assert again.status_code == 200
    updated = again.json()["schedule"]
    assert updated["id"] == body["id"]
    assert updated["cron"] == "0 3 * * *"
    assert updated["last_run_at"] == body["last_run_at"]

    listed = client.get("/schedules")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
    assert items[0]["target"]["source_key"] == "mes-prod"
    assert "task_name" not in items[0]


def test_put_rejects_unknown_kind(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.put(
        f"/sources/{source['id']}/schedule",
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
    created = _put_daily(client, source["id"])
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
    missing = client.get(f"/sources/{source['id']}/schedule")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SCHEDULE_NOT_FOUND"


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
    created = _put_daily(client, source["id"])
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
    create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
        created_by="user_1",
        summary="structure · mes-prod",
        trigger_kind="user",
        trigger_ref="user_1",
    )
    result = fire_scheduled_structure(source["id"])
    assert result["status"] == "skipped"
    assert result["reason"] == "already_active"
    assert len(get_job_store().list(kind="structure")) == 1


def test_disabled_source_tick_skips(client: TestClient) -> None:
    source = _make_source(client)
    disable = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disable.status_code == 200
    result = fire_scheduled_structure(source["id"])
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
    created = _put_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"cron": "0 5 * * *", "interval_seconds": 120},
    )
    assert patched.status_code == 400
    assert patched.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_patch_cron_clears_interval_with_null(client: TestClient) -> None:
    source = _make_source(client)
    created = client.put(
        f"/sources/{source['id']}/schedule",
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


def test_hard_delete_source_cascades_structure_schedule(client: TestClient) -> None:
    source = _make_source(client)
    created = _put_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    assert client.patch(f"/sources/{source['id']}", json={"status": "disabled"}).status_code == 200
    assert client.delete(f"/sources/{source['id']}").status_code == 204
    missing = client.get(f"/schedules/{schedule_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SCHEDULE_NOT_FOUND"
    listed = client.get("/schedules")
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_missing_source_tick_skips(client: TestClient) -> None:
    result = fire_scheduled_structure("src_does_not_exist")
    assert result["status"] == "skipped"
    assert result["reason"] == "source_unusable"


def test_cadence_invalid(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.put(
        f"/sources/{source['id']}/schedule",
        json={"kind": "structure", "cron": "not-a-cron"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_cadence_rejects_non_positive_interval(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.put(
        f"/sources/{source['id']}/schedule",
        json={"kind": "structure", "interval_seconds": 0},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "SCHEDULE_CADENCE_INVALID"
    assert "positive" in body["detail"]


def test_patch_empty_timezone_rejected(client: TestClient) -> None:
    source = _make_source(client)
    created = _put_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    patched = client.patch(
        f"/schedules/{schedule_id}",
        json={"schedule_timezone": ""},
    )
    assert patched.status_code == 400
    assert patched.json()["code"] == "SCHEDULE_CADENCE_INVALID"
