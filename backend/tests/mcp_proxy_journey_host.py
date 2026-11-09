"""Test-only memory MCP host for the public same-origin proxy journey.

One process serves either the Metadata or the Entity host app and mints one
User PAT into that process's memory store. Memory stores are not shared across
processes, so a second process inserts the same secret when
``REFRAQ_JOURNEY_PAT_SECRET`` is set. This is not a product server and it does
not open PostgreSQL.

Do not disable DNS rebinding here. ``create_mcp_http_app`` keeps the
production transport policy.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_MCP_HOST"] = "127.0.0.1"
os.environ["REFRAQ_ENTITY_MCP_HOST"] = "127.0.0.1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.pop("ENTITY_READER_DATABASE_URL", None)
os.environ.pop("ENTITY_SIGNER_DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "journey-secrets-master-key")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")


class OriginObserver:
    """Record the Origin header that arrived on a real MCP POST. Do not alter it."""

    def __init__(self, app: object) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope.get("type") == "http" and scope.get("method") == "POST":
            path = scope.get("path") or ""
            if path == "/mcp" or path.startswith("/mcp/"):
                headers = {
                    key.decode("latin-1").lower(): value.decode("latin-1")
                    for key, value in scope.get("headers", [])
                }
                print(f"JOURNEY_ORIGIN {headers.get('origin', '')}", flush=True)
        await self.app(scope, receive, send)  # type: ignore[operator]


def mint_user_pat() -> str:
    from datetime import timedelta

    from backend.admin.role_store import get_role_store, reset_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.security import hash_password
    from backend.admin.token_store import (
        generate_token_secret,
        get_token_store,
        hash_token,
        reset_token_store,
    )
    from backend.admin.user_store import get_user_store, reset_user_store
    from backend.core.config import reset_settings_cache
    from backend.core.time import utc_now

    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_token_store()
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    if super_admin is None:
        raise RuntimeError("memory role seed did not create super_admin")
    user = get_user_store().create_user(
        account="journey",
        display_name="Journey",
        password_hash=hash_password("journey-password"),
        role_id=super_admin.id,
        status="active",
    )
    supplied = os.environ.get("REFRAQ_JOURNEY_PAT_SECRET", "").strip()
    if supplied:
        secret = supplied
        prefix = secret[:12]
        token_hash = hash_token(secret)
    else:
        secret, prefix, token_hash = generate_token_secret()
    get_token_store().create(
        user_id=user.id,
        name="journey-pat",
        token_hash=token_hash,
        prefix=prefix,
        expires_at=utc_now() + timedelta(days=1),
    )
    return secret


def build_host(domain: str) -> object:
    if domain == "metadata":
        from backend.metadata.mcp_http import create_mcp_http_app
    elif domain == "entity":
        from backend.entity.mcp.http import create_mcp_http_app
    else:
        raise RuntimeError(f"unknown MCP host domain: {domain}")
    return create_mcp_http_app()


def serve(app: object, domain: str, secret: str) -> None:
    import uvicorn
    from importlib.metadata import version as distribution_version

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    sock.setblocking(False)
    config = uvicorn.Config(OriginObserver(app), log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    async def run() -> None:
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started:
            if task.done():
                exc = task.exception()
                raise RuntimeError(f"MCP host exited during startup: {exc}")
            await asyncio.sleep(0.05)
        payload = {
            "domain": domain,
            "port": port,
            "secret": secret,
            "store": "memory",
            "mcp_version": distribution_version("mcp"),
            "protocol_version": "2026-07-28",
        }
        print("JOURNEY_READY " + json.dumps(payload, separators=(",", ":")), flush=True)
        await task

    asyncio.run(run())


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"metadata", "entity"}:
        print(
            "usage: mcp_proxy_journey_host.py metadata|entity",
            file=sys.stderr,
        )
        sys.exit(2)
    serve(build_host(sys.argv[1]), sys.argv[1], mint_user_pat())


if __name__ == "__main__":
    main()
