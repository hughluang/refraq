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
from backend.core.time import (  # noqa: E402
    FixedClock,
    format_instant,
    parse_instant,
    reset_clock,
    set_clock,
    utc_now,
)
from backend.jobs.store import claim_queued, create_queued_job, get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata import source_jobs as source_jobs_mod  # noqa: E402
from backend.metadata.source_jobs import (  # noqa: E402
    fire_scheduled_join_detection,
    fire_scheduled_structure,
)
from backend.metadata.source_schedules import (  # noqa: E402
    STRUCTURE_ENQUEUE_TASK_NAME,
    public_schedule,
)
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.api import ensure_system_schedules, schedule_out  # noqa: E402
from backend.worker.app import celery_app  # noqa: E402
from backend.worker.models import REAPER_SCHEDULE_KEY  # noqa: E402
from backend.worker.scheduler import DatabaseScheduler  # noqa: E402
from backend.worker.schedules import (  # noqa: E402
    ScheduledTaskRecord,
    get_schedule_store,
    reset_schedule_store,
)


def _structure_jobs():
    items, _ = get_job_store().list(kind="structure")
    return items


def _due_at(schedule_id: str) -> str:
    """Simulate Beat delivery kwargs: commitment Instant frozen at send time."""
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    assert record.next_run_at is not None
    return format_instant(record.next_run_at, timespec="microseconds")


def _fire(
    schedule_id: str,
    *,
    due_at: str | None = ...,  # type: ignore[assignment]
    source_id: str | None = None,
):
    """Call fire_scheduled_structure; default due_at from store next (Beat snapshot)."""
    kwargs: dict = {"schedule_id": schedule_id}
    if due_at is ...:
        kwargs["due_at"] = _due_at(schedule_id)
    elif due_at is not None:
        kwargs["due_at"] = due_at
    if source_id is not None:
        kwargs["source_id"] = source_id
    return fire_scheduled_structure(**kwargs)


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
    assert body["running_timeout_sec"] is None

    second = _post_daily(client, source["id"], cron="0 3 * * *")
    assert second.status_code == 201, second.text
    other = second.json()["schedule"]
    assert other["id"] != body["id"]
    assert other["cron"] == "0 3 * * *"
    assert other["key"] != body["key"]

    listed = client.get("/schedules")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 4
    related = client.get(f"/sources/{source['id']}/schedules")
    assert related.status_code == 200
    assert len(related.json()["items"]) == 4
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
    remaining = related.json()["items"]
    assert len(remaining) == 2
    assert remaining[0]["id"] != schedule_id
    assert remaining[1]["id"] != schedule_id


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


def test_patch_empty_name_restores_join_detection_default(client: TestClient) -> None:
    source = _make_source(client)
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "join_detection",
            "cron": "0 4 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "name": "custom detection",
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    assert created.json()["schedule"]["name"] == "custom detection"

    emptied = client.patch(f"/schedules/{schedule_id}", json={"name": ""})
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["schedule"]["name"] == "join_detection · mes-prod"

    renamed = client.patch(
        f"/schedules/{schedule_id}", json={"name": "keep me"}
    )
    assert renamed.status_code == 200
    blank = client.patch(f"/schedules/{schedule_id}", json={"name": "   "})
    assert blank.status_code == 200
    assert blank.json()["schedule"]["name"] == "join_detection · mes-prod"


def test_create_does_not_fire_immediately(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-13T10:15:00Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="no-immediate")
        created = _post_daily(client, source["id"])
        assert created.status_code == 201, created.text
        result = _fire(created.json()["schedule"]["id"])
        assert result["status"] == "not_due"
        assert _structure_jobs() == []
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


