"""get_row and query_rows tool behavior that does not need a database."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.core.bulkhead import reset_peek_bulkhead  # noqa: E402
from backend.core.request_id import correlation_id  # noqa: E402
from backend.core.runtime import reset_runtime_capacity  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.admin.principal import mcp_authorization  # noqa: E402
from backend.entity.mcp.rows import get_row, query_rows  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.entity_access_oracle import prepare_legacy_entity  # noqa: E402

PASSWORD = "secret"


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password(PASSWORD),
        role_id=admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        yield test_client


def _pat(client: TestClient, name: str = "rows-pat") -> tuple[str, str]:
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post("/tokens", json={"name": name, "expires_at": expires})
    assert created.status_code == 201, created.text
    body = created.json()
    return body["secret"], body["token"]["id"]


def _call(fn: Any, secret: str, **kwargs: Any) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        with mcp_authorization(f"Bearer {secret}"):
            return json.loads(await fn(**kwargs))

    return asyncio.run(_run())


def _seed_material() -> str:
    now = datetime.now(timezone.utc)
    attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
        ),
        AttributeRecord(name="note", type="text"),
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="material",
        name="Material",
        description="Stock",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status="published",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    prepare_legacy_entity(entity.id)
    return entity.id


def test_narrow_is_rejected_before_row_reads(client: TestClient) -> None:
    secret, _token_id = _pat(client)
    for fn, kwargs in (
        (get_row, {"table_name": "material", "row_id": 1}),
        (query_rows, {"table_name": "material"}),
    ):
        refused = _call(fn, secret, narrow={"type": "user"}, **kwargs)
        assert refused == {
            "error": {
                "code": "REQUEST_INVALID",
                "message": "narrow is not accepted",
            }
        }


def test_zero_admission_slots_return_the_tool_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret, _token_id = _pat(client)
    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "0")
    reset_runtime_capacity()
    reset_peek_bulkhead()
    expected = {
        "error": {
            "code": "ADMISSION_CAPACITY_EXCEEDED",
            "message": "Platform admission is at capacity",
        }
    }
    assert _call(get_row, secret, table_name="material", row_id=1) == expected
    assert _call(query_rows, secret, table_name="material") == expected


def test_missing_data_read_is_forbidden(client: TestClient) -> None:
    role = create_role(
        get_role_store(),
        key="rows_writer",
        name="Rows writer",
        permissions=["console:access", "tokens:write", "entity:write"],
    )
    get_user_store().create_user(
        account="writer",
        display_name="Writer",
        password_hash=hash_password(PASSWORD),
        role_id=role.id,
        status="active",
    )
    logged_in = client.post(
        "/auth/login", json={"account": "writer", "password": PASSWORD}
    )
    assert logged_in.status_code == 200, logged_in.text
    secret, _token_id = _pat(client, name="writer-pat")
    forbidden = {
        "error": {
            "code": "AUTH_FORBIDDEN",
            "message": "Missing permission entity:data_read",
        }
    }
    assert _call(get_row, secret, table_name="material", row_id=1) == forbidden
    assert _call(query_rows, secret, table_name="material") == forbidden


def test_get_row_records_the_pat_and_requires_one_locator(client: TestClient) -> None:
    entity_id = _seed_material()
    secret, token_id = _pat(client)
    missing = _call(get_row, secret, table_name="material")
    assert missing == {
        "error": {
            "code": "REQUEST_INVALID",
            "message": "exactly one of row_id or business_key is required",
        }
    }
    both = _call(get_row, secret, table_name="material", row_id=1, business_key="SKU")
    assert both["error"]["code"] == "REQUEST_INVALID"
    assert "exactly one of row_id or business_key" in both["error"]["message"]
    logs = get_access_store().logs_for_entity(entity_id)
    assert [item.verb for item in logs] == ["get", "get"]
    assert {item.outcome_code for item in logs} == {"REQUEST_INVALID"}
    assert {item.pat_id for item in logs} == {token_id}


def test_query_rows_rejects_limits_outside_the_data_api(
    client: TestClient,
) -> None:
    entity_id = _seed_material()
    secret, token_id = _pat(client)
    over_limit = _call(query_rows, secret, table_name="material", limit=201)
    assert over_limit == {
        "error": {"code": "REQUEST_INVALID", "message": "limit must be <= 200"}
    }
    assert "items" not in over_limit
    logs = [
        item
        for item in get_access_store().logs_for_entity(entity_id)
        if item.verb == "query"
    ]
    assert [item.outcome_code for item in logs] == ["REQUEST_INVALID"]
    assert {item.pat_id for item in logs} == {token_id}


@pytest.mark.parametrize("keyset", [False, True])
def test_http_and_mcp_read_live_page_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, keyset: bool,
) -> None:
    from contextlib import nullcontext
    from backend.admin.system_parameters import reset_parameter, set_parameter
    from backend.entity.data import sql
    from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS

    _seed_material()
    secret, _ = _pat(client)
    seen = []
    monkeypatch.setattr(sql, "entity_read_connection", lambda ctx: nullcontext(None))
    def offset(conn, target, **kwargs):
        seen.append(kwargs["limit"])
        return [], 0
    def keyset_page(conn, target, **kwargs):
        seen.append(kwargs["limit"])
        return [], None
    monkeypatch.setattr(sql, "query_offset", offset)
    monkeypatch.setattr(sql, "query_keyset", keyset_page)
    paging = {"after_row_id": None} if keyset else {}
    def request(limit):
        body = dict(paging)
        if limit is not None:
            body["limit"] = limit
        http = client.post("/entities/material/query", json=body)
        mcp = _call(query_rows, secret, table_name="material", **body)
        return http, mcp
    http, mcp = request(201)
    assert http.status_code == 422
    assert http.json()["code"] == mcp["error"]["code"] == "REQUEST_INVALID"
    assert mcp["error"]["message"] == "limit must be <= 200"
    set_parameter("entity_page_limit_max", 1000, actor_user_id=None)
    for value in (201, 1000, None, 1):
        http, mcp = request(value)
        assert http.status_code == 200, http.text
        assert http.json()["limit"] == mcp["limit"] == (50 if value is None else value)
    assert seen == [201, 201, 1000, 1000, 50, 50, 1, 1]
    http, mcp = request(1001)
    assert http.status_code == 422
    assert http.json()["detail"] == mcp["error"]["message"] == "limit must be <= 1000"
    set_parameter("entity_page_limit_max", 50, actor_user_id=None)
    http, mcp = request(201)
    assert http.status_code == 422
    assert mcp["error"]["message"] == "limit must be <= 50"
    reset_parameter("entity_page_limit_max", actor_user_id=None)
    assert request(201)[1]["error"]["message"] == "limit must be <= 200"
    guidance = TOOL_DESCRIPTIONS["query_rows"]
    assert "defaults to 50" in guidance
    assert "initially 200" in guidance
    assert "site-configurable" in guidance
    assert "must be <= 200" not in guidance


def test_query_offset_has_no_maximum() -> None:
    from backend.entity.data.paging import resolve_offset_query
    from backend.entity.errors import EntityRequestInvalid

    assert resolve_offset_query({"offset": 10001, "limit": 50}, maximum=200) == (50, 10001, True)
    with pytest.raises(EntityRequestInvalid, match="offset must be an integer >= 0"):
        resolve_offset_query({"offset": -1}, maximum=200)


def test_get_row_and_query_rows_log_the_calling_request_id(client: TestClient) -> None:
    entity_id = _seed_material()
    secret, _token_id = _pat(client)
    request_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    async def _run() -> None:
        token = correlation_id.set(request_id)
        try:
            with mcp_authorization(f"Bearer {secret}"):
                await get_row(table_name="material")
                await query_rows(table_name="material", limit=201)
        finally:
            correlation_id.reset(token)

    asyncio.run(_run())
    logged = [
        (item.verb, item.request_id)
        for item in get_access_store().logs_for_entity(entity_id)
    ]
    assert logged == [("get", request_id), ("query", request_id)]


def test_unknown_table_is_not_found_without_an_access_log(client: TestClient) -> None:
    secret, _token_id = _pat(client)
    missing = _call(get_row, secret, table_name="no_such_entity", row_id=1)
    assert missing == {
        "error": {
            "code": "ENTITY_NOT_FOUND",
            "message": "Business Entity with table_name 'no_such_entity' was not found",
        }
    }
    queried = _call(query_rows, secret, table_name="no_such_entity")
    assert queried["error"]["code"] == "ENTITY_NOT_FOUND"
