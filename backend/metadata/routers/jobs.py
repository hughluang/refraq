"""Source-scoped Job facade and Catalog browse HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.jobs.api import job_out
from backend.jobs.schemas.jobs import JobListResponse
from backend.jobs.store import JobStatus
from backend.metadata.catalog.store import get_catalog_store, require_object
from backend.metadata.source_jobs import enqueue_structure_job, list_jobs_for_source
from backend.metadata.sources.service import require_source
from backend.metadata.schemas.jobs import (
    CatalogColumnOut,
    CatalogDdlResponse,
    CatalogObjectListResponse,
    CatalogObjectOut,
    CatalogObjectResponse,
    EnqueueStructureJobRequest,
)

router = APIRouter(tags=["jobs-catalog"])


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
    payload: EnqueueStructureJobRequest,  # noqa: ARG001 — OpenAPI body; kind fixed by schema
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JSONResponse:
    job = enqueue_structure_job(
        source_id=source_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job": job_out(job).model_dump(mode="json")},
    )


@router.get("/sources/{source_id}/jobs", response_model=JobListResponse)
def list_source_jobs(
    source_id: str,
    kind: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> JobListResponse:
    items = [
        job_out(r)
        for r in list_jobs_for_source(
            source_id, kind=kind, status=status_filter
        )
    ]
    return JobListResponse(items=items)


@router.get("/sources/{source_id}/objects", response_model=CatalogObjectListResponse)
def list_objects(
    source_id: str,
    q: str | None = None,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectListResponse:
    require_source(source_id)
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
