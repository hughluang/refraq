"""Structure Job orchestration (engine-agnostic)."""

from __future__ import annotations

import time

from celery import current_task

from backend.core.config import get_settings
from backend.core.time import utc_now

from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_queued,
    get_job_store,
    mark_failed,
    mark_succeeded,
    occupancy_worker_id,
)
from backend.metadata.catalog.kind_locks import hold_kind_execution_lock
from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    new_column_id,
    new_object_id,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
from backend.metadata.connectors.base import CollectedStructure, ConnectorError
from backend.metadata.connectors.runtime import prepare
from backend.metadata.structure_jobs.collect_log import StructureCollectLog
from backend.metadata.locators import format_column_locator, format_object_locator
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.store import get_source_store
from backend.metadata.type_mappings.service import assign_normalized_types


def _claim_worker_id() -> str:
    try:
        request = getattr(current_task, "request", None)
        hostname = getattr(request, "hostname", None) if request is not None else None
        return occupancy_worker_id(hostname if hostname else None)
    except Exception:  # noqa: BLE001
        return occupancy_worker_id(None)


def run_structure_job(job_id: str) -> dict[str, str]:
    current = claim_queued(
        job_id, celery_task_id=job_id, claimed_by=_claim_worker_id()
    )
    if current is None:
        existing = get_job_store().get(job_id)
        if existing is None:
            return {"status": "missing"}
        return {"status": existing.status}
    if current.kind != "structure":
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"Unsupported job kind: {current.kind}",
        )

    append_job_log(job_id, level="info", message="structure job started")

    source_id = current.input.get("source_id")
    if not isinstance(source_id, str):
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="structure job requires source_id",
        )

    with hold_kind_execution_lock("structure", source_id) as lock:
        if lock is None:
            return _fail(
                job_id,
                error_code="JOB_ALREADY_ACTIVE",
                error_summary=(
                    f"structure Kind execution lock held for source {source_id}"
                ),
            )
        return _run_structure_job_locked(job_id, source_id=source_id)


def _run_structure_job_locked(job_id: str, *, source_id: str) -> dict[str, str]:
    source = get_source_store().get_source(source_id)
    if source is None:
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source not found",
        )

    if source.status != "active":
        return _fail(
            job_id,
            error_code="JOB_SOURCE_DISABLED",
            error_summary="Source is not usable for jobs",
        )

    stopped = _stopped(job_id)
    if stopped is not None:
        return stopped

    append_job_log(job_id, level="info", message=f"loaded source {source.key}")

    if not source.engine or not source.access_ciphertext:
        return _fail(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source has no access configuration",
        )

    try:
        access = decrypt_access_blob(source.access_ciphertext)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary=f"Access decrypt failed: {exc}",
        )

    try:
        bound = prepare(engine=source.engine, access=access)
    except ConnectorError:
        return _fail(
            job_id,
            error_code="JOB_CONNECTOR_UNAVAILABLE",
            error_summary=f"No connector for engine {source.engine}",
        )

    stopped = _stopped(job_id)
    if stopped is not None:
        return stopped

    append_job_log(job_id, level="info", message="collecting structure…")
    try:
        collected = bound.connector.collect_structure(
            bound.endpoint,
            progress=StructureCollectLog(job_id),
        )
    except ConnectorError as exc:
        stopped = _stopped(job_id)
        if stopped is not None:
            return stopped
        return _fail(job_id, error_code=exc.code, error_summary=exc.message)

    stopped = _stopped(job_id)
    if stopped is not None:
        return stopped

    col_count = sum(len(obj.columns) for obj in collected.objects)
    append_job_log(
        job_id,
        level="info",
        message=f"collected {len(collected.objects)} objects, {col_count} columns",
    )

    records = _to_catalog_records(
        source_id=source_id,
        source_key=source.key,
        engine=source.engine,
        kind=source.kind,
        job_id=job_id,
        collected=collected,
    )
    t_phase = time.perf_counter()
    records = assign_normalized_types(records, engine=source.engine)
    append_job_log(
        job_id,
        level="info",
        message=f"assigned normalized types in {time.perf_counter() - t_phase:.1f}s",
    )
    unknown_locators = [
        col.locator_key
        for obj in records
        for col in obj.columns
        if col.normalized_type == "unknown"
    ]
    stopped = _stopped(job_id)
    if stopped is not None:
        return stopped
    append_job_log(job_id, level="info", message="applying catalog snapshot…")
    t_phase = time.perf_counter()
    try:
        commit = apply_structure_snapshot(
            source=source,
            job_id=job_id,
            collected=records,
            schema_scope=bound.endpoint.schema_filter,
            fail_safe_threshold=get_settings().refraq_catalog_fail_safe_threshold,
        )
    except CatalogWriteAborted as exc:
        return _fail(job_id, error_code=exc.code, error_summary=exc.message)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            job_id,
            error_code="JOB_EXECUTION_FAILED",
            error_summary=str(exc)[:400],
        )
    append_job_log(
        job_id,
        level="info",
        message=(
            f"succeeded class={commit.facts.diff_class} "
            f"in {time.perf_counter() - t_phase:.1f}s"
        ),
    )
    if unknown_locators:
        sample = ", ".join(unknown_locators[:10])
        ellipsis = ", …" if len(unknown_locators) > 10 else ""
        append_job_log(
            job_id,
            level="warn",
            message=(
                f"{len(unknown_locators)} columns mapped to unknown "
                f"({sample}{ellipsis})"
            ),
        )
    final = mark_succeeded(job_id, result=commit.result_envelope())
    if final is None:
        return {"status": "missing"}
    return {"status": final.status}


