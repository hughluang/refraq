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
    CatalogObjectRecord,
    CatalogWriteAborted,
    apply_structure_snapshot,
    new_column_id,
    new_object_id,
)
from backend.metadata.connectors.base import (
    CollectedStructure,
    ConnectionEndpoint,
    ConnectorError,
)
from backend.metadata.connectors.registry import get_connector
from backend.metadata.sources.store import (
    decode_secret_payload,
    get_source_store,
)


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
    connection_id = current.input.get("connection_id")
    if not isinstance(source_id, str) or not isinstance(connection_id, str):
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="structure job requires source_id and connection_id",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    sources = get_source_store()
    source = sources.get_source(source_id)
    connection = sources.get_connection(connection_id)
    if source is None or connection is None:
        mark_failed(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source or Connection not found",
        )
        return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}

    if _cancelled(job_id):
        return {"status": "cancelled"}

    if not connection.secret_ciphertext:
        mark_failed(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary="Connection secret is missing",
        )
        return {"status": "failed", "error_code": "JOB_SECRET_MISSING"}

    connector = get_connector(connection.engine)
    if connector is None:
        mark_failed(
            job_id,
            error_code="JOB_CONNECTOR_UNAVAILABLE",
            error_summary=f"No connector for engine {connection.engine}",
        )
        return {"status": "failed", "error_code": "JOB_CONNECTOR_UNAVAILABLE"}

    try:
        secret = decode_secret_payload(connection.secret_ciphertext)
    except Exception as exc:  # noqa: BLE001
        mark_failed(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary=f"Secret decrypt failed: {exc}",
        )
        return {"status": "failed", "error_code": "JOB_SECRET_MISSING"}

    endpoint = ConnectionEndpoint(
        engine=connection.engine,
        host=connection.host,
        port=connection.port,
        username=str(secret.get("username", "")),
        password=str(secret.get("password", "")),
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
        connection_id=connection_id,
        job_id=job_id,
        collected=collected,
    )
    settings = get_settings()
    try:
        apply_structure_snapshot(
            source_id=source_id,
            connection_id=connection_id,
            job_id=job_id,
            collected=records,
            schema_scope=source.schema_filter,
            fail_safe_threshold=settings.refraq_catalog_fail_safe_threshold,
        )
    except CatalogWriteAborted as exc:
        mark_failed(job_id, error_code=exc.code, error_summary=exc.message)
        return {"status": "failed", "error_code": exc.code}

    # Cancel was checked immediately before write; mutation is durable.
    # If a concurrent cancel won the race after commit, mark_succeeded is a
    # no-op on terminal rows — return the store's actual status.
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
    connection_id: str,
    job_id: str,
    collected: CollectedStructure,
) -> list[CatalogObjectRecord]:
    now = datetime.utcnow()
    out: list[CatalogObjectRecord] = []
    for obj in collected.objects:
        object_id = new_object_id()
        columns = [
            CatalogColumnRecord(
                id=new_column_id(),
                object_id=object_id,
                name=col.name,
                ordinal=col.ordinal,
                data_type=col.data_type,
                nullable=col.nullable,
                is_present=True,
                business_name=None,
                business_description=None,
                created_at=now,
                updated_at=now,
            )
            for col in obj.columns
        ]
        out.append(
            CatalogObjectRecord(
                id=object_id,
                source_id=source_id,
                collected_from_connection_id=connection_id,
                object_type=obj.object_type,
                schema_name=obj.schema_name,
                name=obj.name,
                ddl=obj.ddl,
                is_present=True,
                business_name=None,
                business_description=None,
                last_structure_job_id=job_id,
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=columns,
            )
        )
    return out
