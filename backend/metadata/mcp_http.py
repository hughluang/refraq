"""Product MCP HTTP process: Streamable HTTP, PAT Bearer only, intranet readyz."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.admin.errors import AuthUnauthenticated
from backend.core.config import get_settings
from backend.core.errors import problem_response
from backend.core.health import readyz as core_readyz
from backend.core.bulkhead import reset_peek_bulkhead
from backend.core.http_runtime import apply_http_runtime
from backend.core.load_shed import LoadSheddingMiddleware
from backend.core.metrics import metrics_response
from backend.core.request_id import RequestIdMiddleware
from backend.core.runtime import get_runtime_capacity, set_process_role
from backend.metadata.mcp_actor import (
    actor_from_authorization_header,
    reset_mcp_actor,
    set_mcp_actor,
)
from backend.metadata.mcp_catalog import MCP_PUBLIC_PATH
from backend.metadata.mcp_server import mcp
from backend.worker.parameters import assemble_system_parameters


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


async def metrics(_request: Request) -> Response:
    return metrics_response()


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
    assemble_system_parameters()
    settings = get_settings()
    inner = mcp.streamable_http_app(
        streamable_http_path=MCP_PUBLIC_PATH,
        stateless_http=True,
        transport_security=_transport_security(),
        host=settings.refraq_mcp_host,
    )
    inner_lifespan = inner.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        apply_http_runtime()
        async with inner_lifespan(inner):
            try:
                yield
            finally:
                reset_peek_bulkhead()

    return Starlette(
        routes=[
            Route("/readyz", endpoint=readyz, methods=["GET"]),
            Route("/metrics", endpoint=metrics, methods=["GET"]),
            Mount("/", app=PatOnlyGate(inner)),
        ],
        lifespan=lifespan,
        middleware=[
            Middleware(RequestIdMiddleware),
            Middleware(LoadSheddingMiddleware),
        ],
    )


def main() -> None:
    assemble_system_parameters()
    set_process_role("mcp")
    settings = get_settings()
    cap = get_runtime_capacity()
    uvicorn.run(
        create_mcp_http_app(),
        host=settings.refraq_mcp_host,
        port=settings.refraq_mcp_port,
        factory=False,
        timeout_keep_alive=cap.timeout_keep_alive,
    )


if __name__ == "__main__":
    main()