def test_overlap_still_mints_when_source_busy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schedule mint ignores Source single-flight; always creates a Job when due."""
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
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
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
        created_by="user_1",
        summary="structure · mes-prod",
        trigger_kind="user",
        trigger_ref="user_1",
    )
    from dataclasses import replace

    from backend.core.time import utc_now

    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    get_schedule_store().upsert(
        replace(record, next_run_at=utc_now() - timedelta(minutes=1))
    )
    result = _fire(schedule_id)
    assert result["status"] == "queued"
    assert "job_id" in result
    assert len(_structure_jobs()) == 2


def test_disabled_source_tick_still_mints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
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
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    disable = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disable.status_code == 200
    from dataclasses import replace

    from backend.core.time import utc_now

    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    get_schedule_store().upsert(
        replace(record, next_run_at=utc_now() - timedelta(minutes=1))
    )
    result = _fire(schedule_id)
    assert result["status"] == "queued"
    assert len(_structure_jobs()) == 1


def _structure_record(*, source_id: str = "src_abc") -> ScheduledTaskRecord:
    from backend.core.time import utc_now

    now = utc_now()
    schedule_id = "sched_structure"
    return ScheduledTaskRecord(
        id=schedule_id,
        key=f"structure:{source_id}:{schedule_id}",
        name="structure · mes-prod",
        enabled=True,
        interval_seconds=None,
        cron="0 2 * * *",
        task_name=STRUCTURE_ENQUEUE_TASK_NAME,
        args_json=[],
        kwargs_json={"source_id": source_id, "schedule_id": schedule_id},
        system=False,
        schedule_timezone="UTC",
        last_run_at=now,
        created_at=now,
        updated_at=now,
    )


def test_schedule_out_hides_celery_fields() -> None:
    ensure_system_schedules()
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert record is not None
    dumped = schedule_out(record).model_dump()
    assert "task_name" not in dumped
    assert dumped["work_kind"] is None
    assert dumped["target"] is None


def test_schedule_out_does_not_infer_structure_kind() -> None:
    dumped = schedule_out(_structure_record()).model_dump()
    assert "task_name" not in dumped
    assert dumped["work_kind"] is None
    assert dumped["target"] is None


def test_public_schedule_projects_structure_target(client: TestClient) -> None:
    source = _make_source(client)
    created = _post_daily(client, source["id"])
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    mechanism = schedule_out(record)
    assert mechanism.work_kind is None
    assert mechanism.target is None
    projected = public_schedule(record)
    assert projected.work_kind == "structure"
    assert projected.target is not None
    assert projected.target.source_id == source["id"]
    assert projected.target.source_key == "mes-prod"


def test_public_schedule_missing_source_id_is_not_structure() -> None:
    record = _structure_record()
    record.kwargs_json = {"schedule_id": record.id}
    projected = public_schedule(record)
    assert projected.work_kind is None
    assert projected.target is None


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


def test_structure_mint_task_lives_on_fire_scheduled_structure() -> None:
    assert fire_scheduled_structure.name == STRUCTURE_ENQUEUE_TASK_NAME
    assert fire_scheduled_structure.name.startswith("backend.metadata.source_jobs.")
    assert not hasattr(source_jobs_mod, "enqueue_scheduled_structure")


def test_missing_due_at_does_not_mint() -> None:
    result = fire_scheduled_structure("sched_does_not_exist")
    assert result["status"] == "missing_due_at"
    assert _structure_jobs() == []


def test_deleted_schedule_with_due_at_mints_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    due = utc_now() - timedelta(minutes=1)
    result = fire_scheduled_structure(
        "sched_does_not_exist",
        source_id="src_gone",
        due_at=format_instant(due, timespec="microseconds"),
    )
    assert result["status"] == "cancelled"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == "cancelled"
    assert jobs[0].scheduled_for == due
    assert jobs[0].trigger_ref == "sched_does_not_exist"


def test_missing_source_tick_still_mints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    now = utc_now()
    get_schedule_store().upsert(
        ScheduledTaskRecord(
            id="sched_orphan",
            key="structure:src_does_not_exist:sched_orphan",
            name="orphan",
            enabled=True,
            interval_seconds=3600,
            cron=None,
            task_name=STRUCTURE_ENQUEUE_TASK_NAME,
            args_json=[],
            kwargs_json={
                "source_id": "src_does_not_exist",
                "schedule_id": "sched_orphan",
            },
            system=False,
            schedule_timezone="UTC",
            owner_ref="metadata:source:src_does_not_exist",
            last_run_at=now,
            next_run_at=now - timedelta(minutes=1),
            created_at=now,
            updated_at=now,
        )
    )
    result = _fire("sched_orphan")
    assert result["status"] == "queued"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].trigger_ref == "sched_orphan"


def test_cadence_invalid(client: TestClient) -> None:
    source = _make_source(client)
    resp = client.post(
        f"/sources/{source['id']}/schedules",
        json={"kind": "structure", "cron": "not-a-cron"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SCHEDULE_CADENCE_INVALID"


def test_create_schedule_running_timeout_snapshots_on_run_now(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="timeout-src")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "running_timeout_sec": 120,
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()["schedule"]
    assert schedule["running_timeout_sec"] == 120
    ran = client.post(f"/schedules/{schedule['id']}/run")
    assert ran.status_code == 202, ran.text
    assert ran.json()["job"]["running_timeout_sec"] == 120


def test_due_mint_snapshots_running_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="timeout-due")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "interval_seconds": 3600,
            "schedule_timezone": "UTC",
            "enabled": True,
            "running_timeout_sec": 45,
        },
    )
    schedule_id = created.json()["schedule"]["id"]
    from dataclasses import replace

    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    get_schedule_store().upsert(
        replace(record, next_run_at=utc_now() - timedelta(minutes=1))
    )
    result = _fire(schedule_id)
    assert result["status"] == "queued"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].running_timeout_sec == 45


def test_create_rejects_zero_running_timeout(client: TestClient) -> None:
    source = _make_source(client, key="timeout-zero")
    resp = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "running_timeout_sec": 0,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SCHEDULE_RUNNING_TIMEOUT_INVALID"


def test_patch_running_timeout_omit_leaves_and_null_clears(
    client: TestClient,
) -> None:
    source = _make_source(client, key="timeout-patch")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "running_timeout_sec": 90,
        },
    )
    schedule_id = created.json()["schedule"]["id"]
    omitted = client.patch(f"/schedules/{schedule_id}", json={"enabled": True})
    assert omitted.status_code == 200
    assert omitted.json()["schedule"]["running_timeout_sec"] == 90
    cleared = client.patch(
        f"/schedules/{schedule_id}", json={"running_timeout_sec": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["schedule"]["running_timeout_sec"] is None


def test_patch_running_timeout_does_not_rewrite_in_flight_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="timeout-inflight")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
            "running_timeout_sec": 60,
        },
    )
    schedule_id = created.json()["schedule"]["id"]
    ran = client.post(f"/schedules/{schedule_id}/run")
    assert ran.status_code == 202, ran.text
    job_id = ran.json()["job"]["id"]
    assert ran.json()["job"]["running_timeout_sec"] == 60
    patched = client.patch(
        f"/schedules/{schedule_id}", json={"running_timeout_sec": 600}
    )
    assert patched.status_code == 200
    assert patched.json()["schedule"]["running_timeout_sec"] == 600
    detail = client.get(f"/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["job"]["running_timeout_sec"] == 60


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
    paused = client.get(f"/schedules/{schedule_id}").json()["schedule"]
    assert paused["next_run_at"] is None
    ran = client.post(f"/schedules/{schedule_id}/run")
    assert ran.status_code == 202, ran.text
    assert ran.json()["job"]["scheduled_for"] is None
    still = client.get(f"/schedules/{schedule_id}").json()["schedule"]
    assert still["next_run_at"] is None
    assert still["enabled"] is False


def test_run_now_rejects_system_schedule(client: TestClient) -> None:
    ensure_system_schedules()
    items = client.get("/schedules?system=true").json()["items"]
    reaper_id = items[0]["id"]
    ran = client.post(f"/schedules/{reaper_id}/run")
    assert ran.status_code == 409
    assert ran.json()["code"] == "SCHEDULE_SYSTEM_IMMUTABLE"


def test_run_now_mints_when_source_busy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    claimed = claim_queued(job.id)
    assert claimed is not None
    second = client.post(f"/schedules/{schedule_id}/run")
    assert second.status_code == 202, second.text
    assert second.json()["job"]["id"] != job.id
    assert len(_structure_jobs()) == 2


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


def _source_body(key: str) -> dict:
    return {
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
    }


def _insert_source_without_schedule(*, key: str, name: str | None = None):
    from backend.core.time import utc_now
    from backend.metadata.sources.access import seal_access
    from backend.metadata.sources.store import SourceRecord, get_source_store

    now = utc_now()
    return get_source_store().create_source(
        SourceRecord(
            id=f"src_{key.replace('-', '_')}",
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=name or key,
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=seal_access(
                "postgresql", _source_body(key)["access"]
            ),
            access_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def test_source_create_seeds_default_source_schedules(client: TestClient) -> None:
    from backend.admin.audit_store import get_audit_store
    from backend.metadata.source_schedules import (
        DEFAULT_JOIN_DETECTION_CRON,
        DEFAULT_STRUCTURE_CRON,
    )

    resp = client.post("/sources", json=_source_body("seed-src"))
    assert resp.status_code == 201, resp.text
    assert "schedule" not in resp.json()
    assert "schedules" not in resp.json()
    source = resp.json()["source"]
    listed = client.get(f"/sources/{source['id']}/schedules")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    by_kind = {item["work_kind"]: item for item in items}
    structure = by_kind["structure"]
    join_detection = by_kind["join_detection"]
    assert structure["cron"] == DEFAULT_STRUCTURE_CRON
    assert join_detection["cron"] == DEFAULT_JOIN_DETECTION_CRON
    assert structure["schedule_timezone"] == "UTC"
    assert join_detection["schedule_timezone"] == "UTC"
    assert structure["enabled"] is True
    assert join_detection["enabled"] is True
    assert structure["name"] == "structure · seed-src"
    assert join_detection["name"] == "join_detection · seed-src"
    jobs = client.get("/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["items"] == []
    me = client.get("/auth/me")
    assert me.status_code == 200
    actor_id = me.json()["user"]["id"]
    source_events, _ = get_audit_store().list_events(action="source.create")
    schedule_events, _ = get_audit_store().list_events(action="schedule.create")
    assert len(source_events) == 1
    assert len(schedule_events) == 2
    assert source_events[0].actor_user_id == actor_id
    assert {event.detail["kind"] for event in schedule_events} == {
        "structure",
        "join_detection",
    }
    for event in schedule_events:
        assert event.actor_user_id == actor_id
        assert event.detail["source_id"] == source["id"]


def test_sources_write_without_jobs_run_still_seeds(client: TestClient) -> None:
    from backend.admin.roles import create_role
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.worker.schedules import get_schedule_store

    role = create_role(
        get_role_store(),
        key="src_writer",
        name="Source writer",
        permissions=["console:access", "sources:read", "sources:write"],
    )
    get_user_store().create_user(
        account="writer",
        display_name="Writer",
        password_hash=hash_password("writer-pass"),
        role_id=role.id,
    )
    login = client.post(
        "/auth/login",
        json={"account": "writer", "password": "writer-pass"},
    )
    assert login.status_code == 200, login.text
    resp = client.post("/sources", json=_source_body("writer-src"))
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["source"]["id"]
    forbidden = client.get(f"/sources/{source_id}/schedules")
    assert forbidden.status_code == 403
    records, _ = get_schedule_store().list(include_system=False)
    matches = [
        record
        for record in records
        if record.kwargs_json.get("source_id") == source_id
    ]
    assert len(matches) == 2


def test_seed_failure_does_not_leave_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata.sources.service import create_source
    from backend.metadata.sources.store import get_source_store
    from backend.worker.schedules import get_schedule_store

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("seed failed")

    monkeypatch.setattr(
        "backend.metadata.sources.service.seed_default_source_schedules",
        boom,
    )
    with pytest.raises(RuntimeError, match="seed failed"):
        create_source(
            key="boom-src",
            name="boom-src",
            kind="database",
            description=None,
            engine="postgresql",
            access=_source_body("boom-src")["access"],
        )
    assert get_source_store().get_source_by_key("boom-src") is None
    assert get_schedule_store().list(include_system=False) == ([], 0)


def test_patch_inserts_when_zero_source_schedules(client: TestClient) -> None:
    from backend.admin.audit_store import get_audit_store
    from backend.metadata.source_schedules import (
        DEFAULT_JOIN_DETECTION_CRON,
        DEFAULT_STRUCTURE_CRON,
        list_source_schedules,
    )

    source = _insert_source_without_schedule(key="ensure-src", name="Ensure")
    assert list_source_schedules(source.id) == ([], 0)
    me = client.get("/auth/me")
    assert me.status_code == 200
    actor_id = me.json()["user"]["id"]
    patched = client.patch(f"/sources/{source.id}", json={"name": "Ensure updated"})
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert "source" in body
    assert "schedule" not in body
    schedules = body["schedules"]
    assert len(schedules) == 2
    by_kind = {item["work_kind"]: item for item in schedules}
    assert by_kind["structure"]["cron"] == DEFAULT_STRUCTURE_CRON
    assert by_kind["join_detection"]["cron"] == DEFAULT_JOIN_DETECTION_CRON
    items, total = list_source_schedules(source.id)
    assert total == 2
    assert len(items) == 2
    events, _ = get_audit_store().list_events(action="schedule.create")
    assert len(events) == 2
    assert {event.detail["kind"] for event in events} == {
        "structure",
        "join_detection",
    }
    for event in events:
        assert event.actor_user_id == actor_id
        assert event.detail["source_id"] == source.id
    again = client.patch(f"/sources/{source.id}", json={"name": "Ensure again"})
    assert again.status_code == 200
    assert "schedules" not in again.json()
    assert list_source_schedules(source.id)[1] == 2


def test_patch_skips_when_disabled_schedule_present(client: TestClient) -> None:
    source = _make_source(client, key="disabled-seed")
    items = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    assert len(items) == 2
    for item in items:
        patched_sched = client.patch(
            f"/schedules/{item['id']}", json={"enabled": False}
        )
        assert patched_sched.status_code == 200
    patched = client.patch(
        f"/sources/{source['id']}", json={"name": "disabled-seed-renamed"}
    )
    assert patched.status_code == 200
    assert "schedules" not in patched.json()
    after = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    assert len(after) == 2
    assert {item["id"] for item in after} == {item["id"] for item in items}
    assert all(item["enabled"] is False for item in after)


def test_delete_last_schedule_then_patch_reinserts(client: TestClient) -> None:
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    source = _make_source(client, key="wipe-seed")
    items = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    assert len(items) == 2
    for item in items:
        deleted = client.delete(f"/schedules/{item['id']}")
        assert deleted.status_code == 204
    empty = client.get(f"/sources/{source['id']}/schedules")
    assert empty.json()["items"] == []
    reset_audit_store()
    me = client.get("/auth/me")
    actor_id = me.json()["user"]["id"]
    patched = client.patch(
        f"/sources/{source['id']}", json={"name": "wipe-seed-touched"}
    )
    assert patched.status_code == 200, patched.text
    seeded = patched.json()["schedules"]
    assert len(seeded) == 2
    seeded_ids = {item["id"] for item in seeded}
    assert seeded_ids.isdisjoint({item["id"] for item in items})
    after = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    assert {item["id"] for item in after} == seeded_ids
    events, _ = get_audit_store().list_events(action="schedule.create")
    assert len(events) == 2
    assert {event.detail["kind"] for event in events} == {
        "structure",
        "join_detection",
    }
    for event in events:
        assert event.actor_user_id == actor_id
        assert event.detail["source_id"] == source["id"]


def test_patch_same_name_or_empty_body_does_not_seed(client: TestClient) -> None:
    from backend.metadata.source_schedules import list_source_schedules

    source = _insert_source_without_schedule(key="noop-seed", name="Noop")
    same = client.patch(f"/sources/{source.id}", json={"name": "Noop"})
    assert same.status_code == 200
    assert "schedules" not in same.json()
    assert list_source_schedules(source.id) == ([], 0)
    empty = client.patch(f"/sources/{source.id}", json={})
    assert empty.status_code == 200
    assert "schedule" not in empty.json()
    assert "schedules" not in empty.json()
    assert list_source_schedules(source.id) == ([], 0)


def test_cron_current_slot_mints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-15T02:00:05Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="slot-mint")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        from dataclasses import replace

        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        slot = parse_instant("2026-08-15T02:00:00Z")
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=slot,
                last_run_at=parse_instant("2026-08-14T02:00:00Z"),
            )
        )
        result = _fire(schedule_id)
        assert result["status"] == "queued"
        jobs = _structure_jobs()
        assert len(jobs) == 1
        assert jobs[0].scheduled_for == slot
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == clock.now()
        assert refreshed.next_run_at == parse_instant("2026-08-16T02:00:00Z")
    finally:
        reset_clock()


def test_cron_cross_slot_advances_without_mint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-15T05:00:00Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="cross-slot")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        from dataclasses import replace

        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        last = parse_instant("2026-08-14T02:00:00Z")
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=parse_instant("2026-08-15T02:00:00Z"),
                last_run_at=last,
            )
        )
        result = _fire(schedule_id)
        assert result["status"] == "skip_cross_slot"
        assert _structure_jobs() == []
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == last
        assert refreshed.next_run_at == parse_instant("2026-08-16T02:00:00Z")
    finally:
        reset_clock()


def test_cron_stale_commitment_keeps_today_slot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale yesterday commitment at today's matching minute: second consume mints today."""
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-15T02:00:05Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="keep-today")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        from dataclasses import replace

        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        yesterday = parse_instant("2026-08-14T02:00:00Z")
        today_slot = parse_instant("2026-08-15T02:00:00Z")
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=yesterday,
                last_run_at=parse_instant("2026-08-13T02:00:00Z"),
            )
        )
        result = _fire(schedule_id)
        assert result["status"] == "queued"
        jobs = _structure_jobs()
        assert len(jobs) == 1
        assert jobs[0].scheduled_for == today_slot
        assert jobs[0].scheduled_for != yesterday
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == clock.now()
        assert refreshed.next_run_at == parse_instant("2026-08-16T02:00:00Z")
    finally:
        reset_clock()


