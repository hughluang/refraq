"""Job Offset Page: store, platform list, and schedule-related list."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    JobRecord,
    create_queued_job,
    get_job_store,
    reset_job_store,
)
from backend.main import app  # noqa: E402
from backend.metadata.catalog.store import reset_catalog_store  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.schedules import reset_schedule_store  # noqa: E402

STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(
    job_id: str,
    *,
    kind: str = "structure",
    status: str = "queued",
    trigger_kind: str | None = None,
    trigger_ref: str | None = None,
    created_at: datetime = STAMP,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        kind=kind,
        status=status,  # type: ignore[arg-type]
        input={"source_id": "s1"},
        result=None,
        created_by=None,
        celery_task_id=None,
        error_code=None,
        error_summary=None,
        summary=job_id,
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        log_body="",
        log_updated_at=None,
        scheduled_for=None,
        claimed_by=None,
        locked_at=None,
        created_at=created_at,
        started_at=None,
        finished_at=None,
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
    reset_catalog_store()
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
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client


def test_store_pages_and_orders_by_created_at_then_id() -> None:
    reset_job_store()
    store = get_job_store()
    for job_id in ("job_c", "job_a", "job_d", "job_b"):
        store.create(_record(job_id))
    page1, total = store.list(limit=2, offset=0)
    page2, total2 = store.list(limit=2, offset=2)
    assert total == total2 == 4
    assert [row.id for row in page1] == ["job_d", "job_c"]
    assert [row.id for row in page2] == ["job_b", "job_a"]


def test_store_total_respects_filters() -> None:
    reset_job_store()
    store = get_job_store()
    store.create(_record("job_s", kind="structure", status="queued"))
    store.create(_record("job_r", kind="structure", status="running"))
    store.create(_record("job_x", kind="semantics_refresh", status="queued"))
    items, total = store.list(kind="structure", status="queued")
    assert total == 1
    assert [row.id for row in items] == ["job_s"]


def test_store_unbounded_list_returns_all_rows() -> None:
    reset_job_store()
    store = get_job_store()
    for i in range(220):
        store.create(_record(f"job_{i:03d}"))
    items, total = store.list()
    assert total == 220
    assert len(items) == 220


def test_list_jobs_http_envelope_and_pages(client: TestClient) -> None:
    store = get_job_store()
    for job_id in ("job_c", "job_a", "job_d", "job_b"):
        store.create(_record(job_id))

    defaulted = client.get("/jobs")
    assert defaulted.status_code == 200
    body = defaulted.json()
    assert body["total"] == 4
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [
        "job_d",
        "job_c",
        "job_b",
        "job_a",
    ]

    page1 = client.get("/jobs?limit=2&offset=0")
    page2 = client.get("/jobs?limit=2&offset=2")
    assert [item["id"] for item in page1.json()["items"]] == ["job_d", "job_c"]
    assert page1.json()["total"] == 4
    assert [item["id"] for item in page2.json()["items"]] == ["job_b", "job_a"]
    assert page2.json()["offset"] == 2


def test_list_jobs_http_rejects_oversize_limit(client: TestClient) -> None:
    resp = client.get("/jobs?limit=201")
    assert resp.status_code == 422
    assert resp.json()["code"] == "REQUEST_INVALID"


def test_schedule_jobs_pushdown_and_pages(client: TestClient) -> None:
    source = client.post(
        "/sources",
        json={
            "key": "mes-prod",
            "name": "mes-prod",
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
    assert source.status_code == 201, source.text
    source_id = source.json()["source"]["id"]
    created = client.post(
        f"/sources/{source_id}/schedules",
        json={
            "kind": "structure",
            "cron": "0 2 * * *",
            "schedule_timezone": "UTC",
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule"]["id"]
    other_id = "sched_other"

    store = get_job_store()
    for job_id in ("job_z", "job_y", "job_x"):
        store.create(
            _record(
                job_id,
                trigger_kind="schedule",
                trigger_ref=schedule_id,
            )
        )
    store.create(
        _record(
            "job_other",
            trigger_kind="schedule",
            trigger_ref=other_id,
        )
    )
    store.create(_record("job_user", trigger_kind="user", trigger_ref="user_1"))

    listed = client.get(f"/schedules/{schedule_id}/jobs?limit=2&offset=0")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert [item["id"] for item in body["items"]] == ["job_z", "job_y"]
    page2 = client.get(f"/schedules/{schedule_id}/jobs?limit=2&offset=2")
    assert [item["id"] for item in page2.json()["items"]] == ["job_x"]
    assert page2.json()["total"] == 3


def test_single_flight_scan_is_unbounded() -> None:
    """Execution single-flight reads every structure Job, not one HTTP page."""
    reset_job_store()
    store = get_job_store()
    for i in range(60):
        store.create(_record(f"job_{i:03d}", kind="structure", status="running"))
    items, total = store.list(kind="structure")
    assert total == 60
    assert len(items) == 60


def test_create_queued_still_lists_under_http(client: TestClient) -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    listed = client.get("/jobs?kind=structure&status=queued")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == job.id
