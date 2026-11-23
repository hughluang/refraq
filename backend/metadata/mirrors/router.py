"""Authenticated global mirror Operations; no data-plane HTTP surface."""

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission, resolve_user_permissions
from backend.admin.permissions import permissions_include
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.metadata.mirrors import recovery, service
from backend.metadata.mirrors.recovery_schemas import RecoveryRequest
from backend.metadata.mirrors.schemas import (
    JournalPage,
    MirrorListResponse,
    MirrorDetailResponse,
    MirrorActionReceipt,
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


@router.get("/mirrors/{mirror_id}/journal", response_model=JournalPage)
def mirror_journal(
    mirror_id: str, before: str | None = None, limit: int = Query(default=20, ge=1, le=100),
    _: UserRecord = Depends(require_permission("mirror:read")),
):
    return service.get_mirror_journal(mirror_id, before=before, limit=limit)


@router.patch("/mirrors/{mirror_id}", response_model=PatchMirrorResponse | MirrorActionReceipt)
def patch_mirror(
    mirror_id: str,
    payload: PatchMirrorRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("mirror:write")),
    roles: RoleStore = Depends(get_role_store),
):
    return service.set_enabled(
        mirror_id,
        enabled=payload.enabled,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        can_read=permissions_include(resolve_user_permissions(user, roles), "mirror:read"),
    )


@router.delete("/mirrors/{mirror_id}", status_code=204, responses={202: {"model": RecoveryResponse}})
def delete_mirror(
    mirror_id: str,
    request: Request,
    expected_control_revision: int | None = Query(default=None, ge=1),
    user: UserRecord = Depends(require_permission("mirror:write")),
):
    pending = service.delete_mirror(
        mirror_id, actor_user_id=user.id, actor_token_id=get_actor_token_id(request), expected_control_revision=expected_control_revision
    )
    if pending:
        return JSONResponse(pending, status_code=202)
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
    if payload.action == "retry" and payload.expected_control_revision is not None:
        return service.request_recheck(mirror_id, expected_epoch=payload.expected_history_epoch,
                                       expected_revision=payload.expected_control_revision, actor_user_id=user.id,
                                       actor_token_id=get_actor_token_id(request), reason=payload.reason)
    return recovery.request_recovery(
        mirror_id,
        **payload.model_dump(exclude={"expected_control_revision"}),
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