def test_cron_stale_commitment_past_slot_skips_without_mint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale yesterday commitment after today's slot has passed: no mint, advance next."""
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-15T05:00:00Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="stale-past")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        from dataclasses import replace

        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        last = parse_instant("2026-08-13T02:00:00Z")
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=parse_instant("2026-08-14T02:00:00Z"),
                last_run_at=last,
            )
        )
        result = _fire(schedule_id)
        assert result["status"] == "skip_cross_slot"
        assert _structure_jobs() == []
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == last
        assert refreshed.next_run_at == parse_instant("2026-08-16T02:00:00Z")
    finally:
        reset_clock()


def test_pause_does_not_cancel_queued_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="pause-keep")
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    ran = client.post(f"/schedules/{schedule_id}/run")
    assert ran.status_code == 202
    job_id = ran.json()["job"]["id"]
    assert client.patch(
        f"/schedules/{schedule_id}", json={"enabled": False}
    ).status_code == 200
    stored = get_job_store().get(job_id)
    assert stored is not None
    assert stored.status == "queued"
    paused = client.get(f"/schedules/{schedule_id}").json()["schedule"]
    assert paused["next_run_at"] is None


def test_delete_schedule_cancels_unfinished(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="del-cancel")
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    ran = client.post(f"/schedules/{schedule_id}/run")
    job_id = ran.json()["job"]["id"]
    assert client.delete(f"/schedules/{schedule_id}").status_code == 204
    stored = get_job_store().get(job_id)
    assert stored is not None
    assert stored.status == "cancelled"
    assert stored.finished_at is not None


