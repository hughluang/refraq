"""Beat CommitmentSchedule: dispatch a stored next_run_at once, do not tight-loop."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from backend.core.time import FixedClock, format_instant, parse_instant, reset_clock, set_clock
from backend.metadata.source_schedules import STRUCTURE_ENQUEUE_TASK_NAME
from backend.worker.api import ensure_system_schedules
from backend.worker.app import celery_app
from backend.worker.cron import CommitmentSchedule
from backend.worker.models import REAPER_SCHEDULE_KEY
from backend.worker.scheduler import DatabaseScheduler
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store


def test_overdue_commitment_is_due_once_per_dispatch() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    try:
        next_at = parse_instant("2026-08-16T09:00:00Z")
        sched = CommitmentSchedule(next_at)
        due, _delay = sched.is_due(next_at - timedelta(microseconds=1))
        assert due is True
        due_again, wait = sched.is_due(clock.now())
        assert due_again is False
        assert wait >= 1.0
    finally:
        reset_clock()


def test_overdue_commitment_does_not_tight_loop_on_beat_tick() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    sent: list[str] = []
    try:
        ensure_system_schedules()
        record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert record is not None
        get_schedule_store().upsert(
            replace(record, next_run_at=clock.now() - timedelta(hours=1))
        )
        scheduler = DatabaseScheduler(app=celery_app, lazy=True)
        scheduler.setup_schedule()

        def _capture(entry, producer=None):
            sent.append(entry.name)

        scheduler.apply_entry = _capture  # type: ignore[method-assign]
        scheduler.should_sync = lambda: False  # type: ignore[method-assign]
        for _ in range(20):
            scheduler.tick()
        assert sent == [REAPER_SCHEDULE_KEY]
    finally:
        reset_clock()


def test_overdue_commitment_retries_after_sync_window() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    try:
        next_at = parse_instant("2026-08-16T09:00:00Z")
        sched = CommitmentSchedule(next_at)
        dispatched_at = clock.now()
        assert sched.is_due(dispatched_at)[0] is False
        clock.advance(timedelta(seconds=31))
        assert sched.is_due(dispatched_at)[0] is True
    finally:
        reset_clock()


def test_new_commitment_instant_is_due_after_prior_dispatch() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:01:00Z"))
    set_clock(clock)
    try:
        sched = CommitmentSchedule(parse_instant("2026-08-16T10:00:30Z"))
        due, _delay = sched.is_due(parse_instant("2026-08-16T10:00:00Z"))
        assert due is True
    finally:
        reset_clock()


def test_sync_does_not_redispatch_same_overdue_commitment_immediately() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    sent: list[str] = []
    try:
        ensure_system_schedules()
        record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert record is not None
        get_schedule_store().upsert(
            replace(record, next_run_at=clock.now() - timedelta(hours=1))
        )
        scheduler = DatabaseScheduler(app=celery_app, lazy=True)
        scheduler.setup_schedule()
        scheduler.apply_entry = lambda entry, producer=None: sent.append(entry.name)  # type: ignore[method-assign]
        scheduler.should_sync = lambda: False  # type: ignore[method-assign]
        scheduler.tick()
        assert sent == [REAPER_SCHEDULE_KEY]
        scheduler.sync()
        sent.clear()
        for _ in range(10):
            scheduler.tick()
        assert sent == []
    finally:
        reset_clock()


def test_domain_entry_kwargs_include_due_at_system_does_not() -> None:
    clock = FixedClock(parse_instant("2026-08-16T10:00:00Z"))
    set_clock(clock)
    try:
        ensure_system_schedules()
        reaper = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
        assert reaper is not None
        due = clock.now() - timedelta(minutes=5)
        get_schedule_store().upsert(replace(reaper, next_run_at=due))
        get_schedule_store().upsert(
            ScheduledTaskRecord(
                id="sched_due_kw",
                key="structure:src_x:sched_due_kw",
                name="structure · due-kw",
                enabled=True,
                interval_seconds=3600,
                cron=None,
                task_name=STRUCTURE_ENQUEUE_TASK_NAME,
                args_json=[],
                kwargs_json={"source_id": "src_x", "schedule_id": "sched_due_kw"},
                system=False,
                schedule_timezone="UTC",
                owner_ref="metadata:source:src_x",
                last_run_at=clock.now(),
                next_run_at=due,
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        scheduler = DatabaseScheduler(app=celery_app, lazy=True)
        entries = scheduler._load_entries()
        domain = entries["structure:src_x:sched_due_kw"]
        assert domain.kwargs["source_id"] == "src_x"
        assert domain.kwargs["due_at"] == format_instant(due, timespec="microseconds")
        # Stored kwargs_json must not gain due_at from Beat injection.
        stored = get_schedule_store().get_by_id("sched_due_kw")
        assert stored is not None
        assert "due_at" not in stored.kwargs_json
        system_entry = entries[REAPER_SCHEDULE_KEY]
        assert "due_at" not in system_entry.kwargs
    finally:
        reset_clock()
