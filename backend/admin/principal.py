"""Sealed immutable Principal, VerifiedOrigin, ResourceSurface, and cross-thread admission."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeVar

from fastapi import Request
from starlette.types import Scope

from backend.admin.errors import AuthForbidden, AuthPatInvalid, AuthUnauthenticated
from backend.admin.federation.binding_store import BindingStore, get_binding_store
from backend.admin.oauth.runtime_store import (
    DELEGATED_TOKEN_PREFIX,
    OAuthRuntimeStore,
    get_oauth_runtime_store,
)
from backend.admin.permissions import ALL_PERMISSIONS, Permission
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.roles import effective_permissions
from backend.admin.token_store import TokenStore, get_token_store, hash_token
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.admission import await_admitted
from backend.core.browser_host import canonical_browser_host
from backend.core.config import get_settings
from backend.core.request_id import bind_request_id, get_request_id
from backend.core.time import utc_now

T = TypeVar("T")

CredentialKind = Literal["session", "pat", "oauth_delegated"]

_METADATA_MCP_CEILING: frozenset[str] = frozenset(
    {"sources:read", "metadata:read", "metadata:write", "query:run"}
)
_ENTITY_MCP_CEILING: frozenset[str] = frozenset({"entity:data_read"})


class ResourceSurface(str, Enum):
    API = "api"
    METADATA_MCP = "metadata_mcp"
    ENTITY_MCP = "entity_mcp"

    @property
    def path(self) -> str:
        if self is ResourceSurface.ENTITY_MCP:
            return "/mcp/entity"
        if self is ResourceSurface.METADATA_MCP:
            return "/mcp"
        return "/api"

    @property
    def surface_path(self) -> str:
        return self.path.lstrip("/")

    @property
    def ceiling(self) -> frozenset[str]:
        if self is ResourceSurface.ENTITY_MCP:
            return _ENTITY_MCP_CEILING
        if self is ResourceSurface.METADATA_MCP:
            return _METADATA_MCP_CEILING
        return frozenset(ALL_PERMISSIONS)

    @property
    def advertised_scopes(self) -> tuple[str, ...]:
        if self is ResourceSurface.ENTITY_MCP:
            return ("entity:data_read",)
        if self is ResourceSurface.METADATA_MCP:
            return ("sources:read", "metadata:read", "metadata:write", "query:run")
        return tuple(
            perm for perm in ALL_PERMISSIONS if perm != "console:access"
        )


@dataclass(frozen=True, slots=True)
class VerifiedOrigin:
    """Trusted browser-facing {proto}://{host} origin."""

    proto: str
    host: str

    @property
    def base_url(self) -> str:
        return f"{self.proto}://{self.host}"

    def oauth_issuer(self) -> str:
        return f"{self.base_url}/api/oauth"

    def oauth_token_endpoint(self) -> str:
        return f"{self.base_url}/api/oauth/token"

    def resource_uri(self, surface: ResourceSurface) -> str:
        return f"{self.base_url}{surface.path}"

    def protected_resource_metadata_uri(self, surface: ResourceSurface) -> str:
        return f"{self.base_url}/.well-known/oauth-protected-resource/{surface.surface_path}"

    def match_resource_uri(self, uri: str) -> ResourceSurface | None:
        cleaned = uri.strip().rstrip("/")
        for surface in ResourceSurface:
            if cleaned == self.resource_uri(surface):
                return surface
        return None

    @classmethod
    def from_parts(
        cls,
        *,
        forwarded_proto: str | None,
        scheme: str | None,
        forwarded_host: str | None,
        request_host: str | None,
    ) -> "VerifiedOrigin | None":
        settings = get_settings()
        host = canonical_browser_host(
            configured=settings.refraq_browser_facing_host,
            forwarded_host=forwarded_host,
            request_host=request_host,
        )
        if not host:
            return None
        proto = "http"
        if forwarded_proto:
            first = forwarded_proto.split(",")[0].strip().lower()
            if first in {"http", "https"}:
                proto = first
        elif scheme in {"http", "https"}:
            proto = scheme
        return cls(proto=proto, host=host)

    @classmethod
    def from_request(cls, request: Request) -> "VerifiedOrigin | None":
        return cls.from_parts(
            forwarded_proto=request.headers.get("x-forwarded-proto"),
            scheme=request.url.scheme,
            forwarded_host=request.headers.get("x-forwarded-host"),
            request_host=request.headers.get("host"),
        )

    @classmethod
    def from_asgi_scope(cls, scope: Scope) -> "VerifiedOrigin | None":
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        return cls.from_parts(
            forwarded_proto=headers.get("x-forwarded-proto"),
            scheme=str(scope.get("scheme") or "http"),
            forwarded_host=headers.get("x-forwarded-host"),
            request_host=headers.get("host"),
        )


