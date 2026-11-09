"""Entity MCP host: PAT gate, instructions, and permission-cropped tools/list."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta

import httpx
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

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.mcp.catalog import (  # noqa: E402
    MCP_TOOLS,
    TOOLS_LIST_TTL_MS,
    tools_for_permissions,
)
from backend.entity.mcp.http import create_mcp_http_app  # noqa: E402
from backend.entity.mcp.server import list_entities, mcp  # noqa: E402
from backend.main import app  # noqa: E402
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


def _pat(client: TestClient, name: str = "entity-mcp-pat") -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": name, "expires_at": expires})
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def _tools_list(mcp_client: StarletteTestClient, secret: str):
    from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_PROTOCOL_VERSION_HEADER
    from mcp_types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY
    from mcp_types.version import LATEST_MODERN_VERSION

    return mcp_client.post(
        "/mcp/entity",
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


def _jsonrpc_result(response: object) -> dict:
    text = response.text  # type: ignore[attr-defined]
    if text.startswith("event:") or "data:" in text:
        data_lines = [
            line[5:] for line in text.splitlines() if line.startswith("data:")
        ]
        text = data_lines[-1] if data_lines else text
    body = json.loads(text)
    if "error" in body and "result" not in body:
        raise AssertionError(body)
    return body["result"]


def test_catalog_names_match_registered_tools() -> None:
    registered = list(asyncio.run(MCPServer.list_tools(mcp)))
    assert {tool.name for tool in registered} == {spec.name for spec in MCP_TOOLS}
    assert [spec.name for spec in MCP_TOOLS] == [
        "list_entities",
        "describe_entity",
        "list_dictionary_codes",
        "get_row",
        "query_rows",
        "validate_sql",
        "run_sql",
    ]
    assert [spec.permission for spec in MCP_TOOLS] == ["entity:data_read"] * 7
    for tool in registered:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


def test_server_instructions_describe_the_read_workflow() -> None:
    text = mcp.instructions or ""
    for phrase in (
        "list_entities",
        "describe_entity",
        "validate_sql",
        "run_sql",
        "__withheld",
    ):
        assert phrase in text
    lowered = text.lower()
    assert "masked" in lowered
    assert "reference" in lowered


def test_mcp_http_unauthenticated_is_401() -> None:
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        assert mcp_client.get("/readyz").status_code == 200
        missing = mcp_client.post(
            "/mcp/entity",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(missing, status=401, code="AUTH_UNAUTHENTICATED")

        mcp_client.cookies.set("refraq_sid", "not-a-session")
        cookie_only = mcp_client.post(
            "/mcp/entity",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(cookie_only, status=401, code="AUTH_UNAUTHENTICATED")
        mcp_client.cookies.clear()

        bad = mcp_client.post(
            "/mcp/entity",
            headers={"Authorization": "Bearer not-a-real-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(bad, status=401, code="AUTH_UNAUTHENTICATED")


def test_mcp_http_non_post_is_405_after_auth(client: TestClient) -> None:
    secret = _pat(client)
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        mcp_client.timeout = httpx.Timeout(2.0)
        headers = {"Authorization": f"Bearer {secret}"}
        for method in ("get", "delete"):
            response = getattr(mcp_client, method)("/mcp/entity", headers=headers)
            assert_problem(response, status=405, code="HTTP_METHOD_NOT_ALLOWED")
            assert response.headers.get("allow") == "POST"

        unauthenticated = mcp_client.get("/mcp/entity")
        assert_problem(unauthenticated, status=401, code="AUTH_UNAUTHENTICATED")

        listed = _tools_list(mcp_client, secret)
        assert listed.status_code == 200, listed.text
        again = _tools_list(mcp_client, secret)
        assert again.status_code == 200, again.text


def test_tools_list_requires_entity_data_read(client: TestClient) -> None:
    secret = _pat(client)
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        response = _tools_list(mcp_client, secret)
        assert response.status_code == 200, response.text
        payload = _jsonrpc_result(response)
        assert [tool["name"] for tool in payload["tools"]] == [
            "list_entities",
            "describe_entity",
            "list_dictionary_codes",
            "get_row",
            "query_rows",
            "validate_sql",
            "run_sql",
        ]
        assert payload.get("ttlMs") == TOOLS_LIST_TTL_MS
        assert payload.get("cacheScope") == "private"
        for tool in payload["tools"]:
            assert tool["annotations"]["readOnlyHint"] is True
            meta = tool.get("_meta")
            assert isinstance(meta, dict)
            assert meta.get("io.refraq/execution") == "read"
            assert tool.get("execution") not in ("read", "write")
            props = (tool.get("inputSchema") or {}).get("properties") or {}
            assert "authorization" not in props
            assert "narrow" not in props

    roles = get_role_store()
    create_role(
        roles,
        key="entity_mcp_writer",
        name="Entity writer",
        permissions=["console:access", "tokens:write", "entity:write"],
    )
    get_user_store().create_user(
        account="writer",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=roles.get_by_key("entity_mcp_writer").id,  # type: ignore[union-attr]
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "writer", "password": "secret"}
    )
    assert login.status_code == 200, login.text
    writer_secret = _pat(client, name="writer-pat")
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        response = _tools_list(mcp_client, writer_secret)
        assert response.status_code == 200, response.text
        assert _jsonrpc_result(response)["tools"] == []
    assert tools_for_permissions(["entity:write"]) == []


def test_tool_failure_uses_the_error_envelope(client: TestClient) -> None:
    bare = json.loads(list_entities())
    assert bare == {
        "error": {
            "code": "AUTH_UNAUTHENTICATED",
            "message": "Not signed in or session expired",
        }
    }

    roles = get_role_store()
    create_role(
        roles,
        key="entity_mcp_no_read",
        name="No data read",
        permissions=["console:access", "tokens:write", "entity:write"],
    )
    get_user_store().create_user(
        account="noread",
        display_name="No read",
        password_hash=hash_password("secret"),
        role_id=roles.get_by_key("entity_mcp_no_read").id,  # type: ignore[union-attr]
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "noread", "password": "secret"}
    )
    assert login.status_code == 200, login.text
    secret = _pat(client, name="noread-pat")
    with mcp_authorization(f"Bearer {secret}"):
        forbidden = json.loads(list_entities())
    assert forbidden == {
        "error": {
            "code": "AUTH_FORBIDDEN",
            "message": "Missing permission entity:data_read",
        }
    }

    client.post("/auth/logout")
    admin = client.post(
        "/auth/login", json={"account": "admin", "password": "secret"}
    )
    assert admin.status_code == 200, admin.text
    admin_secret = _pat(client, name="admin-envelope")
    with mcp_authorization(f"Bearer {admin_secret}"):
        broken = json.loads(list_entities(limit="nope"))  # type: ignore[arg-type]
    assert set(broken) == {"error"}
    assert set(broken["error"]) == {"code", "message"}
    assert broken["error"]["code"] == "MCP_ERROR"
    assert broken["error"]["message"]
