"""MCP catalog HTTP and tools/list crop (same registration table)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from mcp.server import MCPServer
from starlette.testclient import TestClient as StarletteTestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import RoleRecord, get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.mcp_actor import mcp_authorization  # noqa: E402
from backend.metadata.mcp_catalog import (  # noqa: E402
    MCP_PUBLIC_PATH,
    MCP_TOOLS,
    TOOLS_LIST_TTL_MS,
    tools_for_permissions,
)
from backend.metadata.mcp_http import create_mcp_http_app  # noqa: E402
from backend.metadata.mcp_server import mcp  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=super_admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client


def _pat(client: TestClient, name: str = "mcp-pat") -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": name, "expires_at": expires})
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def test_catalog_names_match_registered_tools() -> None:
    registered = {tool.name for tool in asyncio.run(MCPServer.list_tools(mcp))}
    assert registered == {spec.name for spec in MCP_TOOLS}
    assert len(MCP_TOOLS) == 23
    assert {"get_job"}.isdisjoint(registered)
    assert {
        "get_object_ddl",
        "get_object_semantics",
        "get_object_columns",
        "list_semantics_changes",
    }.issubset(registered)


def test_catalog_requires_auth(client: TestClient) -> None:
    client.post("/auth/logout")
    denied = client.get("/mcp/catalog")
    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_catalog_session_and_pat(client: TestClient) -> None:
    session_resp = client.get("/mcp/catalog")
    assert session_resp.status_code == 200, session_resp.text
    body = session_resp.json()
    assert body["public_path"] == MCP_PUBLIC_PATH
    names = [t["name"] for t in body["tools"]]
    assert names == [spec.name for spec in MCP_TOOLS]

    secret = _pat(client)
    pat_resp = client.get(
        "/mcp/catalog",
        headers={"Authorization": f"Bearer {secret}"},
    )
    # Session cookie is preferred when both are present; drop cookie via a
    # fresh client is heavier — PAT-only is covered by logging out.
    assert pat_resp.status_code == 200
    client.post("/auth/logout")
    pat_only = client.get(
        "/mcp/catalog",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert pat_only.status_code == 200
    assert [t["name"] for t in pat_only.json()["tools"]] == names


def test_catalog_and_tools_list_same_crop(client: TestClient) -> None:
    roles = get_role_store()
    roles.insert(
        RoleRecord(
            id="role_src_only",
            key="src_only",
            name="Source reader",
            permissions=["console:access", "sources:read", "tokens:write"],
            locked=False,
        )
    )
    user = get_user_store().create_user(
        account="srcuser",
        display_name="Src",
        password_hash=hash_password("secret"),
        role_id="role_src_only",
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "srcuser", "password": "secret"}
    )
    assert login.status_code == 200
    catalog = client.get("/mcp/catalog")
    assert catalog.status_code == 200
    catalog_names = [t["name"] for t in catalog.json()["tools"]]
    expected = [s.name for s in tools_for_permissions(["console:access", "sources:read"])]
    assert catalog_names == expected
    assert catalog_names == ["search_sources", "get_source"]

    secret = _pat(client, name="src-pat")
    with mcp_authorization(f"Bearer {secret}"):
        listed = asyncio.run(mcp.list_tools())
    listed_names = [tool.name for tool in listed]
    assert listed_names == catalog_names
    for tool in listed:
        schema = tool.input_schema
        props = schema.get("properties") or {}
        assert "authorization" not in props
    assert user.account == "srcuser"


def test_mcp_http_unauthenticated_is_401() -> None:
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        assert mcp_client.get("/readyz").status_code == 200
        missing = mcp_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert_problem(missing, status=401, code="AUTH_UNAUTHENTICATED")

        mcp_client.cookies.set("refraq_sid", "not-a-session")
        cookie_only = mcp_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(cookie_only, status=401, code="AUTH_UNAUTHENTICATED")
        mcp_client.cookies.clear()

        bad = mcp_client.post(
            "/mcp",
            headers={"Authorization": "Bearer not-a-real-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(bad, status=401, code="AUTH_UNAUTHENTICATED")


def _tools_list(mcp_client: StarletteTestClient, secret: str):
    from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_PROTOCOL_VERSION_HEADER
    from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
    from mcp_types.version import LATEST_MODERN_VERSION

    return mcp_client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION,
            MCP_METHOD_HEADER: "tools/list",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
                    CLIENT_CAPABILITIES_META_KEY: {},
                },
            },
        },
    )


def test_mcp_http_tools_list_respects_pat(client: TestClient) -> None:
    secret = _pat(client)
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        response = _tools_list(mcp_client, secret)
        assert response.status_code == 200, response.text
        payload = _jsonrpc_result(response)
        names = [t["name"] for t in payload["tools"]]
        assert names == [spec.name for spec in MCP_TOOLS]
        assert payload.get("ttlMs") == TOOLS_LIST_TTL_MS
        assert payload.get("cacheScope") == "private"
        for tool in payload["tools"]:
            props = (tool.get("inputSchema") or {}).get("properties") or {}
            assert "authorization" not in props


def test_mcp_http_tools_list_matches_catalog_crop(client: TestClient) -> None:
    roles = get_role_store()
    roles.insert(
        RoleRecord(
            id="role_src_http",
            key="src_http",
            name="Source reader HTTP",
            permissions=["console:access", "sources:read", "tokens:write"],
            locked=False,
        )
    )
    get_user_store().create_user(
        account="srchttp",
        display_name="Src HTTP",
        password_hash=hash_password("secret"),
        role_id="role_src_http",
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "srchttp", "password": "secret"}
    )
    assert login.status_code == 200
    catalog_names = [t["name"] for t in client.get("/mcp/catalog").json()["tools"]]
    secret = _pat(client, name="src-http-pat")
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        response = _tools_list(mcp_client, secret)
        assert response.status_code == 200, response.text
        listed = [t["name"] for t in _jsonrpc_result(response)["tools"]]
    assert listed == catalog_names == ["search_sources", "get_source"]


def _jsonrpc_result(response: object) -> dict:
    text = response.text  # type: ignore[attr-defined]
    if text.startswith("event:") or "data:" in text:
        data_lines = [
            line[5:] for line in text.splitlines() if line.startswith("data:")
        ]
        text = data_lines[-1] if data_lines else text
    body = json.loads(text)
    if "error" in body:
        raise AssertionError(body)
    return body["result"]