def test_delete_schedule_logs_revoke_failure_and_still_cancels(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )

    def _broker_down(*_a, **_k):
        raise RuntimeError("broker down")

    monkeypatch.setattr("backend.worker.api.revoke_queued_delivery", _broker_down)
    source = _make_source(client, key="del-revoke-fail")
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    ran = client.post(f"/schedules/{schedule_id}/run")
    job_id = ran.json()["job"]["id"]
    with caplog.at_level("ERROR", logger="backend.worker.api"):
        assert client.delete(f"/schedules/{schedule_id}").status_code == 204
    stored = get_job_store().get(job_id)
    assert stored is not None
    assert stored.status == "cancelled"
    assert "schedule withdraw revoke failed" in caplog.text
    assert job_id in caplog.text
    assert schedule_id in caplog.text


def test_initial_next_run_at_none_when_disabled() -> None:
    from backend.worker.api import initial_next_run_at

    assert (
        initial_next_run_at(
            cron="0 2 * * *",
            schedule_timezone="UTC",
            interval_seconds=None,
            enabled=False,
            after=parse_instant("2026-08-15T01:00:00Z"),
        )
        is None
    )


def test_initial_next_run_at_uses_after_anchor() -> None:
    from backend.worker.api import initial_next_run_at

    nxt = initial_next_run_at(
        cron="0 2 * * *",
        schedule_timezone="UTC",
        interval_seconds=None,
        enabled=True,
        after=parse_instant("2026-08-15T01:00:00Z"),
    )
    assert nxt == parse_instant("2026-08-15T02:00:00Z")


