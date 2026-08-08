"""Source HTTP routers (encrypted access blob + Connector Spec)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
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
from backend.metadata.sources.probe import run_source_probe
from backend.metadata.sources.store import SourceRecord, get_source_store
from backend.metadata.schemas.sources import (
    AccessSchemaResponse,
    CreateSourceRequest,
    PatchSourceRequest,
    SourceAccessResponse,
    SourceListResponse,
    SourceOut,
    SourceResponse,
    SourceTestResponse,
    TestSourceDraftRequest,
    TestSourceRequest,
)

router = APIRouter(tags=["sources"])


def _source_out(record: SourceRecord) -> SourceOut:
    return SourceOut.model_validate(source_service.public_view(record))


@router.get("/sources", response_model=SourceListResponse)
def list_sources(
    _: UserRecord = Depends(require_permission("sources:read")),
) -> SourceListResponse:
    items = [_source_out(r) for r in get_source_store().list_sources()]
    return SourceListResponse(items=items)


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
        database_name=payload.database_name,
        schema_filter=payload.schema_filter,
        engine=payload.engine,
        access=payload.access,
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.create",
        result="success",
        detail={"key": record.key, "kind": record.kind, "engine": record.engine},
    )
    return SourceResponse(source=_source_out(record))


@router.post("/sources/test", response_model=SourceTestResponse)
def test_source_draft(
    payload: TestSourceDraftRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceTestResponse:
    access = validate_access(payload.engine, payload.access)
    result = run_source_probe(
        engine=payload.engine,
        access=access,
        database_name=payload.database_name,
    )
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
    _: UserRecord = Depends(require_permission("sources:read")),
) -> SourceResponse:
    record = source_service.require_source(source_id)
    return SourceResponse(source=_source_out(record))


@router.get("/sources/{source_id}/access", response_model=SourceAccessResponse)
def get_source_access(
    source_id: str,
    _: UserRecord = Depends(require_permission("sources:write")),
) -> SourceAccessResponse:
    record = source_service.require_source(source_id)
    return SourceAccessResponse(access=source_service.full_access(record))


@router.patch("/sources/{source_id}", response_model=SourceResponse)
def patch_source(
    source_id: str,
    payload: PatchSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceResponse:
    data = payload.model_dump(exclude_unset=True)
    record = source_service.update_source(
        source_id,
        name=data.get("name"),
        description=data["description"] if "description" in data else ...,
        status=data.get("status"),
        database_name=data.get("database_name"),
        schema_filter=data["schema_filter"] if "schema_filter" in data else ...,
        engine=data.get("engine"),
        access=data["access"] if "access" in data else ...,
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.update",
        result="success",
        detail={"fields": sorted(data.keys())},
    )
    return SourceResponse(source=_source_out(record))


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
def test_source_stored(
    source_id: str,
    payload: TestSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceTestResponse:
    record = source_service.require_source(source_id)

    engine = payload.engine or record.engine
    if not engine:
        raise SourceAccessRequired("Source has no engine for this probe")

    if payload.access is not None:
        access = validate_access(engine, payload.access)
    else:
        if not record.access_ciphertext:
            raise SourceSecretRequired()
        access = validate_access(engine, decrypt_access_blob(record.access_ciphertext))

    result = run_source_probe(
        engine=engine,
        access=access,
        database_name=payload.database_name,
    )
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
