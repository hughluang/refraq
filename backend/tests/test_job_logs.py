"""Job log_body, summary/trigger, and platform list/logs HTTP."""

from __future__ import annotations

import os

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
from backend.jobs.store import (  # noqa: E402
    append_job_log,
    create_queued_job,
    get_job_store,
    reset_job_store,
)
from backend.main import app  # noqa: E402
from backend.metadata.catalog.store import reset_catalog_store  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402


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


def test_append_job_log_lines() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    append_job_log(job.id, level="info", message="first")
    append_job_log(job.id, level="warn", message="second")
    stored = get_job_store().get(job.id)
    assert stored is not None
    lines = stored.log_body.splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("INFO first")
    assert lines[1].endswith("WARN second")
    assert stored.log_updated_at is not None


def test_create_with_summary_and_trigger() -> None:
    job = create_queued_job(
        kind="structure",
        input={"source_id": "s1"},
        created_by="user_1",
        summary="structure · demo",
        trigger_kind="user",
        trigger_ref="user_1",
        log_body="2026-01-01T00:00:00Z INFO queued",
    )
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.summary == "structure · demo"
    assert stored.trigger_kind == "user"
    assert stored.trigger_ref == "user_1"
    assert "queued" in stored.log_body


def test_list_jobs_and_logs_http(client: TestClient) -> None:
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    job = create_queued_job(
        kind="structure",
        input={"source_id": "s1"},
        summary="structure · demo",
        trigger_kind="user",
        trigger_ref=admin.id,
    )
    missing = create_queued_job(
        kind="structure",
        input={"source_id": "s1"},
        summary="structure · orphan",
        trigger_kind="user",
        trigger_ref="user_missing",
    )
    append_job_log(job.id, level="info", message="hello")

    listed = client.get("/jobs")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(i["id"] == job.id for i in items)
    row = next(i for i in items if i["id"] == job.id)
    assert row["summary"] == "structure · demo"
    assert row["trigger_kind"] == "user"
    assert row["trigger_actor_name"] == "Admin"
    assert "log_body" not in row
    orphan = next(i for i in items if i["id"] == missing.id)
    assert orphan["trigger_actor_name"] is None

    detail = client.get(f"/jobs/{job.id}")
    assert detail.status_code == 200
    assert detail.json()["job"]["trigger_actor_name"] == "Admin"

    logs = client.get(f"/jobs/{job.id}/logs")
    assert logs.status_code == 200
    body = logs.json()
    assert body["job_id"] == job.id
    assert "INFO hello" in body["body"]


def test_cancel_returns_log_updated_at(client: TestClient) -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    cancelled = client.post(f"/jobs/{job.id}/cancel")
    assert cancelled.status_code == 200
    payload = cancelled.json()["job"]
    assert payload["status"] == "cancelled"
    assert payload["log_updated_at"] is not None

    logs = client.get(f"/jobs/{job.id}/logs")
    assert logs.status_code == 200
    assert "WARN cancelled" in logs.json()["body"]