def test_initial_next_run_at_rejects_non_datetime_after() -> None:
    from backend.worker.api import initial_next_run_at

    with pytest.raises(TypeError):
        initial_next_run_at(
            cron="0 2 * * *",
            schedule_timezone="UTC",
            interval_seconds=None,
            enabled=True,
            after="2026-08-15T01:00:00Z",  # type: ignore[arg-type]
        )


def test_owner_ref_written_and_withdraw_on_source_delete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="owner-ref")
    created = _post_daily(client, source["id"])
    schedule_id = created.json()["schedule"]["id"]
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    assert record.owner_ref == f"metadata:source:{source['id']}"
    ran = client.post(f"/schedules/{schedule_id}/run")
    job_id = ran.json()["job"]["id"]
    assert client.patch(
        f"/sources/{source['id']}", json={"status": "disabled"}
    ).status_code == 200
    assert client.delete(f"/sources/{source['id']}").status_code == 204
    assert get_schedule_store().get_by_id(schedule_id) is None
    stored = get_job_store().get(job_id)
    assert stored is not None
    assert stored.status == "cancelled"


def test_hard_delete_withdraws_both_schedule_kinds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="withdraw-kinds")
    listed = client.get(f"/sources/{source['id']}/schedules")
    assert listed.status_code == 200, listed.text
    kinds = {item["work_kind"] for item in listed.json()["items"]}
    assert kinds == {"structure", "join_detection"}
    ids = {item["id"] for item in listed.json()["items"]}
    assert client.patch(
        f"/sources/{source['id']}", json={"status": "disabled"}
    ).status_code == 200
    assert client.delete(f"/sources/{source['id']}").status_code == 204
    for schedule_id in ids:
        assert get_schedule_store().get_by_id(schedule_id) is None
    leftover, leftover_total = get_schedule_store().list_by_owner_ref(
        f"metadata:source:{source['id']}"
    )
    assert leftover_total == 0
    assert leftover == []


