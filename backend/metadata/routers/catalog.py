"""Catalog browse, semantics, and join HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi import Request

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.catalog import service as catalog_service
from backend.metadata.catalog.store import get_catalog_store, require_object
from backend.metadata.errors import (
    CatalogColumnNotFound,
    CatalogObjectNotFound,
    CatalogSearchQueryRequired,
    JoinPathUnavailable,
)
from backend.metadata.joins.graph import find_join_paths
from backend.metadata.sources.service import require_source
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


def _domain_ref(domain_id: str | None):
    if not domain_id:
        return None
    from backend.metadata.business_domains.store import get_business_domain_store
    from backend.metadata.schemas.catalog import BusinessDomainRef

    record = get_business_domain_store().get(domain_id)
    if record is None:
        return None
    return BusinessDomainRef(id=record.id, code=record.code, name=record.name)


def _column_out(record) -> CatalogColumnOut:
    return CatalogColumnOut(
        id=record.id,
        locator_key=record.locator_key,
        name=record.name,
        data_type=record.data_type,
        nullable=record.nullable,
        default_value=record.default_value,
        comment=record.comment,
        business_name=record.business_name,
        business_description=record.business_description,
        column_semantics=record.column_semantics,
        enum_catalog=record.enum_catalog,
        semantic_source=record.semantic_source,
        field_kind=record.field_kind,
        ordinal=record.ordinal,
        is_present=record.is_present,
    )


def _object_out(record, *, include_columns: bool) -> CatalogObjectOut:
    columns = []
    foreign_keys: list[CatalogForeignKeyOut] = []
    indexes: list[CatalogIndexOut] = []
    if include_columns:
        columns = [_column_out(c) for c in record.columns]
        foreign_keys = [
            CatalogForeignKeyOut(
                name=fk.name,
                columns=list(fk.columns),
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=list(fk.ref_columns),
                is_present=fk.is_present,
            )
            for fk in record.foreign_keys
        ]
        indexes = [
            CatalogIndexOut(
                name=idx.name,
                columns=list(idx.columns),
                is_unique=idx.is_unique,
                is_present=idx.is_present,
            )
            for idx in record.indexes
        ]
    return CatalogObjectOut(
        id=record.id,
        locator_key=record.locator_key,
        source_id=record.source_id,
        object_type=record.object_type,
        schema_name=record.schema_name,
        name=record.name,
        comment=record.comment,
        primary_key=record.primary_key,
        business_name=record.business_name,
        business_description=record.business_description,
        object_category=record.object_category,
        grain_description=record.grain_description,
        business_primary_key=record.business_primary_key,
        business_domain=_domain_ref(record.business_domain_id),
        evidence_summary=record.evidence_summary,
        open_questions=record.open_questions,
        semantic_source=record.semantic_source,
        business_semantics_ready=record.business_semantics_ready,
        semantics_updated_at=record.semantics_updated_at,
        columns=columns if include_columns else [],
        foreign_keys=foreign_keys,
        indexes=indexes,
        ddl=record.ddl if include_columns else None,
        is_present=record.is_present,
        collected_at=record.collected_at,
    )


def _join_out(record, *, store) -> JoinOut:
    from_col = store.get_column(record.from_column_id)
    to_col = store.get_column(record.to_column_id)
    return JoinOut(
        id=record.id,
        from_column_id=record.from_column_id,
        to_column_id=record.to_column_id,
        from_column_locator_key=from_col.locator_key if from_col else None,
        to_column_locator_key=to_col.locator_key if to_col else None,
        evidence=record.evidence,
        join_kind=record.join_kind,
        join_expression=record.join_expression,
        origin=record.origin,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
    )


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
    require_source(source_id)
    items, total = get_catalog_store().list_objects(
        source_id,
        name_search=q,
        include_absent=include_absent,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return CatalogObjectListResponse(
        items=[_object_out(o, include_columns=False) for o in items],
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
    query = q.strip()
    if not query:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_objects(
        query,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return CatalogObjectSearchResponse(
        items=[_object_out(o, include_columns=False) for o in items],
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
    query = q.strip()
    if not query:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_columns(
        query,
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
    return CatalogObjectResponse(object=_object_out(record, include_columns=True))


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
    return CatalogColumnResponse(column=_column_out(record))


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
    record = require_object(object_id)
    return CatalogColumnsSemanticsBatchResponse(
        object=_object_out(record, include_columns=True),
        updated_count=result["updated_count"],
        requested_count=result["requested_count"],
        skipped_columns=result["skipped_columns"],
    )


@router.get("/objects/{object_id}/joins", response_model=JoinListResponse)
def list_object_joins(
    object_id: str,
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> JoinListResponse:
    store = get_catalog_store()
    items = [_join_out(j, store=store) for j in catalog_service.list_joins(object_id)]
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
        join_kind=payload.join_kind or "INNER",
        join_expression=payload.join_expression,
        origin="human",
    )
    return JoinResponse(join=_join_out(record, store=get_catalog_store()))


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
    store = get_catalog_store()
    return JoinBatchResponse(
        created_count=created,
        already_known_count=known,
        items=[_join_out(j, store=store) for j in items],
    )


@router.get("/joins/path", response_model=JoinPathResponse)
def get_join_path(
    start: str = Query(...),
    target: str | None = None,
    max_hops: int = Query(default=1, ge=1, le=5),
    top_targets: int = Query(default=3, ge=1, le=20),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> JoinPathResponse:
    store = get_catalog_store()
    start_object_id = None
    start_column_id = None
    try:
        start_col = catalog_service.resolve_column_ref(start)
        start_column_id = start_col.id
    except CatalogColumnNotFound:
        start_col = None
    if start_col is None:
        try:
            start_obj = catalog_service.resolve_object_ref(start)
            start_object_id = start_obj.id
        except CatalogObjectNotFound as exc:
            raise CatalogObjectNotFound() from exc

    target_object_id = None
    target_column_id = None
    if target:
        try:
            t_col = catalog_service.resolve_column_ref(target)
            target_column_id = t_col.id
        except CatalogColumnNotFound:
            t_col = None
        if t_col is None:
            try:
                t_obj = catalog_service.resolve_object_ref(target)
                target_object_id = t_obj.id
            except CatalogObjectNotFound as exc:
                raise CatalogObjectNotFound() from exc

    result = find_join_paths(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
        target_object_id=target_object_id,
        target_column_id=target_column_id,
        max_hops=max_hops,
        top_targets=top_targets,
    )
    if result.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()
    paths = []
    for path in result.paths:
        hops = []
        for hop in path.hops:
            from_col = store.get_column(hop.from_column_id)
            to_col = store.get_column(hop.to_column_id)
            hops.append(
                JoinPathHopOut(
                    from_column_id=hop.from_column_id,
                    to_column_id=hop.to_column_id,
                    from_column_locator_key=from_col.locator_key if from_col else None,
                    to_column_locator_key=to_col.locator_key if to_col else None,
                    join_id=hop.join.id,
                    join_kind=hop.join.join_kind,
                    join_expression=hop.join.join_expression,
                    evidence=hop.join.evidence,
                    origin=hop.join.origin,
                )
            )
        paths.append(
            JoinPathOut(
                target_object_id=path.target_object_id,
                target_column_id=path.target_column_id,
                hops=hops,
                path_summary=path.path_summary,
            )
        )
    return JoinPathResponse(
        paths_found=len(paths),
        paths=paths,
        direct_joins=[_join_out(j, store=store) for j in result.direct_joins],
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
