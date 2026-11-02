"""Published Job helpers that hold cross-package seam policy.

Mechanism store ports and errors are imported from ``jobs.store`` /
``jobs.errors``. This module owns Celery delivery revoke (so callers never
import ``worker.app``) and Job observation: records in, presented JobOut out.
Scheduled Task name lookup is an injected adapter so ``jobs`` never imports
``worker``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from celery import Celery

from backend.admin.user_store import UserStore
from backend.core.celery_broker import celery_broker_url
from backend.core.config import Settings
from backend.jobs.schemas.jobs import JobOut
from backend.jobs.store import JobRecord

__all__ = [
    "ScheduleNameStore",
    "StampAllowance",
    "bind_schedule_name_store",
    "bind_stamp_allowance",
    "get_schedule_name_store",
    "predicate_for",
    "present_jobs",
    "revoke_queued_delivery",
    "stamp_predicate",
]


class _NamedSchedule(Protocol):
    name: str


class ScheduleNameStore(Protocol):
    def get_by_id(self, schedule_id: str) -> _NamedSchedule | None: ...


_schedule_name_store_getter: Callable[[], ScheduleNameStore] | None = None


def bind_schedule_name_store(getter: Callable[[], ScheduleNameStore]) -> None:
    """Composition binds the Scheduled Task name adapter (typically the store getter)."""
    global _schedule_name_store_getter
    _schedule_name_store_getter = getter


def get_schedule_name_store() -> ScheduleNameStore:
    if _schedule_name_store_getter is None:
        raise RuntimeError("schedule name store is not bound")
    return _schedule_name_store_getter()


class StampAllowance(Protocol):
    all_sources: bool
    source_ids: frozenset[str]


_stamp_allowance: Callable[[str, str], StampAllowance] | None = None


def bind_stamp_allowance(resolver: Callable[[str, str], StampAllowance]) -> None:
    """Composition binds Source Access source_ids_for. Jobs cannot import that module."""
    global _stamp_allowance
    _stamp_allowance = resolver


def predicate_for(allowed: StampAllowance) -> frozenset[str] | None:
    """Finite Source ids, or None when every Source is included.

    An empty set stays empty and is not rewritten to None. Callers must not
    read that empty set as every Source. Job and schedule lists read it as
    null stamps only.
    """
    if allowed.all_sources:
        return None
    return frozenset(allowed.source_ids)


def stamp_predicate(user_id: str, permission: str) -> frozenset[str] | None:
    if _stamp_allowance is None:
        raise RuntimeError("stamp allowance is not bound")
    return predicate_for(_stamp_allowance(user_id, permission))


def present_jobs(
    records: Sequence[JobRecord],
    *,
    users: UserStore,
    schedules: ScheduleNameStore,
) -> list[JobOut]:
    """Map mechanism Job records to the shared HTTP/MCP response shape."""
    actor_names = _actor_names_for_jobs(records, users)
    schedule_names = _schedule_names_for_jobs(records, schedules)
    return [
        _job_out(record, actor_names=actor_names, schedule_names=schedule_names)
        for record in records
    ]


def _actor_names_for_jobs(
    records: Sequence[JobRecord], users: UserStore
) -> dict[str, str]:
    user_ids = {
        record.trigger_ref
        for record in records
        if record.trigger_kind == "user" and record.trigger_ref
    }
    names: dict[str, str] = {}
    for user_id in user_ids:
        user = users.get_by_id(user_id)
        if user is not None:
            names[user_id] = user.display_name
    return names


def _schedule_names_for_jobs(
    records: Sequence[JobRecord], store: ScheduleNameStore
) -> dict[str, str]:
    names: dict[str, str] = {}
    ids = {
        record.trigger_ref
        for record in records
        if record.trigger_kind == "schedule" and record.trigger_ref
    }
    for schedule_id in ids:
        sched = store.get_by_id(schedule_id)
        if sched is None or not sched.name or not sched.name.strip():
            continue
        names[schedule_id] = sched.name.strip()
    return names


def _job_out(
    record: JobRecord,
    *,
    actor_names: Mapping[str, str],
    schedule_names: Mapping[str, str],
) -> JobOut:
    trigger_actor_name: str | None = None
    if record.trigger_kind == "user" and record.trigger_ref:
        trigger_actor_name = actor_names.get(record.trigger_ref)
    trigger_schedule_name: str | None = None
    if record.trigger_kind == "schedule" and record.trigger_ref:
        trigger_schedule_name = schedule_names.get(record.trigger_ref)
    return JobOut(
        id=record.id,
        kind=record.kind,
        status=record.status,
        input=dict(record.input),
        result=record.result,
        summary=record.summary,
        trigger_kind=record.trigger_kind,
        trigger_ref=record.trigger_ref,
        trigger_actor_name=trigger_actor_name,
        trigger_schedule_name=trigger_schedule_name,
        scheduled_for=record.scheduled_for,
        running_timeout_sec=record.running_timeout_sec,
        created_by_user_id=record.created_by,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_code=record.error_code,
        error_message=record.error_summary,
        log_updated_at=record.log_updated_at,
    )


def revoke_queued_delivery(job_id: str, *, settings: Settings) -> None:
    """Best-effort revoke of a queued Celery delivery for a Job id.

    Uses a control-only Celery client. Callers must pass settings (broker
    resolved via ``celery_broker_url``) rather than importing ``worker.app``.
    """
    control_app = Celery("refraq-control")
    control_app.conf.broker_url = celery_broker_url(settings)
    control_app.control.revoke(job_id, terminate=False)