def test_schedule_last_job_observation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="last-job")
    created = _post_daily(client, source["id"])
    schedule = created.json()["schedule"]
    assert schedule["last_job"] is None
    assert schedule["next_run_at"] is not None
    ran = client.post(f"/schedules/{schedule['id']}/run")
    assert ran.status_code == 202
    refreshed = client.get(f"/schedules/{schedule['id']}").json()["schedule"]
    assert refreshed["last_job"] is not None
    assert refreshed["last_job"]["id"] == ran.json()["job"]["id"]


def test_inflight_delete_mints_cancelled_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beat already delivered; worker runs after DELETE — still mint cancelled."""
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="inflight-del")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "interval_seconds": 3600,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    due = utc_now() - timedelta(minutes=1)
    get_schedule_store().upsert(replace(record, next_run_at=due))
    delivered = _due_at(schedule_id)
    assert client.delete(f"/schedules/{schedule_id}").status_code == 204
    result = fire_scheduled_structure(
        schedule_id,
        source_id=source["id"],
        due_at=delivered,
    )
    assert result["status"] == "cancelled"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == "cancelled"
    assert jobs[0].scheduled_for == due
    assert jobs[0].trigger_ref == schedule_id
    assert get_schedule_store().get_by_id(schedule_id) is None


def test_unique_collision_still_advances_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already-minted scheduled_for still consumes the tick (UNIQUE still pushes next)."""
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    clock = FixedClock(parse_instant("2026-08-15T02:00:05Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="uniq-adv")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        slot = parse_instant("2026-08-15T02:00:00Z")
        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=slot,
                last_run_at=parse_instant("2026-08-14T02:00:00Z"),
            )
        )
        # Simulate crash after INSERT Job, before cursor move.
        existing = create_queued_job(
            kind="structure",
            input={"source_id": source["id"]},
            trigger_kind="schedule",
            trigger_ref=schedule_id,
            scheduled_for=slot,
            created_at=clock.now(),
        )
        result = _fire(schedule_id)
        assert result["status"] == "already_minted"
        assert result["job_id"] == existing.id
        jobs = _structure_jobs()
        assert len(jobs) == 1
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == existing.created_at
        assert refreshed.next_run_at == parse_instant("2026-08-16T02:00:00Z")
    finally:
        reset_clock()


