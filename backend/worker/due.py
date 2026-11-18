"""Due-tick consumption for Scheduled Tasks (commitment → Job mint)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.core.time import utc_now
from backend.worker.api import current_schedule_timezone
from backend.worker.cron import compute_next_run_at, next_interval_grid_point
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store


def consume_due_tick(
    schedule_id: str,
    *,
    due_at: datetime | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Decide whether the delivered commitment may mint in the caller's transaction."""
    store = get_schedule_store()
    record = store.get_by_id(
        schedule_id, session=session, for_update=session is not None
    )
    now = utc_now()
    if due_at is None:
        if record is None:
            return {"status": "missing"}
        if not record.store_only:
            return {"status": "missing_due_at"}
        if not record.enabled:
            return {"status": "disabled"}
        if record.next_run_at is None:
            return {"status": "no_commitment"}
        if record.next_run_at > now:
            return {"status": "not_due"}
        advanced = compute_next_run_at(
            cron=record.cron,
            schedule_timezone=record.commitment_timezone,
            interval_seconds=record.interval_seconds,
            after=now,
            start_at=record.start_at,
        )
        store.upsert(
            replace(record, last_run_at=now, next_run_at=advanced, updated_at=now),
            session=session,
        )
        return {"status": "system", "ran_at": now.isoformat()}

    due = due_at
    if record is None:
        return {
            "status": "mint",
            "scheduled_for": due,
            "record": None,
            "now": now,
            "cancel_immediately": True,
            "is_delayed_recovery": False,
        }
    if record.store_only:
        return {"status": "invalid_due_at_for_system"}
    if due > now:
        return {"status": "not_due"}
    if record.enabled:
        if record.next_run_at is None:
            return {"status": "no_commitment"}
        if due != record.next_run_at:
            return {"status": "commitment_replaced"}
    if record.cron:
        legal = compute_next_run_at(
            cron=record.cron,
            schedule_timezone=current_schedule_timezone(),
            interval_seconds=None,
            after=due - timedelta(microseconds=1),
            start_at=record.start_at,
        )
        if legal != due:
            return {"status": "commitment_replaced"}
        if record.last_run_at is not None and due <= record.last_run_at:
            return {"status": "already_consumed"}
    elif not record.interval_seconds or record.interval_seconds <= 0:
        return {"status": "invalid_cadence"}
    return {
        "status": "mint",
        "scheduled_for": due,
        "record": record,
        "now": now,
        "cancel_immediately": not record.enabled,
        "is_delayed_recovery": bool(
            record.enabled and record.cron and now >= due + timedelta(seconds=60)
        ),
    }


def commit_due_mint(
    record: ScheduledTaskRecord,
    *,
    now: datetime,
    session: Session | None = None,
    mint_at: datetime | None = None,
) -> ScheduledTaskRecord | None:
    """Consume one commitment without creating a backlog of historical slots."""
    consumed_at = mint_at or now
    seconds = record.interval_seconds
    if seconds and seconds > 0 and record.start_at is not None:
        zone = None
        nxt = next_interval_grid_point(record.start_at, seconds, after=now)
    elif seconds and seconds > 0:
        zone = None
        nxt = max(consumed_at + timedelta(seconds=seconds), now)
    else:
        zone = current_schedule_timezone()
        nxt = compute_next_run_at(
            cron=record.cron,
            schedule_timezone=zone,
            interval_seconds=None,
            after=now,
            start_at=record.start_at,
        )
    return get_schedule_store().consume_due_cursor(
        record.id,
        last_run_at=consumed_at,
        next_if_enabled=nxt,
        commitment_timezone=zone,
        session=session,
    )
