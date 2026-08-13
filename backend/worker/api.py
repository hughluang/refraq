"""Published helpers for composition / upgrade assembly."""

from __future__ import annotations

from backend.core.time import utc_now
import uuid

from backend.worker.models import REAPER_SCHEDULE_KEY, REAPER_TASK_NAME
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

__all__ = ["ensure_system_schedules"]


def ensure_system_schedules() -> None:
    """Idempotent seed for platform Scheduled Tasks (reaper)."""
    store = get_schedule_store()
    if store.get_by_key(REAPER_SCHEDULE_KEY) is not None:
        return
    now = utc_now()
    store.upsert(
        ScheduledTaskRecord(
            id=f"sched_{uuid.uuid4().hex[:12]}",
            key=REAPER_SCHEDULE_KEY,
            name="Reap stuck jobs",
            enabled=True,
            interval_seconds=60,
            cron=None,
            schedule_timezone="UTC",
            task_name=REAPER_TASK_NAME,
            args_json=[],
            kwargs_json={},
            system=True,
            created_at=now,
            updated_at=now,
        )
    )
