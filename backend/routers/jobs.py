"""Job and Catalog browse HTTP routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.jobs.store import (
    JobRecord,
    JobStatus,
    TERMINAL,
    create_queued_job,
    get_job_store,
    mark_cancelled,
)
from backend.metadata.catalog.store import get_catalog_store, require_object
from backend.metadata.enqueue import enqueue_job
from backend.metadata.errors import (
    CatalogObjectNotFound,
    JobAlreadyActive,
    JobConnectionDisabled,
    JobConnectionMismatch,
    JobInputInvalid,
    JobNotCancellable,
    JobNotFound,
    JobSecretMissing,
    JobSourceDisabled,
    SourceNotFound,
)
from backend.metadata.sources.store import get_source_store
from backend.repositories.user_store import UserRecord
from backend.schemas.jobs import (
    CatalogColumnOut,
    CatalogDdlResponse,
    CatalogObjectListResponse,
    CatalogObjectOut,
    CatalogObjectResponse,
    EnqueueStructureJobRequest,
    JobListResponse,
    JobOut,
    JobResponse,
)
from backend.worker.app import celery_app

router = APIRouter(tags=["jobs-catalog"])


def _job_out(record: JobRecord) -> JobOut:
    return JobOut(
        id=record.id,
        kind=record.kind,
        status=record.status,
        input=dict(record.input),
        created_by_user_id=record.created_by,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_code=record.error_code,
        error_message=record.error_summary,
    )


def _object_out(record, *, include_columns: bool) -> CatalogObjectOut:
    columns = []
    if include_columns:
        columns = [
            CatalogColumnOut(
                id=c.id,
                name=c.name,
                data_type=c.data_type,
                nullable=c.nullable,
                business_name=c.business_name,
                business_description=c.business_description,
                ordinal=c.ordinal,
                is_present=c.is_present,
            )
            for c in record.columns
        ]
    return CatalogObjectOut(
        id=record.id,
        source_id=record.source_id,
        collected_from_connection_id=record.collected_from_connection_id,
        object_type=record.object_type,
        schema_name=record.schema_name,
        name=record.name,
        business_name=record.business_name,
        business_description=record.business_description,
        columns=columns if include_columns else [],
        ddl=record.ddl if include_columns else None,
        is_present=record.is_present,
        collected_at=record.collected_at,
    )


@router.post("/sources/{source_id}/jobs", status_code=status.HTTP_202_ACCEPTED)
def enqueue_source_job(
    source_id: str,
    payload: EnqueueStructureJobRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JSONResponse:
    if payload.kind != "structure":
        raise JobInputInvalid("Only kind=structure is supported in slice A")
    sources = get_source_store()
    source = sources.get_source(source_id)
    if source is None:
        raise SourceNotFound()
    if source.status != "active":
        raise JobSourceDisabled()
    if source.kind != "database":
        raise JobInputInvalid("structure jobs require a database Source")

    connection = sources.get_connection_for_source(source_id)
    if connection is None:
        raise JobInputInvalid("Source has no Connection")
    if payload.connection_id and payload.connection_id != connection.id:
        raise JobConnectionMismatch()
    if connection.status != "active":
        raise JobConnectionDisabled()
    if not connection.has_secret:
        raise JobSecretMissing()

    if get_job_store().has_active_structure_job(source_id):
        raise JobAlreadyActive()

    job = create_queued_job(
        kind="structure",
        input={"source_id": source_id, "connection_id": connection.id},
        created_by=user.id,
    )
    enqueue_job(job)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="job",
        resource_id=job.id,
        action="job.enqueue",
        result="success",
        detail={"kind": "structure", "source_id": source_id},
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job": _job_out(get_job_store().get(job.id) or job).model_dump(mode="json")},
    )


@router.get("/sources/{source_id}/jobs", response_model=JobListResponse)
def list_source_jobs(
    source_id: str,
    kind: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> JobListResponse:
    if get_source_store().get_source(source_id) is None:
        raise SourceNotFound()
    items = [
        _job_out(r)
        for r in get_job_store().list_for_source(
            source_id, kind=kind, status=status_filter
        )
    ]
    return JobListResponse(items=items)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    return JobResponse(job=_job_out(record))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    if record.status in TERMINAL:
        raise JobNotCancellable()
    was_queued = record.status == "queued"
    updated = mark_cancelled(job_id)
    assert updated is not None
    if was_queued:
        celery_app.control.revoke(job_id, terminate=False)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="job",
        resource_id=job_id,
        action="job.cancel",
        result="success",
        detail={},
    )
    return JobResponse(job=_job_out(updated))


@router.get("/sources/{source_id}/objects", response_model=CatalogObjectListResponse)
def list_objects(
    source_id: str,
    q: str | None = None,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectListResponse:
    if get_source_store().get_source(source_id) is None:
        raise SourceNotFound()
    items = [
        _object_out(o, include_columns=False)
        for o in get_catalog_store().list_objects(source_id, name_search=q)
    ]
    return CatalogObjectListResponse(items=items)


@router.get("/objects/{object_id}", response_model=CatalogObjectResponse)
def get_object(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectResponse:
    record = require_object(object_id)
    return CatalogObjectResponse(object=_object_out(record, include_columns=True))


@router.get("/objects/{object_id}/ddl", response_model=CatalogDdlResponse)
def get_object_ddl(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogDdlResponse:
    record = require_object(object_id)
    return CatalogDdlResponse(id=record.id, ddl=record.ddl)
