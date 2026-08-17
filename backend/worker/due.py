"""Due-tick consumption for Scheduled Tasks (commitment → Job mint)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.core.time import ensure_aware_utc, utc_now
from backend.worker.cron import (
    compute_next_run_at,
    current_cron_slot_instant,
)
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store


def next_after_mint(record: ScheduledTaskRecord, *, mint_at: datetime) -> datetime:
    """Compute the next commitment Instant after consuming a due tick at mint_at."""
    if record.interval_seconds and record.interval_seconds > 0:
        return mint_at + timedelta(seconds=record.interval_seconds)
    return compute_next_run_at(
        cron=record.cron,
        schedule_timezone=record.schedule_timezone,
        interval_seconds=None,
        after=mint_at,
    )


def _advance_cross_slot(
    record: ScheduledTaskRecord,
    *,
    now: datetime,
    session: Session | None,
    slot: datetime | None,
    last: datetime | None,
) -> dict[str, Any]:
    """Skip a stale cron Instant without catch-up mint.

    Paused rows must not regain a next_run_at. When the current legal wall-clock
    slot is still unconsumed, rewrite the commitment to that slot Instant and
    consume it in the same due handling (second consume) — do not remap the
    stale delivered Instant onto a different scheduled_for.
    """
    if not record.enabled:
        return {"status": "skip_cross_slot"}
    if slot is not None and (last is None or slot > last):
        get_schedule_store().upsert(
            replace(
                record,
                next_run_at=slot,
                updated_at=now,
            ),
            session=session,
        )
        return consume_due_tick(record.id, due_at=slot, session=session)
    advanced = compute_next_run_at(
        cron=record.cron,
        schedule_timezone=record.schedule_timezone,
        interval_seconds=None,
        after=now,
    )
    get_schedule_store().upsert(
        replace(
            record,
            next_run_at=advanced,
            updated_at=now,
        ),
        session=session,
    )
    return {"status": "skip_cross_slot", "next_run_at": advanced.isoformat()}


def consume_due_tick(
    schedule_id: str,
    *,
    due_at: datetime | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Process one Beat due for a schedule row.

    Domain path: ``due_at`` is the commitment Instant Beat dispatched. Honor that
    Instant — do not skip at the door because the row is paused or gone. Returns
    ``mint`` when the caller should insert a Job (``cancel_immediately`` when the
    tick must end cancelled). Cross-slot skip only when the definition still exists.

    System path (no ``due_at``): advance the store commitment only; no Job.
    """
    store = get_schedule_store()
    now = utc_now()

    # System work: no Job; just advance commitment from the live row.
    if due_at is None:
        record = store.get_by_id(schedule_id, session=session)
        if record is None:
            return {"status": "missing"}
        if not record.system:
            return {"status": "missing_due_at"}
        if not record.enabled:
            return {"status": "disabled"}
        if record.next_run_at is None:
            return {"status": "no_commitment"}
        next_at = ensure_aware_utc(record.next_run_at)
        if next_at > now:
            return {"status": "not_due"}
        advanced = compute_next_run_at(
            cron=record.cron,
            schedule_timezone=record.schedule_timezone,
            interval_seconds=record.interval_seconds,
            after=now,
        )
        store.upsert(
            replace(
                record,
                last_run_at=now,
                next_run_at=advanced,
                updated_at=now,
            ),
            session=session,
        )
        return {"status": "system", "ran_at": now.isoformat()}

    due = ensure_aware_utc(due_at)
    record = store.get_by_id(
        schedule_id, session=session, for_update=session is not None
    )

    # Deleted: always mint cancelled for the delivered Instant (no cross-slot gate).
    if record is None:
        return {
            "status": "mint",
            "scheduled_for": due,
            "record": None,
            "now": now,
            "cancel_immediately": True,
        }

    if record.system:
        return {"status": "invalid_due_at_for_system"}

    # Premature delivery of a future commitment (Beat would not have sent yet).
    if due > now:
        return {"status": "not_due"}

    if record.interval_seconds and record.interval_seconds > 0:
        if not record.enabled:
            # Pause cleared next; the delivered Instant still consumes as cancelled.
            return {
                "status": "mint",
                "scheduled_for": due,
                "record": record,
                "now": now,
                "cancel_immediately": True,
            }
        if record.next_run_at is None:
            return {"status": "no_commitment"}
        live_next = ensure_aware_utc(record.next_run_at)
        if due != live_next:
            # Cadence rewrite replaced the commitment this delivery referred to.
            return {"status": "commitment_replaced"}
        # due == live_next; due > now already returned not_due at the door.
        return {
            "status": "mint",
            "scheduled_for": due,
            "record": record,
            "now": now,
            "cancel_immediately": False,
        }

    if record.cron:
        slot = current_cron_slot_instant(
            cron=record.cron,
            schedule_timezone=record.schedule_timezone,
            now=now,
        )
        last = (
            ensure_aware_utc(record.last_run_at) if record.last_run_at is not None else None
        )
        # Current legal slot still due: mint that delivered Instant (gate only).
        if (
            slot is not None
            and due == slot
            and (last is None or due > last)
        ):
            return {
                "status": "mint",
                "scheduled_for": due,
                "record": record,
                "now": now,
                "cancel_immediately": not record.enabled,
            }
        return _advance_cross_slot(
            record, now=now, session=session, slot=slot, last=last
        )

    return {"status": "invalid_cadence"}


def commit_due_mint(
    record: ScheduledTaskRecord,
    *,
    now: datetime,
    session: Session | None = None,
    mint_at: datetime | None = None,
) -> ScheduledTaskRecord | None:
    """Consume the due event: write last_run_at and next from the live enabled flag."""
    consumed_at = mint_at or now
    nxt = next_after_mint(record, mint_at=consumed_at)
    # Clamp interval next to >= wall-clock now on re-entry.
    if nxt < now:
        nxt = now
    return get_schedule_store().consume_due_cursor(
        record.id,
        last_run_at=consumed_at,
        next_if_enabled=nxt,
        session=session,
    )
