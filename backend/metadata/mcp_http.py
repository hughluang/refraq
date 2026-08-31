"""Product MCP HTTP process: Streamable HTTP, PAT Bearer only, intranet readyz."""

from __future__ import annotations

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.admin.errors import AuthUnauthenticated
from backend.core.config import get_settings
from backend.core.errors import problem_response
from backend.core.health import readyz as core_readyz
from backend.core.request_id import RequestIdMiddleware
from backend.metadata.mcp_actor import (
    actor_from_authorization_header,
    reset_mcp_actor,
    set_mcp_actor,
)
from backend.metadata.mcp_catalog import MCP_PUBLIC_PATH
from backend.metadata.mcp_server import mcp


class PatOnlyGate:
    """Require User PAT on /mcp. Ignore cookies. Do not advertise OAuth metadata."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path != MCP_PUBLIC_PATH and not path.startswith(MCP_PUBLIC_PATH + "/"):
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        try:
            user, token_id = actor_from_authorization_header(headers.get("authorization"))
        except AuthUnauthenticated as exc:
            response = problem_response(
                status=exc.http_status, code=exc.code, detail=exc.message
            )
            await response(scope, receive, send)
            return

        token = set_mcp_actor(user, token_id)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_mcp_actor(token)


async def readyz(_request: Request) -> JSONResponse:
    return core_readyz()


def _transport_security() -> TransportSecuritySettings | None:
    settings = get_settings()
    # Loopback bind keeps the SDK Host whitelist (DNS-rebinding cover for a
    # direct 127.0.0.1 client). Memory tests (Host: testserver) and compose
    # (0.0.0.0, reached only through the Console proxy) disable the check.
    if (
        settings.store_backend != "memory"
        and settings.refraq_mcp_host in ("127.0.0.1", "localhost", "::1")
    ):
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def create_mcp_http_app() -> Starlette:
    settings = get_settings()
    inner = mcp.streamable_http_app(
        streamable_http_path=MCP_PUBLIC_PATH,
        stateless_http=True,
        transport_security=_transport_security(),
        host=settings.refraq_mcp_host,
    )
    return Starlette(
        routes=[
            Route("/readyz", endpoint=readyz, methods=["GET"]),
            Mount("/", app=PatOnlyGate(inner)),
        ],
        lifespan=inner.router.lifespan_context,
        middleware=[Middleware(RequestIdMiddleware)],
    )


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_mcp_http_app(),
        host=settings.refraq_mcp_host,
        port=settings.refraq_mcp_port,
        factory=False,
    )


if __name__ == "__main__":
    main()
