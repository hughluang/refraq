"""Source and Connection HTTP routers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.metadata.errors import ConnectionNotFound, SourceNotFound
from backend.metadata.sources.store import (
    ConnectionRecord,
    SourceRecord,
    create_connection,
    create_source,
    get_source_store,
    rotate_connection_secret,
    update_connection,
    update_source,
)
from backend.repositories.user_store import UserRecord
from backend.schemas.sources import (
    ConnectionListResponse,
    ConnectionOut,
    ConnectionResponse,
    CreateConnectionRequest,
    CreateSourceRequest,
    PatchConnectionRequest,
    PatchSourceRequest,
    PutConnectionSecretRequest,
    SourceListResponse,
    SourceOut,
    SourceResponse,
)

router = APIRouter(tags=["sources"])


def _source_out(record: SourceRecord) -> SourceOut:
    return SourceOut(
        id=record.id,
        key=record.key,
        name=record.name,
        kind=record.kind,
        status=record.status,
        description=record.description,
        database_name=record.database_name,
        schema_filter=record.schema_filter,
    )


def _connection_out(record: ConnectionRecord) -> ConnectionOut:
    return ConnectionOut(
        id=record.id,
        source_id=record.source_id,
        name=record.name,
        engine=record.engine,
        host=record.host,
        port=record.port,
        status=record.status,
        has_secret=record.has_secret,
        secret_updated_at=record.secret_updated_at,
    )


@router.get("/sources", response_model=SourceListResponse)
def list_sources(
    _: UserRecord = Depends(require_permission("sources:read")),
) -> SourceListResponse:
    items = [_source_out(r) for r in get_source_store().list_sources()]
    return SourceListResponse(items=items)


@router.post("/sources", response_model=SourceResponse, status_code=201)
def post_source(
    payload: CreateSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceResponse:
    record = create_source(
        key=payload.key,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        database_name=payload.database_name,
        schema_filter=payload.schema_filter,
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="source",
        resource_id=record.id,
        action="source.create",
        result="success",
        detail={"key": record.key, "kind": record.kind},
    )
    return SourceResponse(source=_source_out(record))


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    source_id: str,
    _: UserRecord = Depends(require_permission("sources:read")),
) -> SourceResponse:
    record = get_source_store().get_source(source_id)
    if record is None:
        raise SourceNotFound()
    return SourceResponse(source=_source_out(record))


@router.patch("/sources/{source_id}", response_model=SourceResponse)
def patch_source(
    source_id: str,
    payload: PatchSourceRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> SourceResponse:
    data = payload.model_dump(exclude_unset=True)
    record = update_source(
        source_id,
        name=data.get("name"),
        description=data["description"] if "description" in data else ...,
        status=data.get("status"),
        database_name=data.get("database_name"),
        schema_filter=data["schema_filter"] if "schema_filter" in data else ...,
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


@router.get(
    "/sources/{source_id}/connections",
    response_model=ConnectionListResponse,
)
def list_source_connections(
    source_id: str,
    _: UserRecord = Depends(require_permission("sources:read")),
) -> ConnectionListResponse:
    store = get_source_store()
    if store.get_source(source_id) is None:
        raise SourceNotFound()
    conn = store.get_connection_for_source(source_id)
    items = [_connection_out(conn)] if conn else []
    return ConnectionListResponse(items=items)


@router.post(
    "/sources/{source_id}/connections",
    response_model=ConnectionResponse,
    status_code=201,
)
def post_connection(
    source_id: str,
    payload: CreateConnectionRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> ConnectionResponse:
    record = create_connection(
        source_id=source_id,
        name=payload.name,
        engine=payload.engine,
        host=payload.host,
        port=payload.port,
        secret=payload.secret.model_dump(),
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="connection",
        resource_id=record.id,
        action="connection.create",
        result="success",
        detail={"source_id": source_id, "engine": record.engine},
    )
    return ConnectionResponse(connection=_connection_out(record))


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
def get_connection(
    connection_id: str,
    _: UserRecord = Depends(require_permission("sources:read")),
) -> ConnectionResponse:
    record = get_source_store().get_connection(connection_id)
    if record is None:
        raise ConnectionNotFound()
    return ConnectionResponse(connection=_connection_out(record))


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
def patch_connection(
    connection_id: str,
    payload: PatchConnectionRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> ConnectionResponse:
    data = payload.model_dump(exclude_unset=True)
    record = update_connection(connection_id, **data)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="connection",
        resource_id=record.id,
        action="connection.update",
        result="success",
        detail={"fields": sorted(data.keys())},
    )
    return ConnectionResponse(connection=_connection_out(record))


@router.put(
    "/connections/{connection_id}/secret",
    response_model=ConnectionResponse,
)
def put_connection_secret(
    connection_id: str,
    payload: PutConnectionSecretRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("sources:write")),
) -> ConnectionResponse:
    record = rotate_connection_secret(
        connection_id, payload.secret.model_dump()
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="connection",
        resource_id=record.id,
        action="connection.secret_rotate",
        result="success",
        detail={},
    )
    return ConnectionResponse(connection=_connection_out(record))
