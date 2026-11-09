"""Entity MCP catalog HTTP: same crop as tools_for_permissions, session or PAT."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

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
from backend.entity.mcp.catalog import MCP_PUBLIC_PATH, tools_for_permissions  # noqa: E402
from backend.main import app  # noqa: E402

_READER = ["console:access", "tokens:write", "entity:data_read"]
_NO_DATA = ["console:access", "tokens:write"]

# Name list is the classification. Every current Entity tool is a read.
_ENTITY_EXECUTION: dict[str, str] = {
    "list_entities": "read",
    "describe_entity": "read",
    "list_dictionary_codes": "read",
    "get_row": "read",
    "query_rows": "read",
    "validate_sql": "read",
    "run_sql": "read",
}


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


def _role(role_id: str, key: str, permissions: list[str]) -> None:
    get_role_store().insert(
        RoleRecord(
            id=role_id,
            key=key,
            name=key,
            permissions=list(permissions),
            locked=False,
        )
    )


def _user(account: str, role_id: str) -> None:
    get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password("secret"),
        role_id=role_id,
        status="active",
    )


def _login(client: TestClient, account: str) -> None:
    login = client.post(
        "/auth/login",
        json={"account": account, "password": "secret"},
    )
    assert login.status_code == 200, login.text


def _pat(client: TestClient, name: str) -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": name, "expires_at": expires})
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def _tool_rows(permissions: list[str]) -> list[dict[str, str]]:
    return [asdict(spec) for spec in tools_for_permissions(permissions)]


def test_entity_catalog_publishes_execution_class(client: TestClient) -> None:
    response = client.get("/mcp/entity/catalog")
    assert response.status_code == 200, response.text
    tools = response.json()["tools"]
    assert [tool["name"] for tool in tools] == list(_ENTITY_EXECUTION)
    for tool in tools:
        assert tool["execution"] == _ENTITY_EXECUTION[tool["name"]]
        assert tool["execution"] == "read"
        assert tool["permission"] == "entity:data_read"


def test_entity_catalog_requires_auth(client: TestClient) -> None:
    client.post("/auth/logout")
    denied = client.get("/mcp/entity/catalog")
    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_entity_catalog_session_and_pat_match_permission_crop(
    client: TestClient,
) -> None:
    _role("role_entity_reader", "entity_reader", _READER)
    _role("role_no_entity_data", "no_entity_data", _NO_DATA)
    _user("reader", "role_entity_reader")
    _user("nodata", "role_no_entity_data")

    _login(client, "reader")
    session_reader = client.get("/mcp/entity/catalog")
    assert session_reader.status_code == 200, session_reader.text
    reader_body = session_reader.json()
    assert reader_body["public_path"] == "/mcp/entity"
    assert reader_body["public_path"] == MCP_PUBLIC_PATH
    reader_tools = _tool_rows(_READER)
    assert reader_tools
    assert reader_body["tools"] == reader_tools

    reader_secret = _pat(client, "reader-pat")
    client.post("/auth/logout")
    pat_reader = client.get(
        "/mcp/entity/catalog",
        headers={"Authorization": f"Bearer {reader_secret}"},
    )
    assert pat_reader.status_code == 200, pat_reader.text
    assert pat_reader.json() == reader_body

    _login(client, "nodata")
    session_empty = client.get("/mcp/entity/catalog")
    assert session_empty.status_code == 200, session_empty.text
    empty_tools = _tool_rows(_NO_DATA)
    assert empty_tools == []
    assert session_empty.json()["public_path"] == "/mcp/entity"
    assert session_empty.json()["tools"] == []

    empty_secret = _pat(client, "nodata-pat")
    client.post("/auth/logout")
    pat_empty = client.get(
        "/mcp/entity/catalog",
        headers={"Authorization": f"Bearer {empty_secret}"},
    )
    assert pat_empty.status_code == 200, pat_empty.text
    assert pat_empty.json()["tools"] == []
