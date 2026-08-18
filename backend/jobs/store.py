"""Job status machine and store adapters."""

from __future__ import annotations

from backend.core.time import format_instant, utc_now
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Literal, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.jobs.models import JobRow
from backend.jobs.parameters import reaper_lost_detection_sec


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})

ERROR_WORKER_LOST = "JOB_WORKER_LOST"
ERROR_RUNNING_TIMEOUT = "JOB_RUNNING_TIMEOUT"
UNKNOWN_WORKER_ID = "celery@unknown"

_UNFINISHED: tuple[str, ...] = ("queued", "running")
_RUNNING_ONLY: tuple[str, ...] = ("running",)


@dataclass
class JobRecord:
    id: str
    kind: str
    status: JobStatus
    input: dict[str, Any]
    result: dict[str, Any] | None
    created_by: str | None
    celery_task_id: str | None
    error_code: str | None
    error_summary: str | None
    summary: str
    trigger_kind: str | None
    trigger_ref: str | None
    log_body: str
    log_updated_at: datetime | None
    scheduled_for: datetime | None
    claimed_by: str | None
    locked_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    running_timeout_sec: int | None = None


class UniqueScheduledForError(Exception):
    def __init__(self, existing_job_id: str) -> None:
        self.existing_job_id = existing_job_id
        super().__init__(existing_job_id)


