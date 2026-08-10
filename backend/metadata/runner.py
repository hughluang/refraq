"""Structure Job orchestration (engine-agnostic)."""

from __future__ import annotations

from datetime import datetime

from backend.core.config import get_settings
from backend.jobs.store import (
    get_job_store,
    mark_failed,
    mark_running,
    mark_succeeded,
)
from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    apply_structure_snapshot,
    new_column_id,
    new_object_id,
)
from backend.metadata.connectors.base import (
    CollectedStructure,
    ConnectorError,
    endpoint_from_access,
)
from backend.metadata.connectors.registry import get_connector
from backend.metadata.locators import format_column_locator, format_object_locator
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.store import get_source_store


def run_structure_job(job_id: str) -> dict[str, str]:
    store = get_job_store()
    current = mark_running(job_id, celery_task_id=job_id)
    if current is None:
        return {"status": "missing"}
    if current.status != "running":
        return {"status": current.status}
    if current.kind != "structure":
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary=f"Unsupported job kind: {current.kind}",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    source_id = current.input.get("source_id")
    if not isinstance(source_id, str):
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="structure job requires source_id",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    sources = get_source_store()
    source = sources.get_source(source_id)
    if source is None:
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source not found",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    if _cancelled(job_id):
        return {"status": "cancelled"}

    if not source.engine or not source.access_ciphertext:
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source has no access configuration",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    connector = get_connector(source.engine)
    if connector is None:
        mark_failed(
            job_id,
            error_code="JOB_CONNECTOR_UNAVAILABLE",
            error_summary=f"No connector for engine {source.engine}",
        )
        return {"status": "failed", "error_code": "JOB_CONNECTOR_UNAVAILABLE"}

    try:
        access = decrypt_access_blob(source.access_ciphertext)
    except Exception as exc:  # noqa: BLE001
        mark_failed(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary=f"Access decrypt failed: {exc}",
        )
        return {"status": "failed", "error_code": "JOB_SECRET_MISSING"}

    endpoint = endpoint_from_access(
        engine=source.engine,
        access=access,
        database_name=source.database_name or "",
        schema_filter=source.schema_filter,
    )

    if _cancelled(job_id):
        return {"status": "cancelled"}

    try:
        collected = connector.collect_structure(endpoint)
    except ConnectorError as exc:
        if _cancelled(job_id):
            return {"status": "cancelled"}
        mark_failed(job_id, error_code=exc.code, error_summary=exc.message)
        return {"status": "failed", "error_code": exc.code}

    if _cancelled(job_id):
        return {"status": "cancelled"}

    records = _to_catalog_records(
        source_id=source_id,
        source_key=source.key,
        engine=source.engine,
        kind=source.kind,
        job_id=job_id,
        collected=collected,
    )
    settings = get_settings()
    try:
        apply_structure_snapshot(
            source_id=source_id,
            job_id=job_id,
            collected=records,
            schema_scope=source.schema_filter,
            fail_safe_threshold=settings.refraq_catalog_fail_safe_threshold,
            engine=source.engine,
            kind=source.kind,
            source_key=source.key,
        )
    except CatalogWriteAborted as exc:
        mark_failed(job_id, error_code=exc.code, error_summary=exc.message)
        return {"status": "failed", "error_code": exc.code}

    final = mark_succeeded(job_id)
    if final is None:
        return {"status": "missing"}
    return {"status": final.status}


def _cancelled(job_id: str) -> bool:
    record = get_job_store().get(job_id)
    if record is None:
        return True
    return record.status == "cancelled"


def _to_catalog_records(
    *,
    source_id: str,
    source_key: str,
    engine: str | None,
    kind: str,
    job_id: str,
    collected: CollectedStructure,
) -> list[CatalogObjectRecord]:
    now = datetime.utcnow()
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
