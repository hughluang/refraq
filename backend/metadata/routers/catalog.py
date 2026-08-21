"""Catalog browse, semantics, and join HTTP adapters."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.core.pagination import (
    CATALOG_OBJECT_LIST,
    CATALOG_SEARCH,
    JOIN_LIST,
    PageParams,
    page_params,
)
from backend.metadata.catalog import join_writes as catalog_joins
from backend.metadata.catalog import semantics as catalog_semantics
from backend.metadata.catalog import service as catalog_reads
from backend.metadata.catalog import views as catalog_views
from backend.metadata.catalog.present import (
    ObjectPresentProfile,
    present_column,
    present_object,
)
from backend.metadata.catalog.join_origin import HUMAN_JOIN_ORIGIN
from backend.metadata.query import service as query_service
from backend.metadata.query.compile_sample import SampleFilterSpec, SampleOrderSpec
from backend.metadata.schemas.catalog import (
    CatalogColumnOut,
    CatalogColumnResponse,
    CatalogColumnSearchResponse,
    CatalogColumnsSemanticsBatchRequest,
    CatalogColumnsSemanticsBatchResponse,
    CatalogDdlResponse,
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
    JoinPatchRequest,
    JoinResponse,
    JoinUpsertRequest,
    ObjectSemanticsPatchRequest,
)
from backend.metadata.schemas.query import SampleRequest, SampleResponse


router = APIRouter(tags=["catalog"])

def _column_out(view: catalog_views.ColumnView) -> CatalogColumnOut:
    return CatalogColumnOut.model_validate(
        present_column(view, include_normalized_type=True)
    )


def _object_out(
    view: catalog_views.ObjectView, *, detail: bool = False
) -> CatalogObjectOut:
    profile = (
        ObjectPresentProfile.HTTP_DETAIL
        if detail
        else ObjectPresentProfile.HTTP_SUMMARY
    )
    return CatalogObjectOut.model_validate(present_object(view, profile=profile))


def _join_out(view: catalog_views.JoinView) -> JoinOut:
    return JoinOut.model_validate(asdict(view))


def _join_out_from_record(record) -> JoinOut:
    return _join_out(catalog_views.join_view(record))


@router.get("/sources/{source_id}/objects", response_model=CatalogObjectListResponse)
def list_objects(
    source_id: str,
    q: str | None = None,
    object_type: str | None = None,
    include_absent: bool = True,
    business_semantics_ready: bool | None = Query(default=None),
    page: PageParams = Depends(page_params(CATALOG_OBJECT_LIST)),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectListResponse:
    items, total = catalog_reads.list_objects_for_source(
        source_id,
        q=q,
        object_type=object_type,
        include_absent=include_absent,
        business_semantics_ready=business_semantics_ready,
        limit=page.limit,
        offset=page.offset,
    )
    return CatalogObjectListResponse(
        items=[_object_out(o) for o in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )

@router.get("/catalog/objects/search", response_model=CatalogObjectSearchResponse)
def search_objects(
    q: str = Query(..., min_length=1),
    source_id: str | None = None,
    object_type: str | None = None,
    page: PageParams = Depends(page_params(CATALOG_SEARCH)),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectSearchResponse:
    items, total = catalog_reads.search_objects(
        q,
        source_id=source_id,
        object_type=object_type,
        limit=page.limit,
        offset=page.offset,
    )
    return CatalogObjectSearchResponse(
        items=[_object_out(o) for o in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )

@router.get("/catalog/columns/search", response_model=CatalogColumnSearchResponse)
def search_columns(
    q: str = Query(..., min_length=1),
    source_id: str | None = None,
    object_type: str | None = None,
    page: PageParams = Depends(page_params(CATALOG_SEARCH)),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogColumnSearchResponse:
    items, total = catalog_reads.search_columns(
        q,
        source_id=source_id,
        object_type=object_type,
        limit=page.limit,
        offset=page.offset,
    )
    return CatalogColumnSearchResponse(
        items=[_column_out(c) for c in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )

@router.get("/objects/{object_id}", response_model=CatalogObjectResponse)
def get_object(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogObjectResponse:
    return CatalogObjectResponse(
        object=_object_out(catalog_reads.get_object(object_id), detail=True)
    )

@router.get("/objects/{object_id}/ddl", response_model=CatalogDdlResponse)
def get_object_ddl(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> CatalogDdlResponse:
    ddl = catalog_reads.get_object_ddl(object_id)
    return CatalogDdlResponse(id=ddl.id, ddl=ddl.ddl)

@router.post("/objects/{object_id}/sample", response_model=SampleResponse)
def run_object_sample(
    object_id: str,
    body: SampleRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("catalog:sample")),
) -> SampleResponse:
    outcome = query_service.run_catalog_sample(
        object_id=object_id,
        columns=body.columns,
        filters=[
            SampleFilterSpec(column=f.column, op=f.op, value=f.value)
            for f in body.filters
        ],
        order_by=[
            SampleOrderSpec(column=o.column, direction=o.direction)
            for o in body.order_by
        ],
        offset=body.offset,
        limit=body.limit,
        include_sql=body.include_sql,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return SampleResponse(
        columns=outcome.columns,
        rows=outcome.rows,
        truncated=outcome.truncated,
        duration_ms=outcome.duration_ms,
        offset=outcome.offset,
        limit=outcome.limit,
        has_more=outcome.has_more,
        sql=outcome.sql,
    )

@router.patch("/objects/{object_id}/semantics", response_model=CatalogObjectResponse)
def patch_object_semantics(
    object_id: str,
    payload: ObjectSemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogObjectResponse:
    data = payload.model_dump(exclude_unset=True)
    record = catalog_semantics.patch_object_semantics(
        object_id=object_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogObjectResponse(
        object=_object_out(
            catalog_views.object_view(record, include_columns=True),
            detail=True,
        )
    )

@router.patch("/columns/{column_id}/semantics", response_model=CatalogColumnResponse)
def patch_column_semantics(
    column_id: str,
    payload: ColumnSemanticsPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> CatalogColumnResponse:
    data = payload.model_dump(exclude_unset=True)
    record, _applied = catalog_semantics.patch_column_semantics(
        column_id=column_id,
        data=data,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogColumnResponse(column=_column_out(catalog_views.column_view(record)))

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
    result = catalog_semantics.set_column_semantics_batch(
        object_id=object_id,
        columns=[item.model_dump(exclude_unset=True) for item in payload.columns],
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        semantic_source="user_input",
    )
    return CatalogColumnsSemanticsBatchResponse(
        object=_object_out(catalog_reads.get_object(object_id), detail=True),
        updated_count=result["updated_count"],
        requested_count=result["requested_count"],
        skipped_columns=result["skipped_columns"],
    )

@router.get("/objects/{object_id}/joins", response_model=JoinListResponse)
def list_object_joins(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
    page: PageParams = Depends(page_params(JOIN_LIST)),
) -> JoinListResponse:
    items, total = catalog_joins.list_joins(
        object_id, limit=page.limit, offset=page.offset
    )
    return JoinListResponse(
        items=[_join_out(j) for j in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )

@router.post("/joins", response_model=JoinResponse, status_code=status.HTTP_201_CREATED)
def create_join(
    payload: JoinUpsertRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinResponse:
    record = catalog_joins.create_join(
        from_column_id=payload.from_column_id,
        to_column_id=payload.to_column_id,
        evidence=payload.evidence,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        join_kind=payload.join_kind or "INNER",
        join_expression=payload.join_expression,
        attester=HUMAN_JOIN_ORIGIN,
    )
    return JoinResponse(join=_join_out_from_record(record))

@router.post("/joins:batch", response_model=JoinBatchResponse)
def create_joins_batch(
    payload: JoinBatchUpsertRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinBatchResponse:
    items, created, known, rejected = catalog_joins.upsert_joins_batch(
        joins=[j.model_dump() for j in payload.joins],
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        attester=HUMAN_JOIN_ORIGIN,
    )
    return JoinBatchResponse(
        created_count=created,
        already_known_count=known,
        rejected_count=rejected,
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
    result = catalog_reads.lookup_join_paths(
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

@router.patch("/joins/{join_id}", response_model=JoinResponse)
def patch_join(
    join_id: str,
    payload: JoinPatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinResponse:
    record = catalog_joins.amend_join(
        join_id=join_id,
        evidence=payload.evidence,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        join_kind=payload.join_kind or "INNER",
        join_expression=payload.join_expression,
    )
    return JoinResponse(join=_join_out_from_record(record))

@router.post("/joins/{join_id}/reject", response_model=JoinResponse)
def reject_join(
    join_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinResponse:
    record = catalog_joins.reject_join(
        join_id=join_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return JoinResponse(join=_join_out_from_record(record))

@router.post("/joins/{join_id}/restore", response_model=JoinResponse)
def restore_join(
    join_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> JoinResponse:
    record = catalog_joins.restore_join(
        join_id=join_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return JoinResponse(join=_join_out_from_record(record))

@router.delete("/joins/{join_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_join(
    join_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("metadata:write")),
) -> Response:
    catalog_joins.delete_join(
        join_id=join_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
