"""Job status machine and store adapters."""

from __future__ import annotations

from backend.core.time import format_instant, utc_now
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.jobs.models import JobRow


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})

ERROR_WORKER_LOST = "JOB_WORKER_LOST"

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
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

class MemoryJobStore:
    def __init__(self) -> None:
        self._by_id: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: JobRecord) -> JobRecord:
        with self._lock:
            self._by_id[record.id] = record
            return record

    def get(self, job_id: str) -> JobRecord | None:
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

class SqlJobStore:
    def create(self, record: JobRecord) -> JobRecord:
        with session_scope() as session:
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
                created_at=record.created_at,
                started_at=record.started_at,
                finished_at=record.finished_at,
            )
            session.add(row)
            session.flush()
            return _row_to_job(row)

    def get(self, job_id: str) -> JobRecord | None:
        with session_scope() as session:
            row = session.get(JobRow, job_id)
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
) -> JobRecord:
    now = utc_now()
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
        created_at=now,
        started_at=None,
        finished_at=None,
    )
    return get_job_store().create(record)

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

def mark_running(job_id: str, *, celery_task_id: str | None = None) -> JobRecord | None:
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    if record.status != "queued":
        return record
    record.status = "running"
    record.started_at = utc_now()
    if celery_task_id:
        record.celery_task_id = celery_task_id
    return store.save(record)

def mark_failed(
    job_id: str,
    *,
    error_code: str,
    error_summary: str,
) -> JobRecord | None:
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    if record.status in TERMINAL:
        return record
    record.status = "failed"
    record.error_code = error_code
    record.error_summary = error_summary
    record.finished_at = utc_now()
    return store.save(record)

def mark_succeeded(
    job_id: str,
    *,
    result: dict[str, Any] | None = None,
) -> JobRecord | None:
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    if record.status in TERMINAL:
        return record
    record.status = "succeeded"
    record.result = dict(result) if result is not None else None
    record.finished_at = utc_now()
    return store.save(record)

def mark_cancelled(job_id: str) -> JobRecord | None:
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        return None
    if record.status in TERMINAL:
        return record
    record.status = "cancelled"
    record.finished_at = utc_now()
    return store.save(record)

def reap_stuck_running_jobs() -> int:
    """Mark running jobs past timeout as failed. Does not re-enqueue."""
    timeout = get_settings().refraq_job_running_timeout_sec
    cutoff = utc_now() - timedelta(seconds=timeout)
    store = get_job_store()
    reaped = 0
    for record in store.list(status="running"):
        started = record.started_at or record.created_at
        if started > cutoff:
            continue
        mark_failed(
            record.id,
            error_code=ERROR_WORKER_LOST,
            error_summary="Worker lost or job exceeded running timeout",
        )
        reaped += 1
    return reaped
