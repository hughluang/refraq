"""Run catalog_embed: rewrite object and column vectors for the current generation."""

from __future__ import annotations

from celery import current_task

from backend.admin.model_services import mark_embedding_ready
from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_queued,
    get_job_store,
    mark_failed,
    mark_succeeded,
    occupancy_worker_id,
)
from backend.metadata.catalog.index_embeddings import (
    EmbeddingRefreshCounts,
    refresh_source_embeddings,
)
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog_embed_jobs.progress_log import CatalogEmbedLog
from backend.metadata.source_job_runner import stopped_result
from backend.metadata.source_job_runner.kind_locks import try_acquire_named_execution_lock
from backend.metadata.sources.store import get_source_store

_SUMMARY_MAX = 400


def _claim_worker_id() -> str:
    try:
        request = getattr(current_task, "request", None)
        hostname = getattr(request, "hostname", None) if request is not None else None
        return occupancy_worker_id(hostname if hostname else None)
    except Exception:  # noqa: BLE001
        return occupancy_worker_id(None)


def _catalog_has_embed_targets() -> bool:
    sources, _ = get_source_store().list_sources(limit=None, offset=0)
    store = get_catalog_store()
    for source in sources:
        _items, total = store.list_objects(
            source.id, include_absent=True, limit=1, offset=0
        )
        if total > 0:
            return True
    return False


def _fail(job_id: str, *, error_code: str, error_summary: str) -> dict[str, str]:
    append_job_log(
        job_id,
        level="error",
        message=f"failed: {error_code} — {error_summary}",
    )
    mark_failed(job_id, error_code=error_code, error_summary=error_summary)
    return {"status": "failed", "error_code": error_code}


def run_catalog_embed_job(job_id: str) -> dict[str, str]:
    current = claim_queued(
        job_id, celery_task_id=job_id, claimed_by=_claim_worker_id()
    )
    if current is None:
        existing = get_job_store().get(job_id)
        if existing is None:
            return {"status": "missing"}
        return {"status": existing.status}
    if current.kind != "catalog_embed":
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"Unsupported job kind: {current.kind}",
        )

    service_id = current.input.get("model_service_id")
    generation = current.input.get("generation")
    if not isinstance(service_id, str) or not isinstance(generation, int):
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="catalog_embed requires model_service_id and generation",
        )

    append_job_log(job_id, level="info", message=f"indexing generation {generation}")

    lock = try_acquire_named_execution_lock("catalog_embed")
    if lock is None:
        return _fail(
            job_id,
            error_code="JOB_ALREADY_ACTIVE",
            error_summary="catalog_embed Kind execution lock is held",
        )
    try:
        stopped = stopped_result(job_id)
        if stopped is not None:
            return stopped
        sources, _ = get_source_store().list_sources(limit=None, offset=0)
        totals = EmbeddingRefreshCounts()
        progress = CatalogEmbedLog(job_id)
        for source in sources:
            stopped = stopped_result(job_id)
            if stopped is not None:
                progress.flush_reason_counts()
                return stopped
            progress.start_source(source.key)
            source_counts = refresh_source_embeddings(
                source.id,
                force=True,
                progress=progress,
                should_stop=lambda: stopped_result(job_id) is not None,
            )
            stopped = stopped_result(job_id)
            if stopped is not None:
                progress.flush_reason_counts()
                return stopped
            progress.finish_source(source_counts)
            totals = totals.plus(source_counts)
        result = {
            "schema": "catalog_embed.v1",
            "objects": totals.objects_written,
            "columns": totals.columns_written,
            "objects_written": totals.objects_written,
            "columns_written": totals.columns_written,
            "objects_failed": totals.objects_failed,
            "columns_failed": totals.columns_failed,
            "objects_skipped": totals.objects_skipped,
            "columns_skipped": totals.columns_skipped,
            "objects_attempted": totals.objects_attempted,
            "columns_attempted": totals.columns_attempted,
            "generation": generation,
            "failure_reasons": progress.failure_reasons(),
        }
        if totals.written == 0 and _catalog_has_embed_targets():
            summary = "catalog_embed wrote no vectors for a non-empty catalog"
            dominant = progress.dominant_reason()
            if dominant:
                summary = f"{summary}: {dominant}"
            if len(summary) > _SUMMARY_MAX:
                summary = summary[:_SUMMARY_MAX] + "…"
            return _fail(
                job_id,
                error_code="JOB_EXECUTION_FAILED",
                error_summary=summary,
            )
        mark_embedding_ready(
            purpose="embedding", service_id=service_id, generation=generation
        )
        mark_succeeded(job_id, result=result)
        indexed = (
            f"indexed {totals.objects_written} objects and "
            f"{totals.columns_written} columns "
            f"(failed {totals.objects_failed}/{totals.columns_failed})"
        )
        dominant = progress.dominant_reason()
        if dominant:
            indexed = (
                f"{indexed}; last error: {dominant} "
                f"(×{progress.dominant_count()})"
            )
        append_job_log(job_id, level="info", message=indexed)
        return {"status": "succeeded"}
    except Exception as exc:  # noqa: BLE001
        summary = str(exc)
        if len(summary) > _SUMMARY_MAX:
            summary = summary[:_SUMMARY_MAX] + "…"
        record = get_job_store().get(job_id)
        if record is not None and record.status not in TERMINAL:
            return _fail(
                job_id,
                error_code="JOB_EXECUTION_FAILED",
                error_summary=summary,
            )
        raise
    finally:
        lock.release()
