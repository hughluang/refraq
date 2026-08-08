"""Catalog browse, semantics, and join HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from fastapi import Request

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.catalog import service as catalog_service
from backend.metadata.catalog.store import get_catalog_store, require_object
from backend.metadata.sources.service import require_source
from backend.metadata.schemas.catalog import (
    CatalogColumnOut,
    CatalogColumnResponse,
    CatalogDdlResponse,
    CatalogObjectListResponse,
    CatalogObjectOut,
    CatalogObjectResponse,
    JoinListResponse,
    JoinOut,
    JoinResponse,
    JoinUpsertRequest,
    SemanticsPatchRequest,
)

router = APIRouter(tags=["catalog"])


def _column_out(record) -> CatalogColumnOut:
    return CatalogColumnOut(
        id=record.id,
        name=record.name,
        data_type=record.data_type,
        nullable=record.nullable,
        business_name=record.business_name,
        business_description=record.business_description,
        ordinal=record.ordinal,
        is_present=record.is_present,
    )


def _object_out(record, *, include_columns: bool) -> CatalogObjectOut:
    columns = []
    if include_columns:
        columns = [_column_out(c) for c in record.columns]
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


def _join_out(record) -> JoinOut:
    return JoinOut(
        id=record.id,
        from_column_id=record.from_column_id,
        to_column_id=record.to_column_id,
        evidence=record.evidence,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
    )


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


@router.patch("/objects/{object_id}/semantics", response_model=CatalogObjectResponse)
def patch_object_semantics(
    object_id: str,
    payload: SemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogObjectResponse:
    data = payload.model_dump(exclude_unset=True)
    record = catalog_service.patch_object_semantics(
        object_id=object_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return CatalogObjectResponse(object=_object_out(record, include_columns=True))


@router.patch("/columns/{column_id}/semantics", response_model=CatalogColumnResponse)
def patch_column_semantics(
    column_id: str,
    payload: SemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogColumnResponse:
    data = payload.model_dump(exclude_unset=True)
    record = catalog_service.patch_column_semantics(
        column_id=column_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return CatalogColumnResponse(column=_column_out(record))


@router.get("/objects/{object_id}/joins", response_model=JoinListResponse)
def list_object_joins(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> JoinListResponse:
    items = [_join_out(j) for j in catalog_service.list_joins(object_id)]
    return JoinListResponse(items=items)


@router.put("/joins", response_model=JoinResponse)
def upsert_join(
    payload: JoinUpsertRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinResponse:
    record = catalog_service.upsert_join(
        from_column_id=payload.from_column_id,
        to_column_id=payload.to_column_id,
        evidence=payload.evidence,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return JoinResponse(join=_join_out(record))


@router.delete("/joins/{join_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_join(
    join_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> Response:
    catalog_service.delete_join(
        join_id=join_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
