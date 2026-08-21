"""Execution shell shared by Source work Jobs (structure, join detection).

Counterpart to ``source_jobs``: that module mints Source work Jobs, this one
runs them. Holds the scaffolding every Source work kind repeats — claim, kind
check, Kind execution lock (ADR 0032), Source lookup and usability — so a kind
only supplies the work performed inside the lock.

Cooperative stop checks stay with the kind: each kind decides where its work is
interruptible, so ``stopped_result`` is called from the body rather than woven
in here.
"""

from __future__ import annotations

from collections.abc import Callable

from celery import current_task

from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_queued,
    get_job_store,
    mark_failed,
    occupancy_worker_id,
)
from backend.metadata.catalog.kind_locks import hold_kind_execution_lock
from backend.metadata.sources.store import SourceRecord, get_source_store

JobBody = Callable[[str, SourceRecord], dict[str, str]]


def run_source_work_job(
    job_id: str,
    *,
    kind: str,
    start_message: str,
    body: JobBody,
) -> dict[str, str]:
    """Claim, lock, and resolve the Source, then hand off to ``body``.

    ``body`` runs inside the Kind execution lock with a Source already proven
    to exist and be active. It owns everything kind-specific, including its own
    cooperative stop checks.
    """
    current = claim_queued(
        job_id, celery_task_id=job_id, claimed_by=_claim_worker_id()
    )
    if current is None:
        existing = get_job_store().get(job_id)
        if existing is None:
            return {"status": "missing"}
        return {"status": existing.status}
    if current.kind != kind:
        return fail_job(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"Unsupported job kind: {current.kind}",
        )

    append_job_log(job_id, level="info", message=start_message)

    source_id = current.input.get("source_id")
    if not isinstance(source_id, str):
        return fail_job(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"{kind} job requires source_id",
        )

    with hold_kind_execution_lock(kind, source_id) as lock:
        if lock is None:
            return fail_job(
                job_id,
                error_code="JOB_ALREADY_ACTIVE",
                error_summary=(
                    f"{kind} Kind execution lock held for source {source_id}"
                ),
            )
        source = get_source_store().get_source(source_id)
        if source is None:
            return fail_job(
                job_id,
                error_code="JOB_INPUT_INVALID",
                error_summary="Source not found",
            )
        if source.status != "active":
            return fail_job(
                job_id,
                error_code="JOB_SOURCE_DISABLED",
                error_summary="Source is not usable for jobs",
            )
        return body(job_id, source)


def fail_job(job_id: str, *, error_code: str, error_summary: str) -> dict[str, str]:
    append_job_log(
        job_id,
        level="error",
        message=f"failed: {error_code} — {error_summary}",
    )
    mark_failed(job_id, error_code=error_code, error_summary=error_summary)
    return {"status": "failed", "error_code": error_code}


def stopped_result(job_id: str) -> dict[str, str] | None:
    """Honor cooperative terminal stamps (cancel, timeout, occupancy lost)."""
    record = get_job_store().get(job_id)
    if record is None:
        return {"status": "missing"}
    if record.status in TERMINAL:
        return {"status": record.status}
    return None


def _claim_worker_id() -> str:
    try:
        request = getattr(current_task, "request", None)
        hostname = getattr(request, "hostname", None) if request is not None else None
        return occupancy_worker_id(hostname if hostname else None)
    except Exception:  # noqa: BLE001
        return occupancy_worker_id(None)
