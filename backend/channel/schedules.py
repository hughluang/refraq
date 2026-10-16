"""Publish sync of one channel Scheduled Task, and the due-tick that mints a run."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from celery import shared_task

from backend.channel.channel_run import dispatch, mint_scheduled_run
from backend.channel.store import ChannelRecord, get_channel_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import ensure_aware_utc, parse_instant, utc_now
from backend.jobs.api import revoke_queued_delivery
from backend.jobs.store import (
    TERMINAL,
    JobRecord,
    get_job_store,
    mark_cancelled,
)
from backend.worker.api import current_schedule_timezone, initial_next_run_at, withdraw_schedules_by_owner_ref
from backend.worker.due import commit_due_mint, consume_due_tick
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

logger = logging.getLogger(__name__)

CHANNEL_RUN_KIND = "channel_run"
ENQUEUE_TASK_NAME = "backend.channel.schedules.fire_scheduled_channel_run"

__all__ = [
    "ENQUEUE_TASK_NAME",
    "cancel_channel_jobs",
    "owner_ref_for",
    "rename_channel_schedule",
    "schedule_key_for",
    "set_channel_schedule_enabled",
    "sync_published_schedule",
]


def schedule_key_for(channel_id: str) -> str:
    return f"channel_run:{channel_id}"


def owner_ref_for(channel_id: str) -> str:
    return f"channel:{channel_id}"


def sync_published_schedule(channel: ChannelRecord, graph: dict[str, Any]) -> None:
    """Upsert the channel's one schedule row, or withdraw it when the trigger is not Scheduled."""
    node = _scheduled_trigger(graph)
    if node is None:
        withdraw_schedules_by_owner_ref(owner_ref_for(channel.id))
        return
    _upsert(channel, node, graph)


def set_channel_schedule_enabled(channel: ChannelRecord, *, enabled: bool) -> None:
    """Toggle the synced row. Enabling recomputes next_run_at from now and does not catch up."""
    record = get_schedule_store().get_by_key(schedule_key_for(channel.id))
    if record is None:
        return
    now = utc_now()
    nxt = (
        initial_next_run_at(
            cron=record.cron,
            interval_seconds=record.interval_seconds,
            enabled=True,
            after=now,
            schedule_timezone=current_schedule_timezone(),
            start_at=record.start_at,
        )
        if enabled
        else None
    )
    get_schedule_store().upsert(
        replace(record, enabled=enabled, next_run_at=nxt, updated_at=now)
    )


def rename_channel_schedule(channel: ChannelRecord) -> None:
    record = get_schedule_store().get_by_key(schedule_key_for(channel.id))
    if record is None:
        return
    node_name = _published_node_name(channel.id, record.kwargs_json.get("node_id"))
    get_schedule_store().upsert(
        replace(
            record,
            name=_schedule_name(channel.name, node_name or str(record.kwargs_json.get("node_id") or "")),
            updated_at=utc_now(),
        )
    )


def cancel_channel_jobs(channel_id: str) -> list[JobRecord]:
    """Cancel every unfinished channel_run Job for this channel, however it was minted."""
    records, _total = get_job_store().list(kind=CHANNEL_RUN_KIND)
    cancelled: list[JobRecord] = []
    for record in records:
        if record.status in TERMINAL:
            continue
        if (record.input or {}).get("channel_id") != channel_id:
            continue
        was_queued = record.status == "queued"
        updated = mark_cancelled(record.id)
        if updated is not None and updated.status == "cancelled":
            cancelled.append(updated)
            if was_queued:
                revoke_queued_delivery(record.id, settings=get_settings())
    return cancelled


