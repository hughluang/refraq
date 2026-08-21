"""HTTP and MCP must present a mechanism Job through the same projection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.jobs.store import create_queued_job, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.mcp_server import get_job as mcp_get_job  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
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


def _pat_secret(client: TestClient) -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": "job-pat", "expires_at": expires})
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def test_get_job_field_parity_between_http_and_mcp(client: TestClient) -> None:
    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    secret = _pat_secret(client)

    http_body = client.get(f"/jobs/{job.id}")
    assert http_body.status_code == 200, http_body.text
    http_job = http_body.json()["job"]

    mcp_job = json.loads(mcp_get_job(authorization=f"Bearer {secret}", job_id=job.id))
    assert "error" not in mcp_job, mcp_job

    assert mcp_job.keys() == http_job.keys()
    assert mcp_job == http_job

    # Guard the two things equality alone would not prove: that the projection
    # is the wide one (not the old hand-written subset) and that Instants agree
    # on the wire format rather than both being absent.
    assert "trigger_schedule_name" in mcp_job
    assert mcp_job["created_at"].endswith("Z")


def test_get_job_missing_reports_error(client: TestClient) -> None:
    secret = _pat_secret(client)
    payload = json.loads(
        mcp_get_job(authorization=f"Bearer {secret}", job_id="job_missing")
    )
    assert payload["error"]["code"] == "JOB_NOT_FOUND"


# The MCP tool host runs as its own process, where `backend.main` never loads
# and therefore never binds the Scheduled Task name adapter. In-process tests
# cannot cover that: `backend.main` is already imported by the fixture above,
# so its binding would mask a missing one in `mcp_server`. Hence a subprocess.
_STANDALONE_PROBE = """
import os, sys
os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

import backend.metadata.mcp_server  # noqa: F401

assert "backend.main" not in sys.modules, "probe must not load the HTTP composition"

from backend.admin.user_store import get_user_store
from backend.jobs.api import get_schedule_name_store, present_jobs
from backend.jobs.store import create_queued_job

job = create_queued_job(kind="structure", input={"source_id": "src_1"})
presented = present_jobs(
    [job], users=get_user_store(), schedules=get_schedule_name_store()
)
assert presented[0].id == job.id
print("ok")
"""


def test_mcp_host_presents_jobs_without_the_http_composition() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _STANDALONE_PROBE],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    assert completed.returncode == 0, completed.stderr
    assert "ok" in completed.stdout
