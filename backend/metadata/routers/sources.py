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
from backend.metadata.capture.precheck import resolve_capture_login, run_capture_precheck
from backend.metadata.connectors.specs import get_connector_spec
from backend.metadata.errors import (
    SourceAccessRequired,
    SourceSecretRequired,
)
from backend.metadata.source_access import effective_permissions
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
    CaptureCheckDraftRequest,
    CaptureCheckRequest,
    CaptureCheckResponse,
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


def _source_out(record: SourceRecord, user: UserRecord) -> SourceOut:
    return SourceOut(
        **source_service.public_view(record),
        can_write="sources:write" in effective_permissions(user.id, record.id),
    )


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
    return SourceResponse(source=_source_out(record, user))


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


def _capture_counts(entries: list[dict] | None) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "unknown": 0, "not_applicable": 0}
    for entry in entries or []:
        result = entry.get("result")
        if result in counts:
            counts[result] += 1
    return counts


def _audit_capture_check(*, user, request, resource_id, engine, access, credential, result) -> None:
    detail = {
        "engine": engine,
        "host": access.get("host"),
        "port": access.get("port"),
        "credential": credential,
        "ok": result.ok,
        "code": result.code,
    }
    if result.ok:
        detail["items"] = _capture_counts(result.items)
        detail["tables"] = _capture_counts((result.tables or {}).get("items"))
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=resource_id,
        action="source.capture_check",
        result="success" if result.ok else "failure",
        detail=detail,
    )


@router.post(
    "/sources/capture-check",
    response_model=CaptureCheckResponse,
    response_model_exclude_none=True,
)
async def capture_check_draft(
    payload: CaptureCheckDraftRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> CaptureCheckResponse:
    access = validate_access(payload.engine, payload.access)
    username, password, credential = resolve_capture_login(
        request_username=(
            payload.capture_credential.username.get_secret_value()
            if payload.capture_credential is not None else None
        ),
        request_password=(
            payload.capture_credential.password.get_secret_value()
            if payload.capture_credential is not None else None
        ),
        stored_ciphertext=None,
        access=access,
    )
    override = None if credential == "access" else (username, password)

    def _check():
        return run_capture_precheck(
            engine=payload.engine,
            access=access,
            credential_override=override,
            credential=credential,
        )

    result = await await_admitted(user.id, _check)
    _audit_capture_check(
        user=user, request=request, resource_id="draft", engine=payload.engine,
        access=access, credential=credential, result=result,
    )
    return CaptureCheckResponse.model_validate(result.public())


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: str,
    user: UserRecord = Depends(require_permission("sources:read")),
) -> SourceResponse:
    record = source_service.require_source_permission(
        user.id, source_id, "sources:read"
    )
    return SourceResponse(source=_source_out(record, user))


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
        return PatchSourceResponse(source=_source_out(record, user))
    return PatchSourceResponse(source=_source_out(record, user), schedules=seeded)


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


@router.post(
    "/sources/{source_id}/capture-check",
    response_model=CaptureCheckResponse,
    response_model_exclude_none=True,
)
async def capture_check_stored(
    source_id: str,
    payload: CaptureCheckRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> CaptureCheckResponse:
    record = source_service.require_source_permission(
        user.id, source_id, "sources:write"
    )
    engine = payload.engine or record.engine
    if not engine:
        raise SourceAccessRequired("Source has no engine for this check")
    if payload.access is not None:
        access = validate_access(engine, payload.access)
    else:
        if not record.access_ciphertext:
            raise SourceSecretRequired()
        access = validate_access(engine, decrypt_access_blob(record.access_ciphertext))
    username, password, credential = resolve_capture_login(
        request_username=(
            payload.capture_credential.username.get_secret_value()
            if payload.capture_credential is not None else None
        ),
        request_password=(
            payload.capture_credential.password.get_secret_value()
            if payload.capture_credential is not None else None
        ),
        stored_ciphertext=record.capture_credential_ciphertext,
        access=access,
    )
    override = None if credential == "access" else (username, password)

    def _check():
        return run_capture_precheck(
            engine=engine,
            access=access,
            credential_override=override,
            credential=credential,
        )

    result = await await_admitted(user.id, _check)
    _audit_capture_check(
        user=user, request=request, resource_id=record.id, engine=engine,
        access=access, credential=credential, result=result,
    )
    return CaptureCheckResponse.model_validate(result.public())