@dataclass(frozen=True, slots=True)
class Principal:
    """Sealed authenticated caller with pre-intersected effective permissions."""

    user: UserRecord
    surface: ResourceSurface
    credential_kind: CredentialKind
    actor_token_id: str | None
    effective_permissions: frozenset[str]
    client_id: str | None = None

    @property
    def user_id(self) -> str:
        return self.user.id

    def has(self, permission: Permission | str) -> bool:
        return permission in self.effective_permissions

    def require(self, *permissions: Permission | str) -> None:
        for perm in permissions:
            if perm not in self.effective_permissions:
                raise AuthForbidden(f"Missing permission {perm}")

    async def admit(self, fn: Callable[[], T]) -> T:
        """Run blocking work through PeekBulkhead while carrying Principal and request_id."""
        request_id = get_request_id()

        def _wrapped() -> T:
            with principal_context(self), bind_request_id(request_id):
                return fn()

        return await await_admitted(self.user.id, _wrapped)


_current_principal: ContextVar[Principal | None] = ContextVar(
    "refraq_current_principal", default=None
)


def current_principal() -> Principal | None:
    return _current_principal.get()


def require_current_principal() -> Principal:
    principal = _current_principal.get()
    if principal is None:
        raise AuthUnauthenticated()
    return principal


def current_actor_token_id() -> str | None:
    principal = _current_principal.get()
    return principal.actor_token_id if principal is not None else None


@contextmanager
def principal_context(principal: Principal | None) -> Iterator[None]:
    token = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)


def _role_permissions(user: UserRecord, roles: RoleStore) -> frozenset[str]:
    if not user.role_id:
        return frozenset()
    role = roles.get_by_id(user.role_id)
    if role is None:
        return frozenset()
    return frozenset(effective_permissions(role))


def _is_scim_deprovisioned(user_id: str, bindings: BindingStore) -> bool:
    binding = bindings.get_for_user(user_id)
    return binding is not None and binding.scim_deprovisioned_at is not None


def resolve_session_principal(
    user: UserRecord,
    *,
    surface: ResourceSurface = ResourceSurface.API,
    roles: RoleStore,
) -> Principal:
    perms = _role_permissions(user, roles) & surface.ceiling
    return Principal(
        user=user,
        surface=surface,
        credential_kind="session",
        actor_token_id=None,
        effective_permissions=perms,
    )


def resolve_bearer_principal(
    authorization: str | None,
    *,
    surface: ResourceSurface,
    tokens: TokenStore,
    users: UserStore,
    roles: RoleStore,
    runtime: OAuthRuntimeStore,
    bindings: BindingStore,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    secret = authorization[7:].strip()
    if not secret:
        raise AuthPatInvalid()

    if secret.startswith(DELEGATED_TOKEN_PREFIX):
        record = runtime.resolve_token(secret)
        if record is None or surface.value not in record.surfaces:
            raise AuthPatInvalid()
        user = users.get_by_id(record.user_id)
        if user is None or user.status != "active":
            raise AuthPatInvalid()
        if _is_scim_deprovisioned(user.id, bindings):
            raise AuthPatInvalid()
        role_perms = _role_permissions(user, roles)
        eff = (role_perms & frozenset(record.scopes) & surface.ceiling) - {
            "console:access"
        }
        return Principal(
            user=user,
            surface=surface,
            credential_kind="oauth_delegated",
            actor_token_id=record.token_id,
            effective_permissions=eff,
            client_id=record.client_id,
        )

    pat = tokens.get_by_hash(hash_token(secret))
    now = utc_now()
    if (
        pat is None
        or pat.revoked_at is not None
        or pat.deleted_at is not None
        or (pat.expires_at is not None and pat.expires_at <= now)
    ):
        raise AuthPatInvalid()
    user = users.get_by_id(pat.user_id)
    if user is None or user.status != "active":
        raise AuthPatInvalid()
    if _is_scim_deprovisioned(user.id, bindings):
        raise AuthPatInvalid()
    tokens.touch_last_used(pat.id, now)
    eff = _role_permissions(user, roles) & surface.ceiling
    return Principal(
        user=user,
        surface=surface,
        credential_kind="pat",
        actor_token_id=pat.id,
        effective_permissions=eff,
    )


@contextmanager
def mcp_authorization(
    authorization: str | None,
    *,
    surface: ResourceSurface = ResourceSurface.API,
) -> Iterator[Principal]:
    """Bind a resolved Bearer Principal for stdio/test MCP invocations."""
    principal = resolve_bearer_principal(
        authorization,
        surface=surface,
        tokens=get_token_store(),
        users=get_user_store(),
        roles=get_role_store(),
        runtime=get_oauth_runtime_store(),
        bindings=get_binding_store(),
    )
    with principal_context(principal):
        yield principal
