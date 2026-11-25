"""Authenticated global mirror Operations; no data-plane HTTP surface."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission, resolve_user_permissions
from backend.admin.permissions import permissions_include
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.metadata.mirrors import recovery, service
from backend.metadata.mirrors import diagnostics
from backend.metadata.mirrors.diagnostic_schemas import DiagnosticsResponse, MeasurementResponse
from backend.metadata.mirrors.diagnostic_schemas import Health, Link
from backend.metadata.mirrors.fleet_schemas import (
    AttentionCause, FleetOverview, GroupedState, InventoryPage, InventorySort, RuntimeFleetPage, SourceFleetPage,
)
from backend.metadata.mirrors.recovery_schemas import RecoveryRequest
from backend.metadata.capture.setup_guide import setup_guide
from backend.metadata.mirrors.schemas import (
    JournalPage,
    MirrorDetailResponse,
    MirrorActionReceipt,
    MirrorSetupGuide,
    MirrorStatus,
    PatchMirrorRequest,
    PatchMirrorResponse,
    RecoveryResponse,
)
from backend.metadata.mirrors.throughput import ThroughputResponse, read_throughput

router = APIRouter(tags=["mirrors"])


@router.get("/mirror-diagnostics", response_model=DiagnosticsResponse)
def read_diagnostics(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    source_id: str | None = None, runtime_id: str | None = None, q: str | None = Query(default=None, max_length=256),
    source_offset: int = Query(default=0, ge=0), runtime_offset: int = Query(default=0, ge=0),
    assignment_offset: int = Query(default=0, ge=0),
):
    return diagnostics.read_diagnostics(store=request.app.state.mirror_diagnostics,
                                        read_scope=request.app.state.mirror_diagnostic_scope,
                                        source_id=source_id, runtime_id=runtime_id, q=q,
                                        source_offset=source_offset, runtime_offset=runtime_offset,
                                        assignment_offset=assignment_offset)


@router.get("/mirror-fleet", response_model=FleetOverview)
def fleet_overview(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    source_id: str | None = None, runtime_id: str | None = None, rank: Literal["size", "attention"] = "size",
):
    return request.app.state.mirror_fleet_reads["overview"](source_id=source_id, runtime_id=runtime_id, rank=rank)


@router.get("/mirror-fleet/sources", response_model=SourceFleetPage)
def fleet_sources(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    source_id: str | None = None, runtime_id: str | None = None, q: str | None = Query(default=None, max_length=256),
    health: Health | None = None, segment: Link | None = None,
    limit: int = Query(default=12, ge=1, le=100), offset: int = Query(default=0, ge=0),
):
    return request.app.state.mirror_fleet_reads["sources"](source_id=source_id, runtime_id=runtime_id,
                                                          q=q, health=health, segment=segment, limit=limit, offset=offset)


@router.get("/mirror-fleet/runtimes", response_model=RuntimeFleetPage)
def fleet_runtimes(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    source_id: str | None = None, runtime_id: str | None = None, q: str | None = Query(default=None, max_length=256),
    health: Health | None = None, segment: Link | None = None,
    limit: int = Query(default=12, ge=1, le=100), offset: int = Query(default=0, ge=0),
):
    return request.app.state.mirror_fleet_reads["runtimes"](source_id=source_id, runtime_id=runtime_id,
                                                           q=q, health=health, segment=segment, limit=limit, offset=offset)


@router.get("/mirror-throughput", response_model=ThroughputResponse)
def fleet_throughput(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    source_id: str | None = None, runtime_id: str | None = None, hours: Literal["1", "6", "24"] = "6",
):
    return read_throughput(store=request.app.state.mirror_diagnostics,
        read_scope=request.app.state.mirror_diagnostic_scope, source_id=source_id, runtime_id=runtime_id, hours=int(hours))


@router.get("/mirror-setup", response_model=MirrorSetupGuide)
def read_mirror_setup(_: UserRecord = Depends(require_permission("mirror:read"))):
    return setup_guide()


@router.get("/mirrors", response_model=InventoryPage)
def list_mirrors(
    request: Request,
    _: UserRecord = Depends(require_permission("mirror:read")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source_id: str | None = None,
    status: MirrorStatus | None = None,
    q: str | None = None,
    runtime_id: str | None = None,
    grouped_state: GroupedState | None = None,
    published_only: bool = False,
    cause: AttentionCause | None = None,
    sort: InventorySort = "priority",
):
    return request.app.state.mirror_fleet_reads["inventory"](
        limit=limit, offset=offset, source_id=source_id, status=status, q=q,
        runtime_id=runtime_id, grouped_state=grouped_state, published_only=published_only, cause=cause, sort=sort,
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


@router.get("/mirrors/{mirror_id}/measurements", response_model=MeasurementResponse)
def mirror_measurements(mirror_id: str, request: Request,
                        _: UserRecord = Depends(require_permission("mirror:read"))):
    return diagnostics.mirror_measurements(mirror_id, store=request.app.state.mirror_diagnostics,
                                           read_scope=request.app.state.mirror_diagnostic_scope,
                                           read_detail=service.get_mirror_detail)


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
