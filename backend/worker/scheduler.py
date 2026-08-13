"""Celery Beat scheduler that reads Scheduled Task rows from Postgres/memory store."""

from __future__ import annotations

from celery.beat import ScheduleEntry, Scheduler

from backend.core.time import utc_now
from backend.worker.cron import build_celery_schedule
from backend.worker.schedules import get_schedule_store


class DatabaseScheduler(Scheduler):
    """Reload enabled Scheduled Task definitions from the schedule store."""

    sync_every = 30

    def setup_schedule(self) -> None:
        self.merge_inplace(self._load_entries())
        super().setup_schedule()

    def sync(self) -> None:
        self.merge_inplace(self._load_entries())
        super().sync()

    def _load_entries(self) -> dict[str, ScheduleEntry]:
        entries: dict[str, ScheduleEntry] = {}
        for record in get_schedule_store().list_enabled():
            schedule = build_celery_schedule(
                cron=record.cron,
                schedule_timezone=record.schedule_timezone,
                interval_seconds=record.interval_seconds,
            )
            if schedule is None:
                continue
            entries[record.key] = ScheduleEntry(
                name=record.key,
                task=record.task_name,
                schedule=schedule,
                args=tuple(record.args_json),
                kwargs=dict(record.kwargs_json),
                options={"ignore_result": True},
                last_run_at=record.last_run_at,
                total_run_count=0,
                app=self.app,
            )
        return entries

    def apply_entry(self, entry: ScheduleEntry, producer=None):
        result = super().apply_entry(entry, producer=producer)
        get_schedule_store().touch_last_run(entry.name, utc_now())
        return result