def _is_unique_violation(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    return orig is not None and getattr(orig, "pgcode", None) == "23505"


class MemoryJobStore:
    def __init__(self) -> None:
        self._by_id: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(
        self, record: JobRecord, *, session: Session | None = None
    ) -> JobRecord:
        del session
        with self._lock:
            if record.scheduled_for is not None and record.trigger_kind == "schedule":
                for existing in self._by_id.values():
                    if (
                        existing.trigger_kind == "schedule"
                        and existing.trigger_ref == record.trigger_ref
                        and existing.scheduled_for == record.scheduled_for
                    ):
                        raise UniqueScheduledForError(existing.id)
            self._by_id[record.id] = record
            return record

    def get(
        self, job_id: str, *, session: Session | None = None
    ) -> JobRecord | None:
        del session
        with self._lock:
            return self._by_id.get(job_id)

    def save(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._by_id[record.id] = record
            return record

    def list(
        self,
        *,
        kind: str | None = None,
        status: JobStatus | None = None,
    ) -> list[JobRecord]:
        with self._lock:
            items = list(self._by_id.values())
            if kind is not None:
                items = [r for r in items if r.kind == kind]
            if status is not None:
                items = [r for r in items if r.status == status]
            return sorted(items, key=lambda r: r.created_at, reverse=True)

    def claim_queued(
        self,
        job_id: str,
        *,
        celery_task_id: str | None = None,
        claimed_by: str | None = None,
    ) -> JobRecord | None:
        """CAS queued→running. Returns the running record only when this caller claimed it."""
        with self._lock:
            record = self._by_id.get(job_id)
            if record is None or record.status != "queued":
                return None
            now = utc_now()
            record.status = "running"
            record.started_at = now
            record.locked_at = now
            if celery_task_id:
                record.celery_task_id = celery_task_id
            if claimed_by:
                record.claimed_by = claimed_by
            self._by_id[job_id] = record
            return record

    def touch_occupancy(self, claimed_by: str) -> int:
        now = utc_now()
        with self._lock:
            touched = 0
            for record in self._by_id.values():
                if record.status == "running" and record.claimed_by == claimed_by:
                    record.locked_at = now
                    touched += 1
            return touched

    def set_celery_task_id(
        self, job_id: str, celery_task_id: str
    ) -> JobRecord | None:
        with self._lock:
            record = self._by_id.get(job_id)
            if record is None:
                return None
            record.celery_task_id = celery_task_id
            return record

    def cas_terminal(
        self,
        job_id: str,
        *,
        to_status: JobStatus,
        from_statuses: Sequence[str],
        error_code: str | None = None,
        error_summary: str | None = None,
        result: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> JobRecord | None:
        """Atomically terminalize if status is in from_statuses. 0 rows → return current."""
        del session
        with self._lock:
            record = self._by_id.get(job_id)
            if record is None:
                return None
            if record.status not in from_statuses:
                return record
            record.status = to_status
            record.finished_at = utc_now()
            if to_status == "failed":
                record.error_code = error_code
                record.error_summary = error_summary
            if to_status == "succeeded":
                record.result = dict(result) if result is not None else None
            self._by_id[job_id] = record
            return record


class SqlJobStore:
    def create(
        self, record: JobRecord, *, session: Session | None = None
    ) -> JobRecord:
        if session is not None:
            return self._create_on(session, record)
        with session_scope() as owned:
            return self._create_on(owned, record)

    def _create_on(self, session: Session, record: JobRecord) -> JobRecord:
        row = JobRow(
            id=record.id,
            kind=record.kind,
            status=record.status,
            input=dict(record.input),
            result=dict(record.result) if record.result is not None else None,
            created_by=record.created_by,
            celery_task_id=record.celery_task_id,
            error_code=record.error_code,
            error_summary=record.error_summary,
            summary=record.summary,
            trigger_kind=record.trigger_kind,
            trigger_ref=record.trigger_ref,
            log_body=record.log_body,
            log_updated_at=record.log_updated_at,
            scheduled_for=record.scheduled_for,
            running_timeout_sec=record.running_timeout_sec,
            claimed_by=record.claimed_by,
            locked_at=record.locked_at,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except Exception as exc:
            if _is_unique_violation(exc):
                existing_id = ""
                if (
                    record.trigger_kind == "schedule"
                    and record.trigger_ref
                    and record.scheduled_for is not None
                ):
                    found = session.scalar(
                        select(JobRow.id).where(
                            JobRow.trigger_kind == "schedule",
                            JobRow.trigger_ref == record.trigger_ref,
                            JobRow.scheduled_for == record.scheduled_for,
                        )
                    )
                    existing_id = found or ""
                raise UniqueScheduledForError(existing_id) from exc
            raise
        return _row_to_job(row)

    def get(
        self, job_id: str, *, session: Session | None = None
    ) -> JobRecord | None:
        if session is not None:
            row = session.get(JobRow, job_id)
            return _row_to_job(row) if row else None
        with session_scope() as owned:
            row = owned.get(JobRow, job_id)
            return _row_to_job(row) if row else None

    def save(self, record: JobRecord) -> JobRecord:
        with session_scope() as session:
            row = session.get(JobRow, record.id)
            if row is None:
                raise KeyError(record.id)
            row.status = record.status
            row.input = dict(record.input)
            row.result = dict(record.result) if record.result is not None else None
            row.celery_task_id = record.celery_task_id
            row.error_code = record.error_code
            row.error_summary = record.error_summary
            row.summary = record.summary
            row.trigger_kind = record.trigger_kind
            row.trigger_ref = record.trigger_ref
            row.log_body = record.log_body
            row.log_updated_at = record.log_updated_at
            row.scheduled_for = record.scheduled_for
            row.running_timeout_sec = record.running_timeout_sec
            row.claimed_by = record.claimed_by
            row.locked_at = record.locked_at
            row.started_at = record.started_at
            row.finished_at = record.finished_at
            session.flush()
            return _row_to_job(row)

    def list(
        self,
        *,
        kind: str | None = None,
        status: JobStatus | None = None,
    ) -> list[JobRecord]:
        with session_scope() as session:
            stmt = select(JobRow)
            if kind is not None:
                stmt = stmt.where(JobRow.kind == kind)
            if status is not None:
                stmt = stmt.where(JobRow.status == status)
            stmt = stmt.order_by(JobRow.created_at.desc())
            rows = session.scalars(stmt).all()
            return [_row_to_job(row) for row in rows]

    def claim_queued(
        self,
        job_id: str,
        *,
        celery_task_id: str | None = None,
        claimed_by: str | None = None,
    ) -> JobRecord | None:
        """CAS queued→running. Returns the running record only when this caller claimed it."""
        with session_scope() as session:
            now = utc_now()
            values: dict[str, Any] = {
                "status": "running",
                "started_at": now,
                "locked_at": now,
            }
            if celery_task_id:
                values["celery_task_id"] = celery_task_id
            if claimed_by:
                values["claimed_by"] = claimed_by
            result = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == "queued")
                .values(**values)
            )
            session.flush()
            if result.rowcount == 0:  # type: ignore[attr-defined]
                return None
            row = session.get(JobRow, job_id)
            return _row_to_job(row) if row else None

    def touch_occupancy(self, claimed_by: str) -> int:
        with session_scope() as session:
            now = utc_now()
            result = session.execute(
                update(JobRow)
                .where(JobRow.status == "running", JobRow.claimed_by == claimed_by)
                .values(locked_at=now)
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    def set_celery_task_id(
        self, job_id: str, celery_task_id: str
    ) -> JobRecord | None:
        with session_scope() as session:
            result = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(celery_task_id=celery_task_id)
            )
            session.flush()
            if result.rowcount == 0:  # type: ignore[attr-defined]
                return None
            row = session.get(JobRow, job_id)
            return _row_to_job(row) if row else None

    def cas_terminal(
        self,
        job_id: str,
        *,
        to_status: JobStatus,
        from_statuses: Sequence[str],
        error_code: str | None = None,
        error_summary: str | None = None,
        result: dict[str, Any] | None = None,
        session: Session | None = None,
    ) -> JobRecord | None:
        if session is not None:
            return self._cas_terminal_on(
                session,
                job_id,
                to_status=to_status,
                from_statuses=from_statuses,
                error_code=error_code,
                error_summary=error_summary,
                result=result,
            )
        with session_scope() as owned:
            return self._cas_terminal_on(
                owned,
                job_id,
                to_status=to_status,
                from_statuses=from_statuses,
                error_code=error_code,
                error_summary=error_summary,
                result=result,
            )

    def _cas_terminal_on(
        self,
        session: Session,
        job_id: str,
        *,
        to_status: JobStatus,
        from_statuses: Sequence[str],
        error_code: str | None,
        error_summary: str | None,
        result: dict[str, Any] | None,
    ) -> JobRecord | None:
        now = utc_now()
        values: dict[str, Any] = {
            "status": to_status,
            "finished_at": now,
        }
        if to_status == "failed":
            values["error_code"] = error_code
            values["error_summary"] = error_summary
        if to_status == "succeeded":
            values["result"] = dict(result) if result is not None else None
        session.execute(
            update(JobRow)
            .where(JobRow.id == job_id, JobRow.status.in_(list(from_statuses)))
            .values(**values)
        )
        session.flush()
        row = session.get(JobRow, job_id)
        return _row_to_job(row) if row else None


def _row_to_job(row: object) -> JobRecord:
    assert isinstance(row, JobRow)
    return JobRecord(
        id=row.id,
        kind=row.kind,
        status=row.status,  # type: ignore[arg-type]
        input=dict(row.input),
        result=dict(row.result) if row.result is not None else None,
        created_by=row.created_by,
        celery_task_id=row.celery_task_id,
        error_code=row.error_code,
        error_summary=row.error_summary,
        summary=row.summary or "",
        trigger_kind=row.trigger_kind,
        trigger_ref=row.trigger_ref,
        log_body=row.log_body or "",
        log_updated_at=row.log_updated_at,
        scheduled_for=getattr(row, "scheduled_for", None),
        running_timeout_sec=getattr(row, "running_timeout_sec", None),
        claimed_by=getattr(row, "claimed_by", None),
        locked_at=getattr(row, "locked_at", None),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


_memory_singleton: MemoryJobStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_job_store() -> MemoryJobStore | SqlJobStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryJobStore()
            return _memory_singleton
    return SqlJobStore()


def reset_job_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_job_store.cache_clear()


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


def format_job_log_line(*, level: str, message: str, at: datetime | None = None) -> str:
    ts = format_instant(at or utc_now())
    return f"{ts} {level.upper()} {message}"


def create_queued_job(
    *,
    kind: str,
    input: dict[str, Any],
    created_by: str | None = None,
    summary: str = "",
    trigger_kind: str | None = None,
    trigger_ref: str | None = None,
    log_body: str = "",
    scheduled_for: datetime | None = None,
    running_timeout_sec: int | None = None,
    session: Session | None = None,
    created_at: datetime | None = None,
) -> JobRecord:
    now = created_at or utc_now()
    record = JobRecord(
        id=new_job_id(),
        kind=kind,
        status="queued",
        input=dict(input),
        result=None,
        created_by=created_by,
        celery_task_id=None,
        error_code=None,
        error_summary=None,
        summary=summary,
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        log_body=log_body,
        log_updated_at=now if log_body else None,
        scheduled_for=scheduled_for,
        running_timeout_sec=running_timeout_sec,
        claimed_by=None,
        locked_at=None,
        created_at=now,
        started_at=None,
        finished_at=None,
    )
    return get_job_store().create(record, session=session)


def append_job_log(
    job_id: str,
    *,
    level: str,
    message: str,
) -> JobRecord | None:
    """Append one line to Job.log_body. Returns None if Job missing."""
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    now = utc_now()
    line = format_job_log_line(level=level, message=message, at=now)
    record.log_body = f"{record.log_body}\n{line}" if record.log_body else line
    record.log_updated_at = now
    return store.save(record)


def occupancy_worker_id(hostname: str | None) -> str:
    """Non-empty worker identity shared by claim and occupancy renew."""
    text = str(hostname).strip() if hostname else ""
    return text or UNKNOWN_WORKER_ID


def claim_queued(
    job_id: str,
    *,
    celery_task_id: str | None = None,
    claimed_by: str | None = None,
) -> JobRecord | None:
    """CAS queued → running. Returns the running record only when this caller claimed it."""
    return get_job_store().claim_queued(
        job_id, celery_task_id=celery_task_id, claimed_by=claimed_by
    )


def set_celery_task_id(job_id: str, celery_task_id: str) -> JobRecord | None:
    """Patch only celery_task_id; does not rewrite status / claim fields."""
    return get_job_store().set_celery_task_id(job_id, celery_task_id)


def mark_failed(
    job_id: str,
    *,
    error_code: str,
    error_summary: str,
    from_statuses: Sequence[str] = _UNFINISHED,
    session: Session | None = None,
) -> JobRecord | None:
    """CAS to failed. Default from queued|running; reaper passes running-only."""
    return get_job_store().cas_terminal(
        job_id,
        to_status="failed",
        from_statuses=from_statuses,
        error_code=error_code,
        error_summary=error_summary,
        session=session,
    )


def mark_succeeded(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
    session: Session | None = None,
) -> JobRecord | None:
    """CAS running → succeeded. 0 rows returns current row (already terminal)."""
    return get_job_store().cas_terminal(
        job_id,
        to_status="succeeded",
        from_statuses=_RUNNING_ONLY,
        result=result,
        session=session,
    )


def mark_cancelled(
    job_id: str, *, session: Session | None = None
) -> JobRecord | None:
    """CAS queued|running → cancelled. 0 rows returns current (already terminal)."""
    return get_job_store().cas_terminal(
        job_id,
        to_status="cancelled",
        from_statuses=_UNFINISHED,
        session=session,
    )


def cancel_unfinished_for_schedule(schedule_id: str) -> list[JobRecord]:
    """Immediately cancel queued/running Jobs minted by this schedule."""
    store = get_job_store()
    cancelled: list[JobRecord] = []
    for record in store.list():
        if record.trigger_kind != "schedule" or record.trigger_ref != schedule_id:
            continue
        if record.status in TERMINAL:
            continue
        updated = mark_cancelled(record.id)
        if updated is not None and updated.status == "cancelled":
            cancelled.append(updated)
    return cancelled


def touch_occupancy(claimed_by: str) -> int:
    """Renew locked_at for all running Jobs claimed by this worker."""
    return get_job_store().touch_occupancy(claimed_by)


def _fail_worker_lost(
    records: Sequence[JobRecord],
    *,
    error_summary: str,
) -> int:
    """CAS running → failed JOB_WORKER_LOST for the given records."""
    reaped = 0
    for record in records:
        updated = mark_failed(
            record.id,
            error_code=ERROR_WORKER_LOST,
            error_summary=error_summary,
            from_statuses=_RUNNING_ONLY,
        )
        if (
            updated is not None
            and updated.status == "failed"
            and updated.error_code == ERROR_WORKER_LOST
        ):
            reaped += 1
    return reaped


def fail_leftover_occupancy(claimed_by: str) -> int:
    """Mark all running Jobs claimed by this worker as JOB_WORKER_LOST.

    Startup path: previous generation under the same identity is gone.
    No TTL filter — freshness must not keep a zombie alive for renew.
    """
    leftovers = [
        record
        for record in get_job_store().list(status="running")
        if record.claimed_by == claimed_by
    ]
    return _fail_worker_lost(
        leftovers,
        error_summary="Worker lost: previous generation left running occupancy",
    )


def reap_stale_occupancy() -> int:
    """Mark running Jobs with stale occupancy as JOB_WORKER_LOST (Beat observer)."""
    lost_sec = reaper_lost_detection_sec()
    cutoff = utc_now() - timedelta(seconds=lost_sec)
    stale = [
        record
        for record in get_job_store().list(status="running")
        if (record.locked_at or record.started_at or record.created_at) <= cutoff
    ]
    return _fail_worker_lost(
        stale,
        error_summary="Worker lost: occupancy declaration stale",
    )


def reap_running_timeouts() -> int:
    """Mark running Jobs past their minted Running Time Limit as JOB_RUNNING_TIMEOUT."""
    now = utc_now()
    store = get_job_store()
    reaped = 0
    for record in store.list(status="running"):
        timeout = record.running_timeout_sec
        if timeout is None:
            continue
        started = record.started_at or record.created_at
        if started > now - timedelta(seconds=timeout):
            continue
        updated = mark_failed(
            record.id,
            error_code=ERROR_RUNNING_TIMEOUT,
            error_summary="Job exceeded running time limit",
            from_statuses=_RUNNING_ONLY,
        )
        if (
            updated is not None
            and updated.status == "failed"
            and updated.error_code == ERROR_RUNNING_TIMEOUT
        ):
            reaped += 1
    return reaped


def reap_stuck_running_jobs() -> int:
    """System reaper: occupancy lost then running timeout. Does not re-enqueue."""
    return reap_stale_occupancy() + reap_running_timeouts()