def test_join_detection_unique_collision_already_minted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    clock = FixedClock(parse_instant("2026-08-15T04:00:05Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="uniq-join")
        items = client.get(f"/sources/{source['id']}/schedules").json()["items"]
        schedule = next(item for item in items if item["work_kind"] == "join_detection")
        schedule_id = schedule["id"]
        slot = parse_instant("2026-08-15T04:00:00Z")
        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=slot,
                last_run_at=parse_instant("2026-08-14T04:00:00Z"),
            )
        )
        existing = create_queued_job(
            kind="join_detection",
            input={"source_id": source["id"]},
            trigger_kind="schedule",
            trigger_ref=schedule_id,
            scheduled_for=slot,
            created_at=clock.now(),
        )
        result = fire_scheduled_join_detection(
            schedule_id=schedule_id, due_at=_due_at(schedule_id)
        )
        assert result["status"] == "already_minted"
        assert result["job_id"] == existing.id
        jobs, _ = get_job_store().list(kind="join_detection")
        assert len(jobs) == 1
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == existing.created_at
        assert refreshed.next_run_at == parse_instant("2026-08-16T04:00:00Z")
    finally:
        reset_clock()


def test_missing_target_mints_cancelled_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="miss-tgt")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "interval_seconds": 3600,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    due = utc_now() - timedelta(minutes=1)
    get_schedule_store().upsert(
        replace(
            record,
            kwargs_json={},
            next_run_at=due,
        )
    )
    result = _fire(schedule_id)
    assert result["status"] == "cancelled"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == "cancelled"
    assert jobs[0].scheduled_for == due
    refreshed = get_schedule_store().get_by_id(schedule_id)
    assert refreshed is not None
    assert refreshed.last_run_at is not None
    assert refreshed.next_run_at is not None
    assert refreshed.next_run_at > utc_now() - timedelta(seconds=5)


