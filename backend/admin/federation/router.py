"""Federated authentication HTTP adapters."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.admin.audit import persist_audit_event
from backend.admin.deps import (
    SESSION_COOKIE_NAME,
    browser_facing_https,
    get_actor_token_id,
    require_permission,
    session_cookie_attrs,
)
from backend.admin.errors import AuthAccountDisabled, AuthConsoleAccessRequired
from backend.admin.federation.binding_store import BindingStore, get_binding_store
from backend.admin.federation.config import protocol_spec
from backend.admin.federation.errors import (
    ProviderNotFound,
    SsoAssertionRejected,
    SsoHandoffInvalid,
    SsoNotAdmitted,
    SsoProviderUnavailable,
)
from backend.admin.federation.handoff_store import (
    HANDOFF_COOKIE_NAME,
    HANDOFF_TTL_SECONDS,
    get_handoff_store,
)
from backend.admin.federation.pending_store import PendingStore, get_pending_store
from backend.admin.federation.provider_store import ProviderStore, get_provider_store
from backend.admin.federation.protocols.oidc.discovery import discover
from backend.admin.federation.schemas import (
    ClaimPendingIn,
    ClaimPendingResponse,
    PendingList,
    PendingOut,
    ProviderCreateIn,
    ProviderDeleteResponse,
    ProviderList,
    ProviderOut,
    ProviderPatchIn,
    ProviderResponse,
    ProviderSpecResponse,
    ProviderTestResponse,
    PublicProviderList,
    PublicProviderOut,
    UnfederateIn,
    UnfederateResponse,
)
from backend.admin.federation.service import (
    audit_sso_reject,
    claim_pending,
    complete_sso,
    create_provider,
    delete_provider,
    patch_provider,
    safe_from,
    start_sso,
    unfederate_user,
)
from backend.admin.federation.spec import ProviderRecord
from backend.admin.parameters import admin_session_ttl_hours
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.user_payload import build_user_summary
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.browser_host import canonical_browser_host
from backend.core.config import get_settings
from backend.core.pagination import PageParams, page_params

router = APIRouter(tags=["federation"])


def _browser_origin(request: Request) -> str | None:
    host = canonical_browser_host(
        configured=get_settings().refraq_browser_facing_host,
        forwarded_host=request.headers.get("x-forwarded-host"),
        request_host=request.headers.get("host") or request.url.netloc,
    )
    if host is None:
        return None
    proto = "https" if browser_facing_https(request) else "http"
    return f"{proto}://{host}"


def _callback_uri(request: Request, provider_id: str) -> str | None:
    origin = _browser_origin(request)
    if origin is None:
        return None
    return f"{origin}/api/auth/sso/{provider_id}/callback"


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?{urlencode({'error': code})}", status_code=302)


def _provider_out(item: ProviderRecord, bound_user_count: int) -> ProviderOut:
    config = item.config
    return ProviderOut(
        id=item.id,
        protocol=item.protocol,
        display_name=item.display_name,
        issuer=item.issuer,
        enabled=item.enabled,
        auto_provision=config.auto_provision,
        group_claim=config.group_claim,
        group_allowlist=list(config.group_allowlist),
        default_role_id=config.default_role_id,
        scopes=list(config.scopes),
        client_id=config.client_id,
        client_secret_configured=bool(config.client_secret),
        bound_user_count=bound_user_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/auth/providers", response_model=PublicProviderList)
def public_providers(
    store: ProviderStore = Depends(get_provider_store),
) -> PublicProviderList:
    items, _total = store.list_providers(enabled_only=True, limit=None, offset=0)
    return PublicProviderList(
        items=[
            PublicProviderOut(
                id=item.id, display_name=item.display_name, protocol=item.protocol
            )
            for item in items
        ]
    )


@router.get("/auth/sso/{provider_id}/start")
def start_login(
    provider_id: str,
    request: Request,
    from_: str | None = Query(default=None, alias="from"),
    store: ProviderStore = Depends(get_provider_store),
) -> RedirectResponse:
    item = store.get(provider_id)
    if item is None or not item.enabled:
        audit_sso_reject(provider_id=provider_id, reason="provider_unavailable")
        return _login_error("AUTH_SSO_PROVIDER_UNAVAILABLE")
    callback = _callback_uri(request, provider_id)
    if callback is None:
        audit_sso_reject(provider_id=provider_id, reason="callback_origin_invalid")
        return _login_error("AUTH_SSO_PROVIDER_UNAVAILABLE")
    try:
        url, handoff = start_sso(item, callback, from_ or "/")
    except SsoProviderUnavailable:
        audit_sso_reject(provider_id=provider_id, reason="provider_unavailable")
        return _login_error("AUTH_SSO_PROVIDER_UNAVAILABLE")
    except SsoAssertionRejected as exc:
        audit_sso_reject(
            provider_id=provider_id,
            reason="assertion_rejected",
            cause=exc.message,
        )
        return _login_error("AUTH_SSO_ASSERTION_REJECTED")
    redirect = RedirectResponse(url, status_code=302)
    redirect.set_cookie(
        HANDOFF_COOKIE_NAME,
        handoff.state,
        max_age=HANDOFF_TTL_SECONDS,
        **session_cookie_attrs(request),
    )
    return redirect


@router.get("/auth/sso/{provider_id}/callback")
def callback(
    provider_id: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    iss: str | None = None,
    refraq_sso: str | None = Cookie(default=None, alias=HANDOFF_COOKIE_NAME),
    store: ProviderStore = Depends(get_provider_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    bindings: BindingStore = Depends(get_binding_store),
    pending: PendingStore = Depends(get_pending_store),
) -> Response:
    def _clear(target: RedirectResponse) -> RedirectResponse:
        target.delete_cookie(HANDOFF_COOKIE_NAME, **session_cookie_attrs(request))
        return target

    if not state or not code or not refraq_sso or refraq_sso != state:
        audit_sso_reject(provider_id=provider_id, reason="handoff_invalid")
        return _clear(_login_error("AUTH_SSO_HANDOFF_INVALID"))
    handoff = get_handoff_store().pop(state)
    if handoff is None or handoff.provider_id != provider_id:
        audit_sso_reject(provider_id=provider_id, reason="handoff_invalid")
        return _clear(_login_error("AUTH_SSO_HANDOFF_INVALID"))
    item = store.get(provider_id)
    if item is None or not item.enabled:
        audit_sso_reject(provider_id=provider_id, reason="provider_unavailable")
        return _clear(_login_error("AUTH_SSO_PROVIDER_UNAVAILABLE"))
    try:
        user = complete_sso(
            provider=item,
            handoff=handoff,
            code=code,
            response_iss=iss,
            users=users,
            roles=roles,
            bindings=bindings,
            pending=pending,
        )
    except SsoNotAdmitted:
        return _clear(_login_error("AUTH_SSO_NOT_ADMITTED"))
    except SsoHandoffInvalid:
        audit_sso_reject(provider_id=provider_id, reason="handoff_invalid")
        return _clear(_login_error("AUTH_SSO_HANDOFF_INVALID"))
    except SsoProviderUnavailable:
        audit_sso_reject(provider_id=provider_id, reason="provider_unavailable")
        return _clear(_login_error("AUTH_SSO_PROVIDER_UNAVAILABLE"))
    except SsoAssertionRejected as exc:
        audit_sso_reject(
            provider_id=provider_id,
            reason="assertion_rejected",
            cause=exc.message,
        )
        return _clear(_login_error("AUTH_SSO_ASSERTION_REJECTED"))
    except (AuthAccountDisabled, AuthConsoleAccessRequired) as exc:
        return _clear(_login_error(exc.code))
    ttl_seconds = admin_session_ttl_hours() * 3600
    sid = sessions.create(user.id, ttl_seconds)
    redirect = RedirectResponse(url=safe_from(handoff.return_to), status_code=302)
    redirect.delete_cookie(HANDOFF_COOKIE_NAME, **session_cookie_attrs(request))
    redirect.set_cookie(
        SESSION_COOKIE_NAME,
        sid,
        max_age=ttl_seconds,
        **session_cookie_attrs(request),
    )
    return redirect


@router.get("/identity-providers/spec", response_model=ProviderSpecResponse)
def provider_protocol_spec(
    protocol: str = "oidc",
    _caller: UserRecord = Depends(require_permission("identity_providers:read")),
) -> ProviderSpecResponse:
    return ProviderSpecResponse(protocol="oidc", spec=protocol_spec(protocol))


@router.get("/identity-providers", response_model=ProviderList)
def list_providers(
    _caller: UserRecord = Depends(require_permission("identity_providers:read")),
    store: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> ProviderList:
    records, total = store.list_providers(limit=page.limit, offset=page.offset)
    items = [
        _provider_out(item, len(bindings.list_for_issuer(item.issuer))) for item in records
    ]
    return ProviderList(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/identity-providers", response_model=ProviderResponse)
def create(
    payload: ProviderCreateIn,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    store: ProviderStore = Depends(get_provider_store),
    roles: RoleStore = Depends(get_role_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ProviderResponse:
    item = create_provider(
        store=store,
        roles=roles,
        protocol=payload.protocol,
        display_name=payload.display_name,
        enabled=payload.enabled,
        config_data=payload.config_payload(),
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return ProviderResponse(provider=_provider_out(item, 0))


@router.get("/identity-providers/{provider_id}", response_model=ProviderResponse)
def get_provider(
    provider_id: str,
    _caller: UserRecord = Depends(require_permission("identity_providers:read")),
    store: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
) -> ProviderResponse:
    item = store.get(provider_id)
    if item is None:
        raise ProviderNotFound()
    return ProviderResponse(
        provider=_provider_out(item, len(bindings.list_for_issuer(item.issuer)))
    )


@router.patch("/identity-providers/{provider_id}", response_model=ProviderResponse)
def update_provider(
    provider_id: str,
    payload: ProviderPatchIn,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    store: ProviderStore = Depends(get_provider_store),
    roles: RoleStore = Depends(get_role_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    sessions: SessionStore = Depends(get_session_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
    disable_bound_users: bool = False,
) -> ProviderResponse:
    item = patch_provider(
        store=store,
        roles=roles,
        provider_id=provider_id,
        display_name=payload.display_name,
        enabled=payload.enabled,
        config_data=payload.config_payload() or None,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
        disable_bound_users=disable_bound_users,
        bindings=bindings,
        users=users,
        sessions=sessions,
    )
    return ProviderResponse(
        provider=_provider_out(item, len(bindings.list_for_issuer(item.issuer)))
    )


@router.post("/identity-providers/{provider_id}/test", response_model=ProviderTestResponse)
def test_provider(
    provider_id: str,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    store: ProviderStore = Depends(get_provider_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ProviderTestResponse:
    item = store.get(provider_id)
    if item is None:
        raise ProviderNotFound()
    metadata = discover(item)
    persist_audit_event(
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
        resource_type="identity_provider",
        resource_id=provider_id,
        action="test",
        result="success",
    )
    return ProviderTestResponse(
        issuer=metadata.issuer,
        authorization_endpoint=metadata.authorization_endpoint,
        token_endpoint=metadata.token_endpoint,
        jwks_uri=metadata.jwks_uri,
        authorization_response_iss_parameter_supported=(
            metadata.authorization_response_iss_parameter_supported
        ),
        group_claim=item.config.group_claim,
    )


@router.delete("/identity-providers/{provider_id}", response_model=ProviderDeleteResponse)
def remove_provider(
    provider_id: str,
    disable_bound_users: bool = False,
    caller: UserRecord = Depends(require_permission("identity_providers:write")),
    store: ProviderStore = Depends(get_provider_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    sessions: SessionStore = Depends(get_session_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ProviderDeleteResponse:
    count = delete_provider(
        store=store,
        bindings=bindings,
        users=users,
        sessions=sessions,
        provider_id=provider_id,
        disable_bound_users=disable_bound_users,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return ProviderDeleteResponse(bound_user_count=count)


@router.get("/users/pending-federated-identities", response_model=PendingList)
def list_pending(
    _caller: UserRecord = Depends(require_permission("users:write")),
    pending: PendingStore = Depends(get_pending_store),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> PendingList:
    records, total = pending.list_pending(limit=page.limit, offset=page.offset)
    items = [
        PendingOut(
            id=item.id,
            issuer=item.issuer,
            subject=item.subject,
            provider_id=item.provider_id,
            account_hint=item.account_hint,
            email=item.email,
            display_name=item.display_name,
            groups=list(item.groups),
            admission_reason=item.admission_reason,
            attempt_count=item.attempt_count,
            first_seen_at=item.first_seen_at,
            last_attempt_at=item.last_attempt_at,
            expires_at=item.expires_at,
        )
        for item in records
    ]
    return PendingList(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/users/pending-federated-identities/{pending_id}/claim",
    response_model=ClaimPendingResponse,
)
def claim(
    pending_id: str,
    payload: ClaimPendingIn,
    caller: UserRecord = Depends(require_permission("users:write")),
    pending: PendingStore = Depends(get_pending_store),
    bindings: BindingStore = Depends(get_binding_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ClaimPendingResponse:
    created = payload.create_user
    user = claim_pending(
        pending_id=pending_id,
        user_id=payload.user_id,
        create_account=created.account if created else None,
        create_display_name=created.display_name if created else None,
        create_email=created.email if created else None,
        create_role_id=created.role_id if created else None,
        pending=pending,
        bindings=bindings,
        users=users,
        roles=roles,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return ClaimPendingResponse(user=build_user_summary(user, roles))


@router.post("/users/{user_id}/unfederate", response_model=UnfederateResponse)
def unfederate(
    user_id: str,
    payload: UnfederateIn,
    caller: UserRecord = Depends(require_permission("users:write")),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    bindings: BindingStore = Depends(get_binding_store),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> UnfederateResponse:
    user = unfederate_user(
        user_id=user_id,
        password=payload.password,
        users=users,
        bindings=bindings,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return UnfederateResponse(user=build_user_summary(user, roles))
