"""FastAPI dependencies for auth-aware request handling."""

from __future__ import annotations

from typing import Callable, Literal, TypedDict

from fastapi import Cookie, Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.admin.errors import AuthForbidden, AuthUnauthenticated
from backend.admin.federation.binding_store import BindingStore, get_binding_store
from backend.admin.oauth.runtime_store import (
    OAuthRuntimeStore,
    get_oauth_runtime_store,
)
from backend.admin.permissions import Permission, permissions_include
from backend.admin.principal import (
    Principal,
    ResourceSurface,
    resolve_bearer_principal,
    resolve_session_principal,
)
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.roles import effective_permissions
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.token_store import TokenStore, get_token_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store

SESSION_COOKIE_NAME = "refraq_sid"


class SessionCookieAttrs(TypedDict):
    path: str
    httponly: bool
    samesite: Literal["lax"]
    secure: bool


def browser_facing_https(request: Request) -> bool:
    """Whether the Management Console request that carries this cookie was HTTPS.

    Self-deploy rewrites `/api` through Next.js, so the API process often sees
    HTTP to the internal service. Honor `X-Forwarded-Proto` stamped by the
    Console proxy (first value), then the request URL scheme. The proxy
    overwrites client-supplied values; `REFRAQ_ENV` does not decide this.
    HTTP self-deploy must keep the Session.
    """
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded is not None:
        first = forwarded.split(",")[0].strip().lower()
        return first == "https"
    return request.url.scheme == "https"


def session_cookie_attrs(request: Request) -> SessionCookieAttrs:
    """Shared cookie attributes for set_cookie and delete_cookie."""
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": browser_facing_https(request),
    }


def resolve_user_permissions(
    user: UserRecord, roles: RoleStore
) -> list[str]:
    if not user.role_id:
        return []
    role = roles.get_by_id(user.role_id)
    if role is None:
        return []
    return effective_permissions(role)


def _principal_from_session(
    *,
    request: Request,
    refraq_sid: str | None,
    sessions: SessionStore,
    users: UserStore,
    roles: RoleStore,
) -> Principal | None:
    if not refraq_sid:
        return None
    user_id = sessions.get(refraq_sid)
    if user_id is None:
        return None
    record = users.get_by_id(user_id)
    if record is None or record.status != "active":
        return None
    principal = resolve_session_principal(
        record, surface=ResourceSurface.API, roles=roles
    )
    request.state.session_id = refraq_sid
    request.state.actor_token_id = None
    request.state.current_user = record
    request.state.principal = principal
    return principal


def get_current_principal(
    request: Request,
    refraq_sid: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    _bearer: HTTPAuthorizationCredentials | None = Security(
        HTTPBearer(
            auto_error=False,
            description=(
                "User PAT or Delegated Access Token. Paste the token secret only; "
                "Swagger sends Authorization: Bearer. Session cookie auth is unchanged."
            ),
        )
    ),
    sessions: SessionStore = Depends(get_session_store),
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    tokens: TokenStore = Depends(get_token_store),
    runtime: OAuthRuntimeStore = Depends(get_oauth_runtime_store),
    bindings: BindingStore = Depends(get_binding_store),
) -> Principal:
    """Resolve sealed Principal from Session cookie (preferred) or Bearer token."""
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached

    session_principal = _principal_from_session(
        request=request,
        refraq_sid=refraq_sid,
        sessions=sessions,
        users=users,
        roles=roles,
    )
    if session_principal is not None:
        return session_principal

    authorization = request.headers.get("Authorization")
    if authorization:
        principal = resolve_bearer_principal(
            authorization,
            surface=ResourceSurface.API,
            tokens=tokens,
            users=users,
            roles=roles,
            runtime=runtime,
            bindings=bindings,
        )
        request.state.session_id = None
        request.state.actor_token_id = principal.actor_token_id
        request.state.current_user = principal.user
        request.state.principal = principal
        return principal
    raise AuthUnauthenticated()


def get_current_user(
    principal: Principal = Depends(get_current_principal),
) -> UserRecord:
    """Resolve User from Session cookie (preferred) or Bearer token."""
    return principal.user


def require_permission(permission: Permission) -> Callable[[Principal], UserRecord]:
    def _checker(
        principal: Principal = Depends(get_current_principal),
    ) -> UserRecord:
        if not permissions_include(principal.effective_permissions, permission):
            raise AuthForbidden()
        return principal.user

    return _checker


def get_actor_token_id(request: Request) -> str | None:
    return getattr(request.state, "actor_token_id", None)
