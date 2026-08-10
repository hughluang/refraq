"""Catalog browse, semantics, and join HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi import Request

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.catalog import service as catalog_service
from backend.metadata.schemas.catalog import (
    CatalogColumnOut,
    CatalogColumnResponse,
    CatalogColumnSearchResponse,
    CatalogColumnsSemanticsBatchRequest,
    CatalogColumnsSemanticsBatchResponse,
    CatalogDdlResponse,
    CatalogForeignKeyOut,
    CatalogIndexOut,
    CatalogObjectListResponse,
    CatalogObjectOut,
    CatalogObjectResponse,
    CatalogObjectSearchResponse,
    ColumnSemanticsPatchRequest,
    JoinBatchResponse,
    JoinBatchUpsertRequest,
    JoinListResponse,
    JoinOut,
    JoinPathHopOut,
    JoinPathOut,
    JoinPathResponse,
    JoinResponse,
    JoinUpsertRequest,
    ObjectSemanticsPatchRequest,
)

router = APIRouter(tags=["catalog"])


def _column_out(view: catalog_service.ColumnView) -> CatalogColumnOut:
    return CatalogColumnOut(
        id=view.id,
        locator_key=view.locator_key,
        name=view.name,
        data_type=view.data_type,
        nullable=view.nullable,
        default_value=view.default_value,
        comment=view.comment,
        business_name=view.business_name,
        business_description=view.business_description,
        column_semantics=view.column_semantics,
        enum_catalog=view.enum_catalog,
        semantic_source=view.semantic_source,
        field_kind=view.field_kind,
        ordinal=view.ordinal,
        is_present=view.is_present,
    )


def _object_out(view: catalog_service.ObjectView) -> CatalogObjectOut:
    from backend.metadata.schemas.catalog import BusinessDomainRef

    domain = None
    if view.business_domain is not None:
        domain = BusinessDomainRef(
            id=view.business_domain.id,
            code=view.business_domain.code,
            name=view.business_domain.name,
        )
    return CatalogObjectOut(
        id=view.id,
        locator_key=view.locator_key,
        source_id=view.source_id,
        object_type=view.object_type,
        schema_name=view.schema_name,
        name=view.name,
        comment=view.comment,
        primary_key=view.primary_key,
        business_name=view.business_name,
        business_description=view.business_description,
        object_category=view.object_category,
        grain_description=view.grain_description,
        business_primary_key=view.business_primary_key,
        business_domain=domain,
        evidence_summary=view.evidence_summary,
        open_questions=view.open_questions,
        semantic_source=view.semantic_source,
        business_semantics_ready=view.business_semantics_ready,
        semantics_updated_at=view.semantics_updated_at,
        columns=[_column_out(c) for c in view.columns],
        foreign_keys=[
            CatalogForeignKeyOut(
                name=fk.name,
                columns=list(fk.columns),
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=list(fk.ref_columns),
                is_present=fk.is_present,
            )
            for fk in view.foreign_keys
        ],
        indexes=[
            CatalogIndexOut(
                name=idx.name,
                columns=list(idx.columns),
                is_unique=idx.is_unique,
                is_present=idx.is_present,
            )
            for idx in view.indexes
        ],
        ddl=view.ddl,
        is_present=view.is_present,
        collected_at=view.collected_at,
    )


def _join_out(view: catalog_service.JoinView) -> JoinOut:
    return JoinOut(
        id=view.id,
        from_column_id=view.from_column_id,
        to_column_id=view.to_column_id,
        from_column_locator_key=view.from_column_locator_key,
        to_column_locator_key=view.to_column_locator_key,
        evidence=view.evidence,
        join_kind=view.join_kind,
        join_expression=view.join_expression,
        origin=view.origin,
        created_by_user_id=view.created_by_user_id,
        created_at=view.created_at,
    )


def _object_out_from_record(record, *, include_columns: bool) -> CatalogObjectOut:
    return _object_out(catalog_service.object_view(record, include_columns=include_columns))


def _join_out_from_record(record) -> JoinOut:
    return _join_out(catalog_service.join_view(record))


@router.get("/sources/{source_id}/objects", response_model=CatalogObjectListResponse)
def list_objects(
    source_id: str,
    q: str | None = None,
    object_type: str | None = None,
    include_absent: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectListResponse:
    items, total = catalog_service.list_objects_for_source(
        source_id,
        q=q,
        object_type=object_type,
        include_absent=include_absent,
        limit=limit,
        offset=offset,
    )
    return CatalogObjectListResponse(
        items=[_object_out(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/catalog/objects/search", response_model=CatalogObjectSearchResponse)
def search_objects(
    q: str = Query(..., min_length=1),
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectSearchResponse:
    items, total = catalog_service.search_objects(
        q,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return CatalogObjectSearchResponse(
        items=[_object_out(o) for o in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/catalog/columns/search", response_model=CatalogColumnSearchResponse)
def search_columns(
    q: str = Query(..., min_length=1),
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogColumnSearchResponse:
    items, total = catalog_service.search_columns(
        q,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return CatalogColumnSearchResponse(
        items=[_column_out(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/objects/{object_id}", response_model=CatalogObjectResponse)
def get_object(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectResponse:
    return CatalogObjectResponse(object=_object_out(catalog_service.get_object(object_id)))


@router.get("/objects/{object_id}/ddl", response_model=CatalogDdlResponse)
def get_object_ddl(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogDdlResponse:
    ddl = catalog_service.get_object_ddl(object_id)
    return CatalogDdlResponse(id=ddl.id, ddl=ddl.ddl)


@router.patch("/objects/{object_id}/semantics", response_model=CatalogObjectResponse)
def patch_object_semantics(
    object_id: str,
    payload: ObjectSemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogObjectResponse:
    data = payload.model_dump(exclude_unset=True)
    record = catalog_service.patch_object_semantics(
        object_id=object_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogObjectResponse(
        object=_object_out_from_record(record, include_columns=True)
    )


@router.patch("/columns/{column_id}/semantics", response_model=CatalogColumnResponse)
def patch_column_semantics(
    column_id: str,
    payload: ColumnSemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogColumnResponse:
    data = payload.model_dump(exclude_unset=True)
    record, _applied = catalog_service.patch_column_semantics(
        column_id=column_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogColumnResponse(column=_column_out(catalog_service.column_view(record)))


@router.patch(
    "/objects/{object_id}/columns/semantics",
    response_model=CatalogColumnsSemanticsBatchResponse,
)
def patch_columns_semantics_batch(
    object_id: str,
    payload: CatalogColumnsSemanticsBatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogColumnsSemanticsBatchResponse:
    result = catalog_service.set_column_semantics_batch(
        object_id=object_id,
        columns=[item.model_dump(exclude_unset=True) for item in payload.columns],
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogColumnsSemanticsBatchResponse(
        object=_object_out(catalog_service.get_object(object_id)),
        updated_count=result["updated_count"],
        requested_count=result["requested_count"],
        skipped_columns=result["skipped_columns"],
    )


@router.get("/objects/{object_id}/joins", response_model=JoinListResponse)
def list_object_joins(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> JoinListResponse:
    return JoinListResponse(items=[_join_out(j) for j in catalog_service.list_joins(object_id)])


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
        join_kind=payload.join_kind or "INNER",
        join_expression=payload.join_expression,
        origin="human",
    )
    return JoinResponse(join=_join_out_from_record(record))


@router.put("/joins:batch", response_model=JoinBatchResponse)
def upsert_joins_batch(
    payload: JoinBatchUpsertRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinBatchResponse:
    items, created, known = catalog_service.upsert_joins_batch(
        joins=[j.model_dump() for j in payload.joins],
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        origin="human",
    )
    return JoinBatchResponse(
        created_count=created,
        already_known_count=known,
        items=[_join_out_from_record(j) for j in items],
    )


@router.get("/joins/path", response_model=JoinPathResponse)
def get_join_path(
    start: str = Query(...),
    target: str | None = None,
    max_hops: int = Query(default=1, ge=1, le=5),
    top_targets: int = Query(default=3, ge=1, le=20),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> JoinPathResponse:
    result = catalog_service.lookup_join_paths(
        start,
        target,
        max_hops=max_hops,
        top_targets=top_targets,
    )
    return JoinPathResponse(
        paths_found=result.paths_found,
        paths=[
            JoinPathOut(
                target_object_id=path.target_object_id,
                target_column_id=path.target_column_id,
                hops=[
                    JoinPathHopOut(
                        from_column_id=hop.from_column_id,
                        to_column_id=hop.to_column_id,
                        from_column_locator_key=hop.from_column_locator_key,
                        to_column_locator_key=hop.to_column_locator_key,
                        join_id=hop.join_id,
                        join_kind=hop.join_kind,
                        join_expression=hop.join_expression,
                        evidence=hop.evidence,
                        origin=hop.origin,
                    )
                    for hop in path.hops
                ],
                path_summary=path.path_summary,
            )
            for path in result.paths
        ],
        direct_joins=[_join_out(j) for j in result.direct_joins],
        reason=result.reason,
    )


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
