"""Type Mapping HTTP routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params
from backend.metadata.type_mappings import service as mapping_service
from backend.metadata.type_mappings.store import TypeMappingRecord
from backend.metadata.schemas.type_mappings import (
    TypeMappingListResponse,
    TypeMappingOut,
    TypeMappingPatchRequest,
    TypeMappingResponse,
)

router = APIRouter(tags=["type-mappings"])


def _mapping_out(record: TypeMappingRecord) -> TypeMappingOut:
    return TypeMappingOut(
        id=record.id,
        engine=record.engine,
        native_type=record.native_type,
        normalized_type=record.normalized_type,
        origin=record.origin,  # type: ignore[arg-type]
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/type-mappings", response_model=TypeMappingListResponse)
def list_type_mappings(
    q: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    page: PageParams = Depends(page_params(default_limit=100, max_limit=500)),
    _: UserRecord = Depends(require_permission("metadata:read")),
) -> TypeMappingListResponse:
    items, total = mapping_service.list_mappings(
        q=q, engine=engine, origin=origin, limit=page.limit, offset=page.offset
    )
    return TypeMappingListResponse(
        items=[_mapping_out(i) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/type-mappings/{mapping_id}", response_model=TypeMappingResponse)
def patch_type_mapping(
    mapping_id: str,
    body: TypeMappingPatchRequest,
    user: UserRecord = Depends(require_permission("metadata:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> TypeMappingResponse:
    record = mapping_service.patch_mapping(
        mapping_id=mapping_id,
        normalized_type=body.normalized_type,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return TypeMappingResponse(mapping=_mapping_out(record))
