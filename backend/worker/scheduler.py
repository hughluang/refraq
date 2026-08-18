"""Celery Beat scheduler that reads Scheduled Task rows from Postgres/memory store."""

from __future__ import annotations

from datetime import timedelta

from celery.beat import ScheduleEntry, Scheduler

from backend.core.time import format_instant
from backend.worker.api import ensure_system_schedules
from backend.worker.cron import CommitmentSchedule
from backend.worker.parameters import BEAT_MAX_INTERVAL_SEC, BEAT_SYNC_EVERY_SEC
from backend.worker.schedules import get_schedule_store


class DatabaseScheduler(Scheduler):
    """Reload enabled Scheduled Task definitions from the schedule store.

    Due is driven solely by stored ``next_run_at`` (CommitmentSchedule).
    Consuming a due tick (mint + cursor) happens inside the fired task / due helper —
    not via unconditional touch_last_run.

    Beat ``last_run_at`` is a delivery cursor for the in-memory commitment snapshot
    (not the store's consumed-due ``last_run_at``). Entries load with last_run_at
    just before next_run_at so an overdue row can dispatch once; after send, Celery
    advances last_run_at and CommitmentSchedule will not tight-loop.

    Domain entries inject delivery-time ``due_at`` (the commitment Instant) into Celery
    kwargs only — not into the stored kwargs_json — so the worker can honor that tick
    even after pause clears next_run_at or delete removes the row.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sync_every = BEAT_SYNC_EVERY_SEC
        self.max_interval = BEAT_MAX_INTERVAL_SEC

    def setup_schedule(self) -> None:
        ensure_system_schedules()
        super().setup_schedule()
        self.merge_inplace(self._load_entries())
        self._heap = None

    def sync(self) -> None:
        ensure_system_schedules()
        self.merge_inplace(self._load_entries())
        super().sync()
        self._heap = None

    def _load_entries(self) -> dict[str, ScheduleEntry]:
        entries: dict[str, ScheduleEntry] = {}
        for record in get_schedule_store().list_enabled():
            if record.next_run_at is None:
                continue
            schedule = CommitmentSchedule(record.next_run_at)
            kwargs = dict(record.kwargs_json)
            # System rows keep store-only consume (no Job); do not inject due_at.
            if not record.system:
                kwargs["due_at"] = format_instant(
                    record.next_run_at, timespec="microseconds"
                )
            # Celery treats last_run_at=None as now(), which would skip an overdue
            # commitment after the one-shot is_due rule. Mark as not-yet-dispatched.
            entries[record.key] = ScheduleEntry(
                name=record.key,
                task=record.task_name,
                schedule=schedule,
                args=tuple(record.args_json),
                kwargs=kwargs,
                options={"ignore_result": True},
                last_run_at=record.next_run_at - timedelta(microseconds=1),
                total_run_count=0,
                app=self.app,
            )
        return entries
