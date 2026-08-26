"""Source work Job execution shell: claim, Kind execution lock, Source usability."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    claim_queued,
    create_queued_job,
    get_job_store,
    mark_succeeded,
    reset_job_store,
)
from backend.metadata.source_job_runner import (  # noqa: E402
    run_source_work_job,
    try_acquire_kind_execution_lock,
)
from backend.metadata.sources.service import create_source  # noqa: E402
from backend.metadata.sources.store import get_source_store, reset_source_store  # noqa: E402
from backend.worker.schedules import reset_schedule_store  # noqa: E402


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_settings_cache()
    reset_job_store()
    reset_source_store()
    reset_schedule_store()


def _source(*, key: str = "runner-src"):
    return create_source(
        key=key,
        name="Runner",
        kind="database",
        description=None,
        engine="postgresql",
        access={
            "host": "127.0.0.1",
            "port": 5432,
            "username": "u",
            "password": "p",
            "ssl_mode": "require",
            "database": "db",
            "schema": "public",
            "extra": {},
        },
    )


def _ok_body(job_id: str, source) -> dict[str, str]:
    return {"status": "succeeded", "source_id": source.id, "job_id": job_id}


def test_missing_job_returns_missing() -> None:
    calls: list[str] = []

    def body(job_id: str, source) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        "job_missing",
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out == {"status": "missing"}
    assert calls == []


def test_already_terminal_returns_status_without_body() -> None:
    source = _source()
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    claimed = claim_queued(job.id, claimed_by="w1")
    assert claimed is not None
    mark_succeeded(job.id, result={"ok": True})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out == {"status": "succeeded"}
    assert calls == []


def test_already_running_returns_status_without_body() -> None:
    source = _source()
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    claimed = claim_queued(job.id, claimed_by="w1")
    assert claimed is not None
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out == {"status": "running"}
    assert calls == []


def test_kind_mismatch_fails_input_invalid() -> None:
    source = _source()
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="join_detection",
        start_message="started",
        body=body,
    )
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_INPUT_INVALID"
    assert calls == []
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.error_code == "JOB_INPUT_INVALID"


def test_non_string_source_id_fails_input_invalid() -> None:
    job = create_queued_job(kind="structure", input={"source_id": 42})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_INPUT_INVALID"
    assert calls == []


def test_source_not_found_fails_input_invalid() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "src_gone"})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_INPUT_INVALID"
    assert calls == []


def test_disabled_source_fails_source_disabled() -> None:
    source = _source(key="disabled-src")
    get_source_store().save_source(replace(source, status="disabled", updated_at=utc_now()))
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded"}

    out = run_source_work_job(
        job.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_SOURCE_DISABLED"
    assert calls == []


def test_same_kind_lock_blocks_body() -> None:
    source = _source(key="lock-same")
    held = try_acquire_kind_execution_lock("structure", source.id)
    assert held is not None
    try:
        job = create_queued_job(kind="structure", input={"source_id": source.id})
        calls: list[str] = []

        def body(job_id: str, src) -> dict[str, str]:
            calls.append(job_id)
            return {"status": "succeeded"}

        out = run_source_work_job(
            job.id,
            kind="structure",
            start_message="started",
            body=body,
        )
        assert out["status"] == "failed"
        assert out["error_code"] == "JOB_ALREADY_ACTIVE"
        assert calls == []
        stored = get_job_store().get(job.id)
        assert stored is not None
        assert "structure Kind execution lock" in (stored.error_summary or "")
    finally:
        held.release()


def test_cross_kind_lock_allows_body() -> None:
    source = _source(key="lock-cross")
    held = try_acquire_kind_execution_lock("join_detection", source.id)
    assert held is not None
    try:
        job = create_queued_job(kind="structure", input={"source_id": source.id})
        out = run_source_work_job(
            job.id,
            kind="structure",
            start_message="started",
            body=_ok_body,
        )
        assert out["status"] == "succeeded"
        assert out["source_id"] == source.id
    finally:
        held.release()


def test_body_success_and_lock_released_for_next_job() -> None:
    source = _source(key="lock-release")
    first = create_queued_job(kind="structure", input={"source_id": source.id})
    out1 = run_source_work_job(
        first.id,
        kind="structure",
        start_message="started",
        body=_ok_body,
    )
    assert out1["status"] == "succeeded"

    second = create_queued_job(kind="structure", input={"source_id": source.id})
    calls: list[str] = []

    def body(job_id: str, src) -> dict[str, str]:
        calls.append(job_id)
        return {"status": "succeeded", "job_id": job_id}

    out2 = run_source_work_job(
        second.id,
        kind="structure",
        start_message="started",
        body=body,
    )
    assert out2["status"] == "succeeded"
    assert calls == [second.id]
