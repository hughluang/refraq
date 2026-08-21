"""Structure Job orchestration (engine-agnostic)."""

from __future__ import annotations

import time

from backend.core.config import get_settings
from backend.core.time import utc_now

from backend.jobs.store import append_job_log, mark_succeeded
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
from backend.metadata.source_job_runner import (
    fail_job,
    run_source_work_job,
    stopped_result,
)
from backend.metadata.structure_jobs.collect_log import StructureCollectLog
from backend.metadata.locators import format_column_locator, format_object_locator
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.store import SourceRecord
from backend.metadata.type_mappings.service import assign_normalized_types


def run_structure_job(job_id: str) -> dict[str, str]:
    return run_source_work_job(
        job_id,
        kind="structure",
        start_message="structure job started",
        body=_collect_and_apply_structure,
    )


def _collect_and_apply_structure(
    job_id: str, source: SourceRecord
) -> dict[str, str]:
    source_id = source.id

    stopped = stopped_result(job_id)
    if stopped is not None:
        return stopped

    append_job_log(job_id, level="info", message=f"loaded source {source.key}")

    if not source.engine or not source.access_ciphertext:
        return fail_job(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source has no access configuration",
        )

    try:
        access = decrypt_access_blob(source.access_ciphertext)
    except Exception as exc:  # noqa: BLE001
        return fail_job(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary=f"Access decrypt failed: {exc}",
        )

    try:
        bound = prepare(engine=source.engine, access=access)
    except ConnectorError:
        return fail_job(
            job_id,
            error_code="JOB_CONNECTOR_UNAVAILABLE",
            error_summary=f"No connector for engine {source.engine}",
        )

    stopped = stopped_result(job_id)
    if stopped is not None:
        return stopped

    append_job_log(job_id, level="info", message="collecting structure…")
    try:
        collected = bound.connector.collect_structure(
            bound.endpoint,
            progress=StructureCollectLog(job_id),
        )
    except ConnectorError as exc:
        stopped = stopped_result(job_id)
        if stopped is not None:
            return stopped
        return fail_job(job_id, error_code=exc.code, error_summary=exc.message)

    stopped = stopped_result(job_id)
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
    stopped = stopped_result(job_id)
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
        return fail_job(job_id, error_code=exc.code, error_summary=exc.message)
    except Exception as exc:  # noqa: BLE001
        return fail_job(
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
