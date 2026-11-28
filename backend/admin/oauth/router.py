"""OAuth Client admin, POST /oauth/token, and RFC 8414/9728 discovery routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.federation.binding_store import BindingStore, get_binding_store
from backend.admin.federation.http_port import OidcHttpPort, get_default_oidc_http
from backend.admin.federation.provider_store import ProviderStore, get_provider_store
from backend.admin.oauth.errors import OAuthClientNotFound, OAuthTokenError
from backend.admin.oauth.exchange import (
    TokenGrantRequest,
    authorization_server_metadata,
    create_oauth_client,
    delete_oauth_client,
    exchange_delegated_token,
    protected_resource_metadata,
    rotate_oauth_client_secret,
    update_oauth_client,
)
from backend.admin.oauth.runtime_store import (
    OAuthRuntimeStore,
    get_oauth_runtime_store,
)
from backend.admin.oauth.schemas import (
    OAuthClientCreateIn,
    OAuthClientList,
    OAuthClientOut,
    OAuthClientPatchIn,
    OAuthClientResponse,
    OAuthClientSecretResponse,
)
from backend.admin.oauth.store import (
    OAuthClientRecord,
    OAuthClientStore,
    get_oauth_client_store,
)
from backend.admin.principal import ResourceSurface, VerifiedOrigin
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.subjects.store import SubjectStore, get_subject_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.pagination import PageParams, page_params

router = APIRouter(tags=["oauth"])

_SURFACE_BY_PATH: dict[str, ResourceSurface] = {
    "mcp/entity": ResourceSurface.ENTITY_MCP,
    "mcp": ResourceSurface.METADATA_MCP,
    "api": ResourceSurface.API,
}


def _client_out(record: OAuthClientRecord) -> OAuthClientOut:
    return OAuthClientOut(
        id=record.id,
        client_id=record.client_id,
        name=record.name,
        description=record.description,
        provider_id=record.provider_id,
        enabled=record.enabled,
        token_endpoint_auth_method=record.token_endpoint_auth_method,  # type: ignore[arg-type]
        jwks=record.jwks,
        jwks_uri=record.jwks_uri,
        secret_prefix=record.secret_prefix,
        client_secret_configured=bool(record.secret_hash),
        allowed_grant_types=list(record.allowed_grant_types),
        allowed_subject_audiences=list(record.allowed_subject_audiences),
        allowed_surfaces=list(record.allowed_surfaces),
        allowed_scopes=list(record.allowed_scopes),
        token_ttl_sec=record.token_ttl_sec,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_used_at=record.last_used_at,
    )


def _require_origin(request: Request) -> VerifiedOrigin:
    origin = VerifiedOrigin.from_request(request)
    if origin is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canonical browser host is not configured",
        )
    return origin


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/api/oauth")
def well_known_oauth_authorization_server(request: Request) -> JSONResponse:
    origin = _require_origin(request)
    return JSONResponse(content=authorization_server_metadata(origin))


@router.get("/.well-known/oauth-protected-resource/{surface_path:path}")
def well_known_oauth_protected_resource(
    surface_path: str, request: Request
) -> JSONResponse:
    cleaned = surface_path.strip("/")
    surface = _SURFACE_BY_PATH.get(cleaned)
    if surface is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    origin = _require_origin(request)
    return JSONResponse(content=protected_resource_metadata(origin, surface))


@router.post("/oauth/token")
def oauth_token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    client_id: str | None = Form(default=None),
    client_secret: str | None = Form(default=None),
    client_assertion_type: str | None = Form(default=None),
    client_assertion: str | None = Form(default=None),
    assertion: str | None = Form(default=None),
    subject_token: str | None = Form(default=None),
    resource: str | None = Form(default=None),
    scope: str | None = Form(default=None),
    http: OidcHttpPort = Depends(get_default_oidc_http),
    clients: OAuthClientStore = Depends(get_oauth_client_store),
    providers: ProviderStore = Depends(get_provider_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    bindings: BindingStore = Depends(get_binding_store),
    subjects: SubjectStore = Depends(get_subject_store),
    runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
) -> JSONResponse:
    origin = VerifiedOrigin.from_request(request)
    if origin is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "temporarily_unavailable",
                "error_description": "Canonical browser host is not configured",
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    try:
        result = exchange_delegated_token(
            origin=origin,
            req=TokenGrantRequest(
                grant_type=grant_type,
                authorization_header=request.headers.get("Authorization"),
                client_id=client_id,
                client_secret=client_secret,
                client_assertion_type=client_assertion_type,
                client_assertion=client_assertion,
                assertion=assertion,
                subject_token=subject_token,
                resource=resource,
                scope=scope,
            ),
            http=http,
            clients=clients,
            providers=providers,
            users=users,
            roles=roles,
            bindings=bindings,
            subjects=subjects,
            runtime=runtime,
        )
    except OAuthTokenError as exc:
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        if exc.http_status == 401:
            headers["WWW-Authenticate"] = 'Basic realm="refraq-oauth"'
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": exc.error, "error_description": exc.description},
            headers=headers,
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "access_token": result.access_token,
            "token_type": result.token_type,
            "issued_token_type": result.issued_token_type,
            "expires_in": result.expires_in,
            "scope": result.scope,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.get("/oauth-clients", response_model=OAuthClientList)
def list_oauth_clients(
    q: str | None = Query(default=None),
    provider_id: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    _caller: UserRecord = Depends(require_permission("oauth_client:read")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
) -> OAuthClientList:
    items, total = store.list_page(
        limit=page.limit,
        offset=page.offset,
        q=q,
        provider_id=provider_id,
        enabled=enabled,
    )
    return OAuthClientList(
        items=[_client_out(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/oauth-clients",
    response_model=OAuthClientSecretResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_oauth_client_route(
    payload: OAuthClientCreateIn,
    request: Request,
    caller: UserRecord = Depends(require_permission("oauth_client:write")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
    providers: ProviderStore = Depends(get_provider_store),
) -> OAuthClientSecretResponse:
    record, plaintext = create_oauth_client(
        name=payload.name,
        description=payload.description,
        provider_id=payload.provider_id,
        enabled=payload.enabled,
        token_endpoint_auth_method=payload.token_endpoint_auth_method,
        jwks=payload.jwks,
        jwks_uri=payload.jwks_uri,
        allowed_grant_types=payload.allowed_grant_types,
        allowed_subject_audiences=payload.allowed_subject_audiences,
        allowed_surfaces=payload.allowed_surfaces,
        allowed_scopes=payload.allowed_scopes,
        token_ttl_sec=payload.token_ttl_sec,
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        store=store,
        providers=providers,
    )
    return OAuthClientSecretResponse(
        oauth_client=_client_out(record),
        client_secret=plaintext,
    )


@router.get("/oauth-clients/{record_id}", response_model=OAuthClientResponse)
def get_oauth_client_route(
    record_id: str,
    _caller: UserRecord = Depends(require_permission("oauth_client:read")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
) -> OAuthClientResponse:
    record = store.get_by_id(record_id)
    if record is None:
        raise OAuthClientNotFound()
    return OAuthClientResponse(oauth_client=_client_out(record))


@router.patch("/oauth-clients/{record_id}", response_model=OAuthClientResponse)
def patch_oauth_client_route(
    record_id: str,
    payload: OAuthClientPatchIn,
    request: Request,
    caller: UserRecord = Depends(require_permission("oauth_client:write")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
    runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
) -> OAuthClientResponse:
    updated = update_oauth_client(
        record_id=record_id,
        patch=payload.model_dump(exclude_unset=True),
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        store=store,
        runtime=runtime,
    )
    return OAuthClientResponse(oauth_client=_client_out(updated))


@router.post(
    "/oauth-clients/{record_id}/rotate-secret",
    response_model=OAuthClientSecretResponse,
)
def rotate_oauth_client_secret_route(
    record_id: str,
    request: Request,
    caller: UserRecord = Depends(require_permission("oauth_client:write")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
) -> OAuthClientSecretResponse:
    updated, plaintext = rotate_oauth_client_secret(
        record_id=record_id,
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        store=store,
    )
    return OAuthClientSecretResponse(
        oauth_client=_client_out(updated),
        client_secret=plaintext,
    )


@router.delete(
    "/oauth-clients/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_oauth_client_route(
    record_id: str,
    request: Request,
    caller: UserRecord = Depends(require_permission("oauth_client:write")),
    store: OAuthClientStore = Depends(get_oauth_client_store),
    runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
) -> None:
    delete_oauth_client(
        record_id=record_id,
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        store=store,
        runtime=runtime,
    )
