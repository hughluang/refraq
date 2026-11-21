"""Authenticated global mirror Operations; no data-plane HTTP surface."""

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.mirrors import recovery, service
from backend.metadata.mirrors.recovery_schemas import RecoveryRequest
from backend.metadata.mirrors.schemas import (
    MirrorListResponse,
    MirrorDetailResponse,
    MirrorStatus,
    PatchMirrorRequest,
    PatchMirrorResponse,
    RecoveryResponse,
)

router = APIRouter(tags=["mirrors"])


@router.get("/mirrors", response_model=MirrorListResponse)
def list_mirrors(
    _: UserRecord = Depends(require_permission("mirror:read")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source_id: str | None = None,
    status: MirrorStatus | None = None,
    q: str | None = None,
):
    return service.list_mirrors(
        limit=limit, offset=offset, source_id=source_id, status=status, q=q
    )


@router.get("/mirrors/{mirror_id}", response_model=MirrorDetailResponse)
def get_mirror(
    mirror_id: str, _: UserRecord = Depends(require_permission("mirror:read"))
):
    return service.get_mirror_detail(mirror_id)


@router.patch("/mirrors/{mirror_id}", response_model=PatchMirrorResponse)
def patch_mirror(
    mirror_id: str,
    payload: PatchMirrorRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("mirror:write")),
):
    return service.set_enabled(
        mirror_id,
        enabled=payload.enabled,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )


@router.delete("/mirrors/{mirror_id}", status_code=204)
def delete_mirror(
    mirror_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("mirror:write")),
):
    service.delete_mirror(
        mirror_id, actor_user_id=user.id, actor_token_id=get_actor_token_id(request)
    )
    return Response(status_code=204)


@router.post(
    "/mirrors/{mirror_id}/recovery-requests",
    response_model=RecoveryResponse,
    status_code=202,
)
def recovery_request(
    mirror_id: str,
    payload: RecoveryRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("mirror:write")),
):
    return recovery.request_recovery(
        mirror_id,
        **payload.model_dump(),
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
