"""Ingestion Job + Celery stub + reaper tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.metadata.enqueue import enqueue_ingestion_job  # noqa: E402
from backend.metadata.jobs import (  # noqa: E402
    ERROR_HANDLER_UNAVAILABLE,
    ERROR_WORKER_LOST,
    create_queued_job,
    get_job_store,
    mark_running,
    reap_stuck_running_jobs,
    reset_job_store,
)
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
    # Reload celery conf for eager flag
    from backend.worker.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    reset_job_store()
    reset_schedule_store()


def test_stub_ingestion_marks_failed_with_stable_code() -> None:
    job = create_queued_job(
        connection_id="conn_1",
        source_system_id="src_1",
        kind="structure",
        created_by="user_1",
    )
    enqueue_ingestion_job(job)
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_HANDLER_UNAVAILABLE
    assert stored.finished_at is not None


def test_reaper_marks_stuck_running() -> None:
    job = create_queued_job(
        connection_id="conn_1",
        source_system_id="src_1",
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
    ensure_system_schedules()
    assert get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY) is not None