def _fail(job_id: str, *, error_code: str, error_summary: str) -> dict[str, str]:
    append_job_log(
        job_id,
        level="error",
        message=f"failed: {error_code} — {error_summary}",
    )
    mark_failed(job_id, error_code=error_code, error_summary=error_summary)
    return {"status": "failed", "error_code": error_code}


def _stopped(job_id: str) -> dict[str, str] | None:
    """Honor cooperative terminal stamps (cancel, timeout, occupancy lost)."""
    record = get_job_store().get(job_id)
    if record is None:
        return {"status": "missing"}
    if record.status in TERMINAL:
        return {"status": record.status}
    return None


def _to_catalog_records(
    *,
    source_id: str,
    source_key: str,
    engine: str | None,
    kind: str,
    job_id: str,
    collected: CollectedStructure,
) -> list[CatalogObjectRecord]:
    now = utc_now()
    out: list[CatalogObjectRecord] = []
    for obj in collected.objects:
        object_id = new_object_id()
        obj_locator = format_object_locator(
            engine=engine,
            kind=kind,
            source_key=source_key,
            schema_name=obj.schema_name,
            object_type=obj.object_type,
            name=obj.name,
        )
        columns = [
            CatalogColumnRecord(
                id=new_column_id(),
                object_id=object_id,
                locator_key=format_column_locator(
                    engine=engine,
                    kind=kind,
                    source_key=source_key,
                    schema_name=obj.schema_name,
                    object_type=obj.object_type,
                    name=obj.name,
                    column_name=col.name,
                ),
                name=col.name,
                ordinal=col.ordinal,
                data_type=col.data_type,
                nullable=col.nullable,
                is_present=True,
                default_value=col.default_value,
                comment=col.comment,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
            for col in obj.columns
        ]
        foreign_keys = [
            CatalogForeignKeyRecord(
                name=fk.name,
                columns=list(fk.columns),
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=list(fk.ref_columns),
            )
            for fk in obj.foreign_keys
        ]
        indexes = [
            CatalogIndexRecord(
                name=idx.name,
                columns=list(idx.columns),
                is_unique=idx.is_unique,
            )
            for idx in obj.indexes
        ]
        out.append(
            CatalogObjectRecord(
                id=object_id,
                source_id=source_id,
                locator_key=obj_locator,
                object_type=obj.object_type,
                schema_name=obj.schema_name,
                name=obj.name,
                ddl=obj.ddl,
                comment=obj.comment,
                primary_key=list(obj.primary_key) if obj.primary_key else None,
                is_present=True,
                business_name=None,
                business_description=None,
                object_category=None,
                grain_description=None,
                business_primary_key=None,
                business_domain_id=None,
                evidence_summary=None,
                open_questions=None,
                semantic_source=None,
                business_semantics_ready=False,
                semantics_updated_at=None,
                last_structure_job_id=job_id,
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=columns,
                foreign_keys=foreign_keys,
                indexes=indexes,
            )
        )
    return out