def _upsert(channel: ChannelRecord, node: dict[str, Any], graph: dict[str, Any]) -> ScheduledTaskRecord:
    del graph
    store = get_schedule_store()
    key = schedule_key_for(channel.id)
    existing = store.get_by_key(key)
    cron, interval, start_at = _cadence(node)
    now = utc_now()
    zone = current_schedule_timezone()
    enabled = channel.active
    name = _schedule_name(channel.name, str(node.get("name") or node["id"]))
    schedule_id = existing.id if existing is not None else f"sched_{uuid.uuid4().hex[:12]}"
    cadence_changed = existing is None or not _same_cadence(existing, cron, interval, start_at)
    enabling = enabled and (existing is None or not existing.enabled or cadence_changed)
    if not enabled:
        nxt = None
    elif enabling:
        nxt = initial_next_run_at(
            cron=cron,
            interval_seconds=interval,
            enabled=True,
            after=now,
            schedule_timezone=zone,
            start_at=start_at,
        )
    else:
        nxt = existing.next_run_at if existing is not None else None
    return store.upsert(
        ScheduledTaskRecord(
            id=schedule_id,
            key=key,
            name=name,
            enabled=enabled,
            interval_seconds=interval,
            cron=cron,
            commitment_timezone=zone if cron else (existing.commitment_timezone if existing else zone),
            task_name=ENQUEUE_TASK_NAME,
            args_json=[],
            kwargs_json={
                "schedule_id": schedule_id,
                "channel_id": channel.id,
                "node_id": str(node["id"]),
            },
            hidden=False,
            locked=True,
            undeletable=True,
            store_only=False,
            owner_ref=owner_ref_for(channel.id),
            last_run_at=existing.last_run_at if existing is not None else None,
            next_run_at=nxt,
            running_timeout_sec=None,
            start_at=start_at,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
    )


def _scheduled_trigger(graph: dict[str, Any]) -> dict[str, Any] | None:
    triggers = [
        node
        for node in graph.get("nodes") or []
        if node.get("type") == "trigger.scheduled"
    ]
    if len(triggers) != 1:
        return None
    return triggers[0]


def _cadence(node: dict[str, Any]) -> tuple[str | None, int | None, datetime | None]:
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    cron = config.get("cron")
    cron_text = str(cron).strip() if isinstance(cron, str) and str(cron).strip() else None
    interval = config.get("interval_seconds")
    seconds = interval if isinstance(interval, int) else None
    raw_start = config.get("start_at")
    start = parse_instant(raw_start) if isinstance(raw_start, str) and raw_start.strip() else None
    return cron_text, seconds, start


def _same_cadence(
    record: ScheduledTaskRecord,
    cron: str | None,
    interval: int | None,
    start_at: datetime | None,
) -> bool:
    left = ensure_aware_utc(record.start_at) if record.start_at is not None else None
    right = ensure_aware_utc(start_at) if start_at is not None else None
    return record.cron == cron and record.interval_seconds == interval and left == right


def _schedule_name(channel_name: str, node_name: str) -> str:
    return f"channel_run · {channel_name} · {node_name}"[:128]


def _published_node_name(channel_id: str, node_id: Any) -> str | None:
    if not isinstance(node_id, str):
        return None
    versions, _total = get_channel_store().list_versions(channel_id, limit=1, offset=0)
    if not versions:
        return None
    for node in versions[0].graph.get("nodes") or []:
        if node.get("id") == node_id:
            name = node.get("name")
            return str(name) if isinstance(name, str) else None
    return None


def _resolve_due_at(due_at: str | datetime | None) -> datetime | None:
    if due_at is None:
        return None
    if isinstance(due_at, datetime):
        return ensure_aware_utc(due_at)
    if isinstance(due_at, str) and due_at.strip():
        return parse_instant(due_at)
    return None


@shared_task(name=ENQUEUE_TASK_NAME)
def fire_scheduled_channel_run(
    schedule_id: str | None = None,
    due_at: str | datetime | None = None,
    channel_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, str]:
    """Beat tick: mint one channel_run Job for the delivered commitment."""
    if not schedule_id:
        logger.info("scheduled channel_run skipped: missing_schedule_id")
        return {"status": "skipped", "reason": "missing_schedule_id"}
    due = _resolve_due_at(due_at)
    if due is None:
        return {"status": "missing_due_at"}

    def _decide(session: Any) -> dict[str, Any]:
        outcome = consume_due_tick(schedule_id, due_at=due, session=session)
        if outcome.get("status") != "mint":
            return {"status": str(outcome.get("status"))}
        record = outcome.get("record")
        minted_channel = channel_id
        minted_node = node_id
        if isinstance(record, ScheduledTaskRecord):
            minted_channel = record.kwargs_json.get("channel_id") or minted_channel
            minted_node = record.kwargs_json.get("node_id") or minted_node
        minted = mint_scheduled_run(
            schedule_id=schedule_id,
            channel_id=minted_channel if isinstance(minted_channel, str) else None,
            node_id=minted_node if isinstance(minted_node, str) else None,
            scheduled_for=outcome["scheduled_for"],
            now=outcome["now"],
            session=session,
        )
        job = minted.job
        if job is None or minted.mint_at is None:
            return {"status": minted.status, "job_id": minted.job_id}
        if isinstance(record, ScheduledTaskRecord):
            commit_due_mint(record, now=outcome["now"], session=session, mint_at=minted.mint_at)
        if bool(outcome.get("cancel_immediately")) and job.status not in TERMINAL:
            cancelled = mark_cancelled(job.id, session=session)
            job = cancelled or job
            return {"status": "cancelled", "job_id": job.id, "job": job}
        return {"status": minted.status, "job_id": job.id, "job": job}

    if get_settings().store_backend == "memory":
        minted = _decide(None)
    else:
        with session_scope() as session:
            minted = _decide(session)

    status = minted.get("status")
    job = minted.get("job")
    if status == "cancelled":
        return {"status": "cancelled", "job_id": str(minted.get("job_id") or "")}
    if status == "already_minted":
        if isinstance(job, JobRecord) and job.status == "queued":
            fresh = get_schedule_store().get_by_id(schedule_id)
            if fresh is not None and fresh.enabled:
                dispatch(job.id)
        return {"status": "already_minted", "job_id": str(minted.get("job_id") or "")}
    if status != "queued" or not isinstance(job, JobRecord):
        return {"status": str(status)}
    dispatch(job.id)
    return {"status": "queued", "job_id": job.id}
