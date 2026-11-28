"""SCIM 2.0 Service Provider routes and per-provider SCIM token admin routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.federation.binding_store import BindingStore, get_binding_store
from backend.admin.federation.errors import ProviderNotFound
from backend.admin.federation.provider_store import ProviderStore, get_provider_store
from backend.admin.oauth.runtime_store import (
    OAuthRuntimeStore,
    get_oauth_runtime_store,
)
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.scim.errors import SCIM_CONTENT_TYPE, ScimError, ScimTokenNotFound
from backend.admin.scim.schemas import (
    ScimTokenCreateIn,
    ScimTokenCreateResponse,
    ScimTokenListResponse,
    ScimTokenOut,
)
from backend.admin.scim.service import (
    authenticate_scim_bearer,
    create_scim_group,
    create_scim_user,
    delete_scim_group,
    delete_scim_user,
    get_scim_group,
    get_scim_user,
    list_scim_groups,
    list_scim_users,
    patch_scim_group,
    patch_scim_user,
    replace_scim_group,
    replace_scim_user,
    resource_types,
    schemas_list,
    service_provider_config,
)
from backend.admin.scim.store import ScimStore, ScimTokenRecord, get_scim_store
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.subjects.store import SubjectStore, get_subject_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store

router = APIRouter(tags=["scim"])


def _scim_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type=SCIM_CONTENT_TYPE,
    )


def _token_out(record: ScimTokenRecord) -> ScimTokenOut:
    return ScimTokenOut(
        id=record.id,
        provider_id=record.provider_id,
        name=record.name,
        prefix=record.prefix,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


# --- Per-Identity-Provider SCIM Token Admin ---


@router.get(
    "/identity-providers/{provider_id}/scim-tokens",
    response_model=ScimTokenListResponse,
)
def list_provider_scim_tokens(
    provider_id: str,
    _caller: UserRecord = Depends(require_permission("identity_providers:read")),
    providers: ProviderStore = Depends(get_provider_store),
    store: ScimStore = Depends(get_scim_store),
) -> ScimTokenListResponse:
    if providers.get(provider_id) is None:
        raise ProviderNotFound()
    items = store.list_tokens(provider_id)
    return ScimTokenListResponse(items=[_token_out(item) for item in items])


@router.post(
    "/identity-providers/{provider_id}/scim-tokens",
    response_model=ScimTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_provider_scim_token(
    provider_id: str,
    payload: ScimTokenCreateIn,
    request: Request,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    providers: ProviderStore = Depends(get_provider_store),
    store: ScimStore = Depends(get_scim_store),
) -> ScimTokenCreateResponse:
    if providers.get(provider_id) is None:
        raise ProviderNotFound()
    record, plaintext = store.create_token(provider_id, payload.name.strip())
    persist_audit_event(
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="scim_token",
        resource_id=record.id,
        action="create",
        result="success",
        detail={"provider_id": provider_id, "prefix": record.prefix},
    )
    return ScimTokenCreateResponse(scim_token=_token_out(record), token=plaintext)


@router.delete(
    "/identity-providers/{provider_id}/scim-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_provider_scim_token(
    provider_id: str,
    token_id: str,
    request: Request,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    providers: ProviderStore = Depends(get_provider_store),
    store: ScimStore = Depends(get_scim_store),
) -> None:
    if providers.get(provider_id) is None:
        raise ProviderNotFound()
    revoked = store.revoke_token(provider_id, token_id)
    if revoked is None:
        raise ScimTokenNotFound()
    persist_audit_event(
        actor_user_id=caller.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="scim_token",
        resource_id=token_id,
        action="revoke",
        result="success",
        detail={"provider_id": provider_id},
    )


# --- SCIM 2.0 Service Provider ---


@router.get("/scim/v2/ServiceProviderConfig")
def scim_service_provider_config(
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
) -> JSONResponse:
    try:
        authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(service_provider_config())
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/ResourceTypes")
def scim_resource_types(
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
) -> JSONResponse:
    try:
        authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(resource_types())
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/Schemas")
def scim_schemas(
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
) -> JSONResponse:
    try:
        authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(schemas_list())
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/Users")
def scim_list_users_route(
    request: Request,
    filter_expr: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=0, le=200),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            list_scim_users(
                principal,
                filter_expr=filter_expr,
                start_index=start_index,
                count=count,
                bindings=bindings,
                users=users,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.post("/scim/v2/Users")
def scim_create_user_route(
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    oauth_runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            create_scim_user(
                principal,
                payload,
                bindings=bindings,
                users=users,
                roles=roles,
                sessions=sessions,
                oauth_runtime=oauth_runtime,
                subjects=subjects,
            ),
            status_code=201,
        )
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/Users/{user_id}")
def scim_get_user_route(
    user_id: str,
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            get_scim_user(
                principal,
                user_id,
                bindings=bindings,
                users=users,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.put("/scim/v2/Users/{user_id}")
def scim_put_user_route(
    user_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    oauth_runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            replace_scim_user(
                principal,
                user_id,
                payload,
                bindings=bindings,
                users=users,
                roles=roles,
                sessions=sessions,
                oauth_runtime=oauth_runtime,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.patch("/scim/v2/Users/{user_id}")
def scim_patch_user_route(
    user_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    oauth_runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            patch_scim_user(
                principal,
                user_id,
                payload,
                bindings=bindings,
                users=users,
                roles=roles,
                sessions=sessions,
                oauth_runtime=oauth_runtime,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.delete("/scim/v2/Users/{user_id}")
def scim_delete_user_route(
    user_id: str,
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    oauth_runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
) -> Response:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        delete_scim_user(
            principal,
            user_id,
            bindings=bindings,
            users=users,
            roles=roles,
            sessions=sessions,
            oauth_runtime=oauth_runtime,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/Groups")
def scim_list_groups_route(
    request: Request,
    filter_expr: str | None = Query(default=None, alias="filter"),
    start_index: int = Query(default=1, alias="startIndex", ge=1),
    count: int = Query(default=100, ge=0, le=200),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            list_scim_groups(
                principal,
                filter_expr=filter_expr,
                start_index=start_index,
                count=count,
                scim_store=scim_store,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.post("/scim/v2/Groups")
def scim_create_group_route(
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            create_scim_group(
                principal,
                payload,
                scim_store=scim_store,
                bindings=bindings,
                subjects=subjects,
            ),
            status_code=201,
        )
    except ScimError as exc:
        return exc.to_response()


@router.get("/scim/v2/Groups/{group_id}")
def scim_get_group_route(
    group_id: str,
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            get_scim_group(
                principal,
                group_id,
                scim_store=scim_store,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.put("/scim/v2/Groups/{group_id}")
def scim_put_group_route(
    group_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            replace_scim_group(
                principal,
                group_id,
                payload,
                scim_store=scim_store,
                bindings=bindings,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.patch("/scim/v2/Groups/{group_id}")
def scim_patch_group_route(
    group_id: str,
    request: Request,
    payload: dict[str, Any] = Body(...),
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> JSONResponse:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        return _scim_json(
            patch_scim_group(
                principal,
                group_id,
                payload,
                scim_store=scim_store,
                bindings=bindings,
                subjects=subjects,
            )
        )
    except ScimError as exc:
        return exc.to_response()


@router.delete("/scim/v2/Groups/{group_id}")
def scim_delete_group_route(
    group_id: str,
    request: Request,
    scim_store: ScimStore = Depends(get_scim_store),
    providers: ProviderStore = Depends(get_provider_store),
    subjects: SubjectStore = Depends(get_subject_store),
) -> Response:
    try:
        principal = authenticate_scim_bearer(
            request.headers.get("Authorization"),
            scim_store=scim_store,
            providers=providers,
        )
        delete_scim_group(
            principal,
            group_id,
            scim_store=scim_store,
            subjects=subjects,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ScimError as exc:
        return exc.to_response()
