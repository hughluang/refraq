"""Shared ASGI gate for MCP protected resource surfaces (/mcp and /mcp/entity)."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.admin.errors import AuthPatInvalid, AuthUnauthenticated
from backend.admin.federation.binding_store import get_binding_store
from backend.admin.oauth.runtime_store import get_oauth_runtime_store
from backend.admin.principal import (
    ResourceSurface,
    VerifiedOrigin,
    principal_context,
    resolve_bearer_principal,
)
from backend.admin.role_store import get_role_store
from backend.admin.token_store import get_token_store
from backend.admin.user_store import get_user_store
from backend.core.errors import CODE_HTTP_METHOD_NOT_ALLOWED, problem_response


def _www_authenticate(
    scope: Scope,
    surface: ResourceSurface,
    *,
    has_authorization: bool,
) -> str:
    params: list[str] = []
    origin = VerifiedOrigin.from_asgi_scope(scope)
    if origin is not None:
        metadata_url = origin.protected_resource_metadata_uri(surface)
        params.append(f'resource_metadata="{metadata_url}"')
    scopes = " ".join(surface.advertised_scopes)
    params.append(f'scope="{scopes}"')
    if has_authorization:
        params.append('error="invalid_token"')
    return "Bearer " + ", ".join(params)


class McpResourceGate:
    """Require Bearer PAT or surface-bound Delegated Access Token, then accept POST only."""

    def __init__(self, app: ASGIApp, *, surface: ResourceSurface) -> None:
        self.app = app
        self.surface = surface

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        prefix = self.surface.path
        if path != prefix and not path.startswith(prefix + "/"):
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        auth_header = headers.get("authorization")
        try:
            principal = resolve_bearer_principal(
                auth_header,
                surface=self.surface,
                tokens=get_token_store(),
                users=get_user_store(),
                roles=get_role_store(),
                runtime=get_oauth_runtime_store(),
                bindings=get_binding_store(),
            )
        except (AuthUnauthenticated, AuthPatInvalid) as exc:
            challenge = _www_authenticate(
                scope,
                self.surface,
                has_authorization=bool(auth_header),
            )
            response = problem_response(
                status=401,
                code=AuthUnauthenticated.code,
                detail=exc.message,
                headers={"WWW-Authenticate": challenge},
            )
            await response(scope, receive, send)
            return

        if scope.get("method") != "POST":
            response = problem_response(
                status=405,
                code=CODE_HTTP_METHOD_NOT_ALLOWED,
                detail="Only POST is accepted",
                headers={"Allow": "POST"},
            )
            await response(scope, receive, send)
            return

        with principal_context(principal):
            await self.app(scope, receive, send)
