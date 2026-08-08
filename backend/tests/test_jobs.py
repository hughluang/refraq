"""Platform Job + Celery stub + reaper tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    ERROR_WORKER_LOST,
    create_queued_job,
    get_job_store,
    mark_running,
    reap_stuck_running_jobs,
    reset_job_store,
)
from backend.metadata.source_jobs import dispatch_queued_job  # noqa: E402
from backend.worker.schedules import (  # noqa: E402
    ensure_system_schedules,
    get_schedule_store,
    reset_schedule_store,
)
from backend.worker.models import REAPER_SCHEDULE_KEY  # noqa: E402


@pytest.fixture(autouse=True)
def _eager_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_job_store()
    reset_schedule_store()
    from backend.worker.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    reset_job_store()
    reset_schedule_store()


def test_stub_job_marks_failed_when_source_missing() -> None:
    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_missing"},
        created_by="user_1",
    )
    assert not hasattr(job, "source_id")
    assert job.input["source_id"] == "src_missing"
    dispatch_queued_job(job)
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "JOB_INPUT_INVALID"
    assert stored.finished_at is not None


def test_unknown_kind_marks_failed() -> None:
    job = create_queued_job(kind="nope", input={})
    dispatch_queued_job(job)
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "JOB_INPUT_INVALID"


def test_create_job_with_source_id_in_input() -> None:
    """Store accepts opaque input; source_id is not a universal Job column."""
    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_1"},
    )
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.input == {"source_id": "src_1"}
    assert stored.status == "queued"
    assert not hasattr(stored, "source_id")


def test_reaper_marks_stuck_running() -> None:
    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_1"},
    )
    mark_running(job.id)
    stored = get_job_store().get(job.id)
    assert stored is not None
    stored.started_at = datetime.utcnow() - timedelta(hours=2)
    get_job_store().save(stored)

    count = reap_stuck_running_jobs()
    assert count == 1
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_WORKER_LOST


def test_system_schedule_seed_includes_reaper() -> None:
    ensure_system_schedules()
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    assert record is not None
    assert record.system is True
    assert record.enabled is True
    assert record.interval_seconds == 60
    assert record.task_name == "backend.worker.tasks.reap_stuck_jobs"
    assert record.name == "Reap stuck jobs"
    ensure_system_schedules()
    assert get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY) is not None
