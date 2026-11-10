"""Run entity_embed: one full sweep of current serving targets."""

from __future__ import annotations

from celery import current_task

from backend.admin.model_services import get_embedding_runtime
from backend.admin.model_services.errors import (
    ModelServiceClosed,
    ModelServiceControlRevisionMismatch,
    ModelServiceGenerationMismatch,
)
from backend.entity.embed_jobs.index_state import (
    get_entity_index_store,
    note_entity_index_gap,
    publish_entity_index,
)
from backend.entity.errors import EntityNotServing
from backend.entity.kinds import KIND_EMBED
from backend.entity.locks import try_acquire_entity_embed_lock
from backend.entity.projection import (
    delete_entity_projection,
    embed_entity,
    serving_entity_ids,
)
from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_for_execution,
    get_job_store,
    mark_failed,
    mark_succeeded,
    occupancy_worker_id,
)

_SUMMARY_MAX = 400


def _claim_worker_id() -> str:
    try:
        request = getattr(current_task, "request", None)
        hostname = getattr(request, "hostname", None) if request is not None else None
        return occupancy_worker_id(hostname if hostname else None)
    except Exception:  # noqa: BLE001
        return occupancy_worker_id(None)


def _failure_summary(failed: int) -> str:
    if failed == 1:
        return "1 current target failed"
    return f"{failed} current targets failed"


def _result(
    *,
    generation: int | None,
    outcome: str,
    reason: str | None,
    written: int = 0,
    failed: int = 0,
    attempted: int = 0,
) -> dict[str, object]:
    return {
        "schema": "entity_embed.v1",
        "outcome": outcome,
        "reason": reason,
        "written": written,
        "failed": failed,
        "attempted": attempted,
        "generation": generation,
    }


def _fail(job_id: str, *, error_code: str, error_summary: str) -> dict[str, str]:
    append_job_log(
        job_id,
        level="error",
        message=f"failed: {error_code} — {error_summary}",
    )
    mark_failed(job_id, error_code=error_code, error_summary=error_summary)
    return {"status": "failed", "error_code": error_code}


def _skip(
    job_id: str, reason: str, *, generation: int | None = None
) -> dict[str, str]:
    mark_succeeded(
        job_id,
        result=_result(generation=generation, outcome="skipped", reason=reason),
    )
    append_job_log(job_id, level="info", message=f"skipped: {reason}")
    return {"status": "succeeded", "outcome": "skipped", "reason": reason}


def _stopped(job_id: str) -> dict[str, str] | None:
    record = get_job_store().get(job_id)
    if record is None:
        return {"status": "missing"}
    if record.status in TERMINAL:
        return {"status": record.status}
    return None


def run_entity_embed_job(job_id: str) -> dict[str, str]:
    current = claim_for_execution(
        job_id, celery_task_id=job_id, claimed_by=_claim_worker_id()
    )
    if current is None:
        existing = get_job_store().get(job_id)
        if existing is None:
            return {"status": "missing"}
        return {"status": existing.status}
    if current.kind != KIND_EMBED:
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"Unsupported job kind: {current.kind}",
        )

    runtime = get_embedding_runtime()
    if runtime is None or not runtime.url:
        return _skip(job_id, "no_service")
    if runtime.closed:
        return _skip(job_id, "closed", generation=runtime.generation)

    lock = try_acquire_entity_embed_lock()
    if lock is None:
        return _skip(job_id, "already_active", generation=runtime.generation)
    try:
        return _sweep(
            job_id,
            generation=runtime.generation,
            control_revision=runtime.control_revision,
        )
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


def _embed_one(
    entity_id: str, *, generation: int, control_revision: int
) -> str:
    try:
        embed_entity(
            entity_id,
            expected_generation=generation,
            expected_control_revision=control_revision,
        )
    except (
        ModelServiceGenerationMismatch,
        ModelServiceControlRevisionMismatch,
        ModelServiceClosed,
    ):
        return "fence"
    except EntityNotServing:
        if entity_id not in serving_entity_ids():
            return "skipped"
    except Exception:
        pass
    else:
        return "written"
    # Still serving but the write was refused, or the embed call failed.
    delete_entity_projection(entity_id)
    return "failed"


def _fence_skip(job_id: str, *, generation: int) -> dict[str, str]:
    live = get_embedding_runtime()
    if live is not None and live.generation != generation:
        return _skip(job_id, "generation_changed", generation=generation)
    return _skip(job_id, "aborted", generation=generation)


def _sweep(
    job_id: str, *, generation: int, control_revision: int
) -> dict[str, str]:
    before = get_entity_index_store().get()
    already_ready = (
        before.ready and before.generation == generation and not before.rebuild_owed
    )
    append_job_log(job_id, level="info", message=f"indexing generation {generation}")
    stopped = _stopped(job_id)
    if stopped is not None:
        return stopped

    written = 0
    failed = 0
    attempted = 0
    for entity_id in serving_entity_ids():
        stopped = _stopped(job_id)
        if stopped is not None:
            return stopped
        live = get_embedding_runtime()
        if (
            live is None
            or not live.url
            or live.closed
            or live.generation != generation
            or live.control_revision != control_revision
        ):
            return _fence_skip(job_id, generation=generation)
        outcome = _embed_one(
            entity_id, generation=generation, control_revision=control_revision
        )
        if outcome == "fence":
            return _fence_skip(job_id, generation=generation)
        if outcome == "skipped":
            continue
        attempted += 1
        if outcome == "written":
            written += 1
        else:
            failed += 1

    live = get_embedding_runtime()
    if (
        live is None
        or live.closed
        or live.generation != generation
        or live.control_revision != control_revision
    ):
        return _fence_skip(job_id, generation=generation)

    if failed and not already_ready:
        summary = _failure_summary(failed)
        note_entity_index_gap(
            written=written,
            failed=failed,
            attempted=attempted,
            failure_summary=summary,
            keep_ready=False,
        )
        return _fail(job_id, error_code="JOB_EXECUTION_FAILED", error_summary=summary)

    if failed:
        summary = _failure_summary(failed)
        note_entity_index_gap(
            written=written,
            failed=failed,
            attempted=attempted,
            failure_summary=summary,
            keep_ready=True,
        )
        result = _result(
            generation=generation,
            outcome="completed",
            reason=None,
            written=written,
            failed=failed,
            attempted=attempted,
        )
        mark_succeeded(job_id, result=result)
        append_job_log(job_id, level="info", message=summary)
        return {"status": "succeeded"}

    progress = f"indexed {written} entities"
    ready = publish_entity_index(
        generation=generation,
        control_revision=control_revision,
        written=written,
        failed=0,
        attempted=attempted,
        progress=progress,
        failure_summary=None,
    )
    if not ready:
        return _skip(job_id, "aborted", generation=generation)
    result = _result(
        generation=generation,
        outcome="completed",
        reason=None,
        written=written,
        failed=0,
        attempted=attempted,
    )
    mark_succeeded(job_id, result=result)
    append_job_log(job_id, level="info", message=progress)
    return {"status": "succeeded"}
