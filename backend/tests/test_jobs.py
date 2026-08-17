"""Platform Job + Celery stub + reaper tests."""

from __future__ import annotations

from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock, utc_now
import os
from datetime import timedelta

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    ERROR_WORKER_LOST,
    claim_queued,
    create_queued_job,
    get_job_store,
    reap_stuck_running_jobs,
    reset_job_store,
)
from backend.worker.app import celery_app  # noqa: E402
from backend.metadata.source_jobs import dispatch_queued_job  # noqa: E402
from backend.worker.api import ensure_system_schedules  # noqa: E402
from backend.worker.schedules import get_schedule_store, reset_schedule_store  # noqa: E402
from backend.worker.models import REAPER_SCHEDULE_KEY  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def _eager_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_job_store()
    reset_schedule_store()
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


def test_reaper_marks_running_timeout() -> None:
    from backend.jobs.store import ERROR_RUNNING_TIMEOUT

    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_1"},
    )
    claimed = claim_queued(job.id)
    assert claimed is not None
    stored = get_job_store().get(job.id)
    assert stored is not None
    stored.started_at = utc_now() - timedelta(hours=2)
    stored.locked_at = utc_now()  # occupancy still fresh → timeout, not lost
    get_job_store().save(stored)

    count = reap_stuck_running_jobs()
    assert count == 1
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_RUNNING_TIMEOUT


def test_reaper_marks_worker_lost() -> None:
    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_1"},
    )
    claimed = claim_queued(job.id)
    assert claimed is not None
    stored = get_job_store().get(job.id)
    assert stored is not None
    stored.claimed_by = "celery@worker-a"
    stored.locked_at = utc_now() - timedelta(minutes=5)
    stored.started_at = utc_now() - timedelta(minutes=5)
    get_job_store().save(stored)

    count = reap_stuck_running_jobs()
    assert count == 1
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_WORKER_LOST


def test_claim_queued_is_cas() -> None:
    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    first = claim_queued(job.id, claimed_by="w1")
    assert first is not None
    assert first.status == "running"
    second = claim_queued(job.id, claimed_by="w2")
    assert second is None
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.claimed_by == "w1"


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


def test_reaper_task_consumes_commitment() -> None:
    from dataclasses import replace

    from backend.worker.tasks import reap_stuck_jobs

    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    try:
        ensure_system_schedules()
        record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert record is not None
        get_schedule_store().upsert(
            replace(
                record,
                last_run_at=parse_instant("2026-08-16T09:59:00Z"),
                next_run_at=clock.now(),
            )
        )
        result = reap_stuck_jobs()
        assert result["reaped"] == 0
        refreshed = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert refreshed is not None
        assert refreshed.last_run_at == clock.now()
        assert refreshed.next_run_at == clock.now() + timedelta(seconds=60)
        reap_stuck_jobs()
        again = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert again is not None
        assert again.next_run_at == refreshed.next_run_at
        assert again.last_run_at == refreshed.last_run_at
    finally:
        reset_clock()


def test_reaper_does_not_overwrite_cancelled() -> None:
    from backend.jobs.store import mark_cancelled, mark_failed

    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by="w1")
    assert claimed is not None
    cancelled = mark_cancelled(job.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"

    updated = mark_failed(
        job.id,
        error_code=ERROR_WORKER_LOST,
        error_summary="Worker lost: occupancy declaration stale",
        from_statuses=("running",),
    )
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.error_code != ERROR_WORKER_LOST


def test_cancel_unfinished_does_not_overwrite_succeeded() -> None:
    from backend.jobs.store import cancel_unfinished_for_schedule, mark_succeeded

    job = create_queued_job(
        kind="structure",
        input={"source_id": "src_1"},
        trigger_kind="schedule",
        trigger_ref="sched_1",
    )
    claimed = claim_queued(job.id)
    assert claimed is not None
    mark_succeeded(job.id, result={"ok": True})
    cancelled = cancel_unfinished_for_schedule("sched_1")
    assert cancelled == []
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "succeeded"


def test_dispatch_does_not_revert_claimed_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """After claim, dispatch must only patch celery_task_id (not rewrite status)."""
    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by="worker@host")
    assert claimed is not None
    assert claimed.status == "running"

    stale = get_job_store().get(job.id)
    assert stale is not None
    # Simulate a stale queued snapshot that old dispatch would have saved back.
    from dataclasses import replace

    queued_snapshot = replace(
        stale,
        status="queued",
        claimed_by=None,
        locked_at=None,
        started_at=None,
    )

    monkeypatch.setattr(
        "backend.metadata.source_jobs.run_job.apply_async",
        lambda *a, **k: type("R", (), {"id": "task-xyz"})(),
    )
    # Old bug path used get()+save(queued); new path ignores the snapshot.
    dispatch_queued_job(queued_snapshot)
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "running"
    assert stored.claimed_by == "worker@host"
    assert stored.celery_task_id == "task-xyz"