def test_inflight_disable_mints_cancelled_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beat already delivered; worker runs after PATCH enabled=false — mint cancelled."""
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    source = _make_source(client, key="inflight-dis")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "structure",
            "interval_seconds": 3600,
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    record = get_schedule_store().get_by_id(schedule_id)
    assert record is not None
    due = utc_now() - timedelta(minutes=1)
    get_schedule_store().upsert(replace(record, next_run_at=due))
    delivered = _due_at(schedule_id)
    assert client.patch(
        f"/schedules/{schedule_id}", json={"enabled": False}
    ).status_code == 200
    result = fire_scheduled_structure(
        schedule_id,
        source_id=source["id"],
        due_at=delivered,
    )
    assert result["status"] == "cancelled"
    jobs = _structure_jobs()
    assert len(jobs) == 1
    assert jobs[0].status == "cancelled"
    assert jobs[0].scheduled_for == due
    refreshed = get_schedule_store().get_by_id(schedule_id)
    assert refreshed is not None
    assert refreshed.enabled is False
    assert refreshed.next_run_at is None
    assert refreshed.last_run_at is not None


def test_paused_cron_cross_slot_does_not_mint_or_restore_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Paused + delivered Instant already past current slot: skip, keep next null."""
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "eager-stub"})(),
    )
    clock = FixedClock(parse_instant("2026-08-15T05:00:00Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="pause-cross")
        created = _post_daily(client, source["id"])
        schedule_id = created.json()["schedule"]["id"]
        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        due = parse_instant("2026-08-15T02:00:00Z")
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=due,
                last_run_at=parse_instant("2026-08-14T02:00:00Z"),
            )
        )
        delivered = _due_at(schedule_id)
        assert client.patch(
            f"/schedules/{schedule_id}", json={"enabled": False}
        ).status_code == 200
        result = fire_scheduled_structure(
            schedule_id,
            source_id=source["id"],
            due_at=delivered,
        )
        assert result["status"] == "skip_cross_slot"
        assert _structure_jobs() == []
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.enabled is False
        assert refreshed.next_run_at is None
        assert refreshed.last_run_at == parse_instant("2026-08-14T02:00:00Z")
    finally:
        reset_clock()


def test_interval_catchup_scheduled_for_and_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    clock = FixedClock(parse_instant("2026-08-15T10:00:00Z"))
    set_clock(clock)
    try:
        source = _make_source(client, key="int-catch")
        created = client.post(
            f"/sources/{source['id']}/schedules",
            json={
                "kind": "structure",
                "interval_seconds": 3600,
                "schedule_timezone": "UTC",
                "enabled": True,
            },
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["schedule"]["id"]
        past = parse_instant("2026-08-15T09:00:00Z")
        record = get_schedule_store().get_by_id(schedule_id)
        assert record is not None
        get_schedule_store().upsert(replace(record, next_run_at=past))
        result = _fire(schedule_id)
        assert result["status"] == "queued"
        jobs = _structure_jobs()
        assert len(jobs) == 1
        assert jobs[0].scheduled_for == past
        refreshed = get_schedule_store().get_by_id(schedule_id)
        assert refreshed is not None
        assert refreshed.last_run_at == clock.now()
        assert refreshed.next_run_at == clock.now() + timedelta(seconds=3600)
    finally:
        reset_clock()


def test_create_join_detection_schedule_and_run_now(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.metadata.join_detection_jobs.service.run_join_detection_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="join-sched")
    created = client.post(
        f"/sources/{source['id']}/schedules",
        json={
            "kind": "join_detection",
            "cron": "0 4 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()["schedule"]
    assert body["work_kind"] == "join_detection"
    assert body["key"] == f"join_detection:{source['id']}:{body['id']}"
    ran = client.post(f"/schedules/{body['id']}/run")
    assert ran.status_code == 202, ran.text
    assert ran.json()["job"]["kind"] == "join_detection"
    assert ran.json()["job"]["input"] == {"source_id": source["id"]}


def test_patch_restores_missing_kind_only(client: TestClient) -> None:
    source = _make_source(client, key="partial-seed")
    items = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    by_kind = {item["work_kind"]: item for item in items}
    deleted = client.delete(f"/schedules/{by_kind['join_detection']['id']}")
    assert deleted.status_code == 204
    patched = client.patch(
        f"/sources/{source['id']}", json={"name": "partial-seed-touched"}
    )
    assert patched.status_code == 200, patched.text
    seeded = patched.json()["schedules"]
    assert len(seeded) == 1
    assert seeded[0]["work_kind"] == "join_detection"
    after = client.get(f"/sources/{source['id']}/schedules").json()["items"]
    kinds = {item["work_kind"] for item in after}
    assert kinds == {"structure", "join_detection"}
    assert by_kind["structure"]["id"] in {item["id"] for item in after}

