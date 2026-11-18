"""Source HTTP routers (encrypted access blob + Connector Spec)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.core.pagination import SOURCE_LIST, PageParams, page_params

from backend.admin.audit import persist_audit_event
from backend.admin.deps import (
    get_actor_token_id,
    get_current_user,
    require_permission,
    resolve_user_permissions,
)
from backend.admin.errors import AuthForbidden
from backend.admin.permissions import permissions_include
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.user_store import UserRecord
from backend.metadata.capture.control import capture_status
from backend.metadata.connectors.specs import get_connector_spec
from backend.metadata.errors import (
    SourceAccessRequired,
    SourceSecretRequired,
)
from backend.metadata.sources.access import (
    decrypt_access_blob,
    validate_access,
)
from backend.metadata.sources import service as source_service
from backend.core.admission import await_admitted
from backend.metadata.sources.probe import ProbeResult, run_source_probe
from backend.metadata.sources.store import SourceRecord
from backend.metadata.schemas.sources import (
    AccessSchemaResponse,
    CreateSourceRequest,
    PatchSourceRequest,
    PatchSourceResponse,
    SourceAccessResponse,
    SourceListResponse,
    SourceOut,
    SourceResponse,
    SourceTestResponse,
    TestSourceDraftRequest,
    TestSourceRequest,
)

router = APIRouter(tags=["sources"])

_SOURCE_LIST_KEYS = ("sources:read", "sources:access_manage")


def require_source_list_access(
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> UserRecord:
    perms = resolve_user_permissions(user, roles)
    if any(permissions_include(perms, key) for key in _SOURCE_LIST_KEYS):
        return user
    raise AuthForbidden()


def _source_out(record: SourceRecord) -> SourceOut:
    return SourceOut.model_validate(source_service.public_view(record))


@router.get(
    "/sources",
    response_model=SourceListResponse,
    response_model_exclude_unset=True,
)
def list_sources(
    user: UserRecord = Depends(require_source_list_access),
    page: PageParams = Depends(page_params(SOURCE_LIST)),
    q: str | None = Query(default=None),
    engine: Literal["postgresql", "mssql", "oracle", "mysql"] | None = Query(default=None),
) -> SourceListResponse:
    items, total = source_service.list_sources_for_user(
        user,
        query_text=(q or "").strip() or None,
        engine=engine,
        limit=page.limit,
        offset=page.offset,
    )
    return SourceListResponse(
        items=[SourceOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/sources/access-schema/{engine}",
    response_model=AccessSchemaResponse,
)
def get_access_schema(
    engine: str,
    _: UserRecord = Depends(require_permission("sources:read")),
) -> AccessSchemaResponse:
    schema = get_connector_spec(engine)
    return AccessSchemaResponse(engine=engine, schema=schema)


@router.post("/sources", response_model=SourceResponse, status_code=201)
def post_source(
    payload: CreateSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceResponse:
    record = source_service.create_source(
        key=payload.key,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        engine=payload.engine,
        access=payload.access,
        capture_credential=payload.capture_credential,
        snapshot_window=payload.snapshot_window,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.create",
        result="success",
        detail={
            "fields": sorted(payload.model_fields_set),
            "key": record.key,
            "kind": record.kind,
            "engine": record.engine,
            "capture_credential": "replace"
            if payload.capture_credential
            else "clear"
            if "capture_credential" in payload.model_fields_set
            else "retain",
        },
    )
    return SourceResponse(source=_source_out(record))


@router.post("/sources/test", response_model=SourceTestResponse)
async def test_source_draft(
    payload: TestSourceDraftRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceTestResponse:
    access = validate_access(payload.engine, payload.access)

    def _probe() -> ProbeResult:
        return run_source_probe(
            engine=payload.engine,
            access=access,
        )

    result = await await_admitted(user.id, _probe)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id="draft",
        action="source.test",
        result="success" if result.ok else "failure",
        detail={
            "engine": payload.engine,
            "host": access.get("host"),
            "port": access.get("port"),
            "ok": result.ok,
            "code": result.code,
        },
    )
    return SourceTestResponse(ok=result.ok, code=result.code, message=result.message)


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: str,
    user: UserRecord = Depends(require_permission("sources:read")),
) -> SourceResponse:
    record = source_service.require_source_permission(
        user.id, source_id, "sources:read"
    )
    return SourceResponse(source=_source_out(record))


@router.get("/sources/{source_id}/capture-status")
def get_source_capture_status(
    source_id: str,
    user: UserRecord = Depends(require_permission("sources:read")),
) -> dict:
    source_service.require_source_permission(user.id, source_id, "sources:read")
    return capture_status(source_id)


@router.get("/sources/{source_id}/access", response_model=SourceAccessResponse)
def get_source_access(
    source_id: str,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceAccessResponse:
    record = source_service.require_source_permission(
        user.id, source_id, "sources:write"
    )
    return SourceAccessResponse(access=source_service.full_access(record))


@router.patch(
    "/sources/{source_id}",
    response_model=PatchSourceResponse,
    response_model_exclude_unset=True,
)
def patch_source(
    source_id: str,
    payload: PatchSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> PatchSourceResponse:
    source_service.require_source_permission(user.id, source_id, "sources:write")
    fields = payload.model_fields_set
    record, seeded = source_service.update_source(
        source_id,
        name=payload.name,
        description=payload.description if "description" in fields else ...,
        status=payload.status,
        engine=payload.engine,
        access=payload.access if "access" in fields else ...,
        capture_credential=payload.capture_credential if "capture_credential" in fields else ...,
        snapshot_window=payload.snapshot_window if "snapshot_window" in fields else ...,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        patch_fields=fields,
    )
    if not seeded:
        return PatchSourceResponse(source=_source_out(record))
    return PatchSourceResponse(source=_source_out(record), schedules=seeded)


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_source_endpoint(
    source_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> Response:
    source_service.require_source_permission(user.id, source_id, "sources:write")
    record = source_service.delete_source(source_id)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.delete",
        result="success",
        detail={"key": record.key},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sources/{source_id}/test", response_model=SourceTestResponse)
async def test_source_stored(
    source_id: str,
    payload: TestSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceTestResponse:
    record = source_service.require_source_permission(
        user.id, source_id, "sources:write"
    )

    engine = payload.engine or record.engine
    if not engine:
        raise SourceAccessRequired("Source has no engine for this probe")

    if payload.access is not None:
        access = validate_access(engine, payload.access)
    else:
        if not record.access_ciphertext:
            raise SourceSecretRequired()
        access = validate_access(engine, decrypt_access_blob(record.access_ciphertext))

    def _probe() -> ProbeResult:
        return run_source_probe(
            engine=engine,
            access=access,
        )

    result = await await_admitted(user.id, _probe)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.test",
        result="success" if result.ok else "failure",
        detail={
            "engine": engine,
            "host": access.get("host"),
            "port": access.get("port"),
            "ok": result.ok,
            "code": result.code,
        },
    )
    return SourceTestResponse(ok=result.ok, code=result.code, message=result.message)