def test_second_run_structure_job_does_not_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata.structure_jobs.service import run_structure_job

    calls: list[str] = []

    def boom(_job_id: str) -> None:
        calls.append("collect")
        raise AssertionError("must not collect on second entry")

    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.append_job_log",
        lambda *a, **k: None,
    )
    # Force collect path not to run by ensuring claim fails on second entry.
    job = create_queued_job(kind="structure", input={"source_id": "src_missing"})
    first = claim_queued(job.id, claimed_by="w1")
    assert first is not None
    # Second entry: claim returns None → early return without domain work.
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.prepare",
        boom,
    )
    outcome = run_structure_job(job.id)
    assert outcome["status"] == "running"
    assert calls == []


def test_occupancy_worker_id_is_never_empty() -> None:
    from backend.jobs.store import UNKNOWN_WORKER_ID, occupancy_worker_id

    assert occupancy_worker_id(None) == UNKNOWN_WORKER_ID
    assert occupancy_worker_id("") == UNKNOWN_WORKER_ID
    assert occupancy_worker_id("   ") == UNKNOWN_WORKER_ID
    assert occupancy_worker_id("celery@w1") == "celery@w1"


def test_direct_claim_without_hostname_matches_occupancy_renew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-task-context claim must write the same id occupancy renews."""
    from backend.jobs.store import UNKNOWN_WORKER_ID, occupancy_worker_id, touch_occupancy
    from backend.metadata.structure_jobs.service import _claim_worker_id, run_structure_job

    monkeypatch.setattr(
        "celery.current_task",
        type("T", (), {"request": type("R", (), {"hostname": None})()})(),
    )
    assert _claim_worker_id() == occupancy_worker_id(None) == UNKNOWN_WORKER_ID

    job = create_queued_job(kind="structure", input={"source_id": "src_missing"})
    run_structure_job(job.id)
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.claimed_by == UNKNOWN_WORKER_ID

    running = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(running.id, claimed_by=_claim_worker_id())
    assert claimed is not None
    assert claimed.claimed_by == UNKNOWN_WORKER_ID
    assert touch_occupancy(UNKNOWN_WORKER_ID) == 1


def test_claim_worker_id_exception_uses_shared_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.jobs.store import UNKNOWN_WORKER_ID
    from backend.metadata.structure_jobs.service import _claim_worker_id

    class Boom:
        @property
        def request(self):
            raise RuntimeError("no task context")

    monkeypatch.setattr("celery.current_task", Boom())
    assert _claim_worker_id() == UNKNOWN_WORKER_ID


def test_occupancy_ready_uses_shared_worker_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.jobs.store import UNKNOWN_WORKER_ID
    from backend.worker import occupancy

    monkeypatch.setattr(occupancy, "_renew_loop", lambda: None)
    occupancy.on_worker_shutdown()
    occupancy.on_worker_ready(sender=type("S", (), {"hostname": None})())
    assert occupancy._worker_id == UNKNOWN_WORKER_ID
    occupancy.on_worker_ready(sender=type("S", (), {"hostname": "celery@w1"})())
    assert occupancy._worker_id == "celery@w1"
    occupancy.on_worker_shutdown()


def test_startup_abandons_fresh_leftover_same_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same nodename restart must not renew a previous generation's running Job."""
    from backend.jobs.store import touch_occupancy
    from backend.worker import occupancy

    monkeypatch.setattr(occupancy, "_renew_loop", lambda: None)
    occupancy.on_worker_shutdown()

    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by="celery@w1")
    assert claimed is not None
    stored = get_job_store().get(job.id)
    assert stored is not None
    stored.locked_at = utc_now()  # still within lost-detection window
    get_job_store().save(stored)

    occupancy.on_worker_ready(sender=type("S", (), {"hostname": "celery@w1"})())
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_WORKER_LOST
    assert touch_occupancy("celery@w1") == 0
    occupancy.on_worker_shutdown()


def test_startup_does_not_abandon_other_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.worker import occupancy

    monkeypatch.setattr(occupancy, "_renew_loop", lambda: None)
    occupancy.on_worker_shutdown()

    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by="celery@w2")
    assert claimed is not None

    occupancy.on_worker_ready(sender=type("S", (), {"hostname": "celery@w1"})())
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "running"
    occupancy.on_worker_shutdown()


def test_startup_same_generation_ready_does_not_kill_own_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.jobs.store import touch_occupancy
    from backend.worker import occupancy

    monkeypatch.setattr(occupancy, "_renew_loop", lambda: None)
    occupancy.on_worker_shutdown()
    occupancy.on_worker_ready(sender=type("S", (), {"hostname": "celery@w1"})())

    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by="celery@w1")
    assert claimed is not None
    assert touch_occupancy("celery@w1") == 1

    # Same process, same identity: second ready must not abandon this generation.
    occupancy.on_worker_ready(sender=type("S", (), {"hostname": "celery@w1"})())
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "running"
    assert touch_occupancy("celery@w1") == 1
    occupancy.on_worker_shutdown()


def test_startup_unknown_does_not_abandon_shared_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.jobs.store import UNKNOWN_WORKER_ID
    from backend.worker import occupancy

    monkeypatch.setattr(occupancy, "_renew_loop", lambda: None)
    occupancy.on_worker_shutdown()

    job = create_queued_job(kind="structure", input={"source_id": "src_1"})
    claimed = claim_queued(job.id, claimed_by=UNKNOWN_WORKER_ID)
    assert claimed is not None

    occupancy.on_worker_ready(sender=type("S", (), {"hostname": None})())
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "running"
    occupancy.on_worker_shutdown()
