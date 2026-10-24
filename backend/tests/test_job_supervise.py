"""Supervisor kills a cancelled Job's child and leaves a failed stamp alone."""

from __future__ import annotations

import os
import subprocess
import sys

from backend.jobs.job_child import main
from backend.jobs.store import (
    CLAIMED_ENV,
    claim_queued,
    create_queued_job,
    get_job_store,
    mark_cancelled,
    mark_failed,
)
from backend.jobs.supervise import watch_process


def _adopt_probe(job_id: str) -> None:
    captured["job_id"] = job_id
    captured["claimed"] = os.environ.get(CLAIMED_ENV)


captured: dict[str, str | None] = {}


def _sleeper(seconds: float) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        start_new_session=True,
    )


def test_child_adopts_the_claim_itself() -> None:
    previous = os.environ.pop(CLAIMED_ENV, None)
    captured.clear()
    try:
        main(["backend.tests.test_job_supervise:_adopt_probe", "job_1"])
        assert captured == {"job_id": "job_1", "claimed": "1"}
    finally:
        if previous is None:
            os.environ.pop(CLAIMED_ENV, None)
        else:
            os.environ[CLAIMED_ENV] = previous


def test_cancel_kills_the_child_and_keeps_cancelled() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    assert claim_queued(job.id, claimed_by="worker@test") is not None
    proc = _sleeper(30)
    try:
        mark_cancelled(job.id)
        code = watch_process(job.id, proc, poll_sec=0.05)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert code < 0
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "cancelled"
    assert stored.error_code is None


def test_persistent_redelivery_skips_child_when_not_queued(monkeypatch) -> None:
    from backend.core.config import get_settings
    from backend.jobs import supervise as supervise_mod

    signing = get_settings().model_copy(update={"store_backend": "persistent"})
    monkeypatch.setattr(supervise_mod, "get_settings", lambda: signing)
    spawned: list[str] = []

    def _refuse_spawn(job_id: str, target: str) -> subprocess.Popen[bytes]:
        spawned.append(job_id)
        raise AssertionError("job_child must not start")

    monkeypatch.setattr(supervise_mod, "_spawn", _refuse_spawn)
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    assert claim_queued(job.id, claimed_by="worker@test") is not None
    result = supervise_mod.supervise(job.id, "backend.tests.test_job_supervise:_adopt_probe")
    assert result == {"status": "running"}
    assert spawned == []
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "running"


def test_running_timeout_does_not_kill_the_child() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "s1"})
    assert claim_queued(job.id, claimed_by="worker@test") is not None
    proc = _sleeper(0.3)
    try:
        mark_failed(
            job.id,
            error_code="JOB_RUNNING_TIMEOUT",
            error_summary="timeout",
        )
        code = watch_process(job.id, proc, poll_sec=0.05)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert code == 0
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "JOB_RUNNING_TIMEOUT"
