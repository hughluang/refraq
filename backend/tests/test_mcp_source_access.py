"""MCP tools follow the caller's Source Access. PAT is not a second permission set."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import TestClient as StarletteTestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.embedding import set_embed_fn_for_tests  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.connectors.base import QueryResult  # noqa: E402
from backend.metadata.mcp_actor import mcp_authorization  # noqa: E402
from backend.metadata.mcp_guidance import ENRICH_SEMANTICS_BODY  # noqa: E402
from backend.metadata.mcp_http import create_mcp_http_app  # noqa: E402
from backend.metadata.mcp_server import (  # noqa: E402
    delete_join,
    enrich_semantics,
    find_join_path,
    get_object,
    get_object_columns,
    get_object_ddl,
    get_object_semantics,
    get_source,
    list_joins,
    list_objects,
    list_semantics_changes,
    patch_join,
    reject_join,
    restore_join,
    run_sql,
    search_columns,
    search_objects,
    search_sources,
    set_column_semantics,
    set_object_semantics,
    upsert_join,
    upsert_joins,
)
from backend.metadata.source_access import (  # noqa: E402
    create_membership,
    reset_source_access_store,
)
from backend.metadata.sources.access import seal_access  # noqa: E402
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)
from backend.tests.problem import assert_problem  # noqa: E402

PASSWORD = "secret"
UNKNOWN_SOURCE = "src/postgresql/missing"
UNKNOWN_OBJECT = "obj_missing"
UNKNOWN_JOIN = "join_missing"


@dataclass
class _World:
    client: TestClient
    source_a: str
    source_b: str
    locator_a: str
    locator_b: str
    object_a: str
    object_a2: str
    object_b: str
    object_a_locator: str
    object_b_locator: str
    column_a: str
    column_a2: str
    column_b: str
    column_a_locator: str
    column_a2_locator: str
    column_b_locator: str
    pats: dict[str, str]

    def tool(self, account: str, fn: Any, **kwargs: Any) -> dict[str, Any]:
        with mcp_authorization(f"Bearer {self.pats[account]}"):
            result = fn(**kwargs)
            if inspect.iscoroutine(result):
                result = asyncio.run(result)
        return json.loads(result)


@pytest.fixture()
def world() -> _World:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_source_access_store()
    set_embed_fn_for_tests(None)
    roles = get_role_store()
    seed_roles(roles)
    full = create_role(
        roles,
        key="mcp_full",
        name="MCP full",
        permissions=[
            "console:access",
            "sources:read",
            "metadata:read",
            "metadata:write",
            "query:run",
            "tokens:write",
        ],
    )
    no_query = create_role(
        roles,
        key="mcp_no_query",
        name="MCP no query",
        permissions=[
            "console:access",
            "sources:read",
            "metadata:read",
            "metadata:write",
            "tokens:write",
        ],
    )
    no_write = create_role(
        roles,
        key="mcp_no_write",
        name="MCP no write",
        permissions=[
            "console:access",
            "sources:read",
            "metadata:read",
            "query:run",
            "tokens:write",
        ],
    )
    users = {
        "hidden": _user("hidden", full.id),
        "viewer": _user("viewer", full.id),
        "steward": _user("steward", full.id),
        "noquery": _user("noquery", no_query.id),
        "reader": _user("reader", no_write.id),
        "other": _user("other", full.id),
    }
    _source("src_a", "src-a")
    _source("src_b", "src-b")
    orders = _table("obj_orders", "orders", "src_a", "src-a")
    customers = _table("obj_customers", "customers", "src_a", "src-a")
    secret = _table("obj_secret", "orders", "src_b", "src-b")
    apply_structure_snapshot(
        source=require_source("src_a"),
        job_id="job_a",
        collected=[orders, customers],
        schema_scope=None,
    )
    apply_structure_snapshot(
        source=require_source("src_b"),
        job_id="job_b",
        collected=[secret],
        schema_scope=None,
    )
    _member(users["viewer"], "src_a", "viewer")
    _member(users["steward"], "src_a", "steward")
    _member(users["steward"], "src_b", "steward")
    _member(users["noquery"], "src_a", "viewer")
    _member(users["reader"], "src_a", "maintainer")
    _member(users["other"], "src_b", "viewer")
    built = _World(
        client=TestClient(app),
        source_a="src_a",
        source_b="src_b",
        locator_a="src/postgresql/src-a",
        locator_b="src/postgresql/src-b",
        object_a="obj_orders",
        object_a2="obj_customers",
        object_b="obj_secret",
        object_a_locator="obj/postgresql/src-a/public/table/orders",
        object_b_locator="obj/postgresql/src-b/public/table/orders",
        column_a="col_obj_orders",
        column_a2="col_obj_customers",
        column_b="col_obj_secret",
        column_a_locator="col/postgresql/src-a/public/table/orders/column/id",
        column_a2_locator="col/postgresql/src-a/public/table/customers/column/id",
        column_b_locator="col/postgresql/src-b/public/table/orders/column/id",
        pats={},
    )
    with built.client:
        built.pats = {account: _pat(built.client, account) for account in users}
        yield built
    set_embed_fn_for_tests(None)


def _user(account: str, role_id: str) -> str:
    record = get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password(PASSWORD),
        role_id=role_id,
        status="active",
    )
    return record.id


def _member(user_id: str, source_id: str, level: str) -> None:
    create_membership(
        subject_type="user",
        subject_id=user_id,
        target=source_id,
        level=level,
    )


def _source(source_id: str, key: str) -> None:
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=key,
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=seal_access(
                "postgresql",
                {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "username": "u",
                    "password": "super-secret-password",
                    "ssl_mode": "require",
                    "database": "MES",
                    "schema": "public",
                    "extra": {},
                },
            ),
            access_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _table(
    object_id: str, name: str, source_id: str, source_key: str
) -> CatalogObjectRecord:
    now = utc_now()
    column_id = f"col_{object_id}"
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/postgresql/{source_key}/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl="CREATE TABLE x (id int)",
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=None,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=False,
        semantics_updated_at=None,
        last_structure_job_id=None,
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=column_id,
                object_id=object_id,
                locator_key=(
                    f"col/postgresql/{source_key}/public/table/{name}/column/id"
                ),
                name="id",
                ordinal=0,
                data_type="int",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
        ],
    )


def _pat(client: TestClient, account: str) -> str:
    login = client.post(
        "/auth/login",
        json={"account": account, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post(
        "/tokens",
        json={"name": f"{account}-pat", "expires_at": expires},
    )
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def _error(payload: dict[str, Any]) -> dict[str, str]:
    assert set(payload) == {"error"}, payload
    error = payload["error"]
    assert set(error) == {"code", "message"}, error
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


def _source_keys(payload: dict[str, Any]) -> set[str]:
    assert "error" not in payload, payload
    return {item["key"] for item in payload["items"]}


def test_lists_and_search_stay_inside_visible_sources(world: _World) -> None:
    hidden_sources = world.tool("hidden", search_sources, limit=50)
    assert _source_keys(hidden_sources) == set()
    assert hidden_sources["total"] == 0

    assert _source_keys(world.tool("viewer", search_sources, limit=50)) == {"src-a"}
    assert _source_keys(world.tool("other", search_sources, limit=50)) == {"src-b"}

    listed = world.tool(
        "viewer", list_objects, source_locator_key=world.locator_a, limit=50
    )
    assert {item["id"] for item in listed["items"]} == {
        world.object_a,
        world.object_a2,
    }
    hidden_list = world.tool(
        "hidden", list_objects, source_locator_key=world.locator_a
    )
    unknown_list = world.tool(
        "hidden", list_objects, source_locator_key=UNKNOWN_SOURCE
    )
    assert _error(hidden_list) == _error(unknown_list)
    assert _error(hidden_list)["code"] == "SOURCE_NOT_FOUND"
    foreign_list = world.tool(
        "viewer", list_objects, source_locator_key=world.locator_b
    )
    assert _error(foreign_list)["code"] == "SOURCE_NOT_FOUND"

    visible_objects = world.tool("viewer", search_objects, query_text="orders")
    assert {item["id"] for item in visible_objects["items"]} == {world.object_a}
    assert world.tool("hidden", search_objects, query_text="orders")["items"] == []
    hidden_filter = world.tool(
        "viewer",
        search_objects,
        query_text="orders",
        source_locator_key=world.locator_b,
    )
    unknown_filter = world.tool(
        "viewer",
        search_objects,
        query_text="orders",
        source_locator_key=UNKNOWN_SOURCE,
    )
    assert _error(hidden_filter) == _error(unknown_filter)
    assert _error(hidden_filter)["code"] == "SOURCE_NOT_FOUND"

    visible_columns = world.tool("viewer", search_columns, query_text="id")
    assert {item["id"] for item in visible_columns["items"]} == {
        world.column_a,
        world.column_a2,
    }
    assert world.tool("hidden", search_columns, query_text="id")["items"] == []
    hidden_columns = world.tool(
        "viewer",
        search_columns,
        query_text="id",
        source_locator_key=world.locator_b,
    )
    assert _error(hidden_columns)["code"] == "SOURCE_NOT_FOUND"

    reachable = world.tool(
        "viewer", find_join_path, start_locator_key=world.object_a_locator
    )
    assert "error" not in reachable
    assert reachable["paths_found"] == 0
    hidden_start = world.tool(
        "viewer", find_join_path, start_locator_key=world.object_b_locator
    )
    assert _error(hidden_start)["code"] == "CATALOG_OBJECT_NOT_FOUND"


def test_invisible_locators_use_the_existing_not_found_codes(world: _World) -> None:
    hidden_source = world.tool("hidden", get_source, source_locator_key=world.locator_a)
    unknown_source = world.tool(
        "hidden", get_source, source_locator_key=UNKNOWN_SOURCE
    )
    assert _error(hidden_source) == _error(unknown_source)
    assert _error(hidden_source)["code"] == "SOURCE_NOT_FOUND"
    visible_source = world.tool(
        "viewer", get_source, source_locator_key=world.locator_a
    )
    assert visible_source["key"] == "src-a"
    foreign_source = world.tool(
        "viewer", get_source, source_locator_key=world.locator_b
    )
    assert _error(foreign_source)["code"] == "SOURCE_NOT_FOUND"

    reads = (
        (get_object, "object_locator_key"),
        (get_object_semantics, "object_locator_key"),
        (get_object_columns, "object_locator_key"),
        (get_object_ddl, "object_locator_key"),
        (list_semantics_changes, "object_locator_key"),
        (list_joins, "object_locator_key"),
    )
    for fn, arg in reads:
        hidden = world.tool("hidden", fn, **{arg: world.object_a_locator})
        unknown = world.tool("hidden", fn, **{arg: UNKNOWN_OBJECT})
        assert _error(hidden) == _error(unknown), fn.__name__
        assert _error(hidden)["code"] == "CATALOG_OBJECT_NOT_FOUND", fn.__name__
        foreign = world.tool("viewer", fn, **{arg: world.object_b_locator})
        assert _error(foreign)["code"] == "CATALOG_OBJECT_NOT_FOUND", fn.__name__
        visible = world.tool("viewer", fn, **{arg: world.object_a_locator})
        assert "error" not in visible, fn.__name__


def test_hidden_join_path_target_is_not_cross_source(world: _World) -> None:
    hidden = world.tool(
        "viewer",
        find_join_path,
        start_locator_key=world.object_a_locator,
        target_locator_key=world.object_b_locator,
    )
    unknown = world.tool(
        "viewer",
        find_join_path,
        start_locator_key=world.object_a_locator,
        target_locator_key=UNKNOWN_OBJECT,
    )
    column = world.tool(
        "viewer",
        find_join_path,
        start_locator_key=world.object_a_locator,
        target_locator_key=world.column_b_locator,
    )
    assert _error(hidden) == _error(unknown)
    assert _error(hidden)["code"] == "CATALOG_OBJECT_NOT_FOUND"
    assert _error(column)["code"] == "CATALOG_OBJECT_NOT_FOUND"
    crossed = world.tool(
        "steward",
        find_join_path,
        start_locator_key=world.object_a_locator,
        target_locator_key=world.object_b_locator,
    )
    assert _error(crossed)["code"] == "JOIN_CROSS_SOURCE"


def test_semantics_and_join_writes_require_steward(world: _World) -> None:
    hidden = world.tool(
        "hidden",
        set_object_semantics,
        object_locator_key=world.object_a_locator,
        business_name="Orders",
    )
    unknown = world.tool(
        "hidden",
        set_object_semantics,
        object_locator_key=UNKNOWN_OBJECT,
        business_name="Orders",
    )
    assert _error(hidden) == _error(unknown)
    assert _error(hidden)["code"] == "CATALOG_OBJECT_NOT_FOUND"
    assert (
        _error(
            world.tool(
                "viewer",
                set_object_semantics,
                object_locator_key=world.object_a_locator,
                business_name="Orders",
            )
        )["code"]
        == "AUTH_FORBIDDEN"
    )
    assert (
        _error(
            world.tool(
                "reader",
                set_object_semantics,
                object_locator_key=world.object_a_locator,
                business_name="Orders",
            )
        )["code"]
        == "AUTH_FORBIDDEN"
    )
    written = world.tool(
        "steward",
        set_object_semantics,
        object_locator_key=world.object_a_locator,
        business_name="Orders",
    )
    assert written["object"]["business_name"] == "Orders"

    hidden_columns = world.tool(
        "hidden",
        set_column_semantics,
        object_locator_key=world.object_a_locator,
        columns=[{"column_name": "id", "business_name": "Identifier"}],
    )
    assert _error(hidden_columns)["code"] == "CATALOG_OBJECT_NOT_FOUND"
    assert (
        _error(
            world.tool(
                "viewer",
                set_column_semantics,
                object_locator_key=world.object_a_locator,
                columns=[{"column_name": "id", "business_name": "Identifier"}],
            )
        )["code"]
        == "AUTH_FORBIDDEN"
    )
    columns = world.tool(
        "steward",
        set_column_semantics,
        object_locator_key=world.object_a_locator,
        columns=[{"column_name": "id", "business_name": "Identifier"}],
    )
    assert columns["updated_count"] == 1

    hidden_edge = world.tool(
        "viewer",
        upsert_join,
        from_column_locator_key=world.column_a_locator,
        to_column_locator_key=world.column_b_locator,
        evidence="fk",
    )
    assert _error(hidden_edge)["code"] == "CATALOG_COLUMN_NOT_FOUND"
    assert (
        _error(
            world.tool(
                "hidden",
                upsert_join,
                from_column_locator_key=world.column_a_locator,
                to_column_locator_key=world.column_a2_locator,
                evidence="fk",
            )
        )["code"]
        == "CATALOG_COLUMN_NOT_FOUND"
    )
    assert (
        _error(
            world.tool(
                "viewer",
                upsert_join,
                from_column_locator_key=world.column_a_locator,
                to_column_locator_key=world.column_a2_locator,
                evidence="fk",
            )
        )["code"]
        == "AUTH_FORBIDDEN"
    )
    assert (
        _error(
            world.tool(
                "reader",
                upsert_join,
                from_column_locator_key=world.column_a_locator,
                to_column_locator_key=world.column_a2_locator,
                evidence="fk",
            )
        )["code"]
        == "AUTH_FORBIDDEN"
    )
    crossed = world.tool(
        "steward",
        upsert_join,
        from_column_locator_key=world.column_a_locator,
        to_column_locator_key=world.column_b_locator,
        evidence="fk",
    )
    assert _error(crossed)["code"] == "JOIN_CROSS_SOURCE"
    created = world.tool(
        "steward",
        upsert_join,
        from_column_locator_key=world.column_a_locator,
        to_column_locator_key=world.column_a2_locator,
        evidence="fk",
    )
    join_id = created["join"]["id"]

    hidden_batch = world.tool(
        "viewer",
        upsert_joins,
        joins=[
            {
                "from_column_locator_key": world.column_a_locator,
                "to_column_locator_key": world.column_b_locator,
                "evidence": "fk",
            }
        ],
    )
    assert _error(hidden_batch)["code"] == "CATALOG_COLUMN_NOT_FOUND"
    crossed_batch = world.tool(
        "steward",
        upsert_joins,
        joins=[
            {
                "from_column_locator_key": world.column_a_locator,
                "to_column_locator_key": world.column_b_locator,
                "evidence": "fk",
            }
        ],
    )
    assert _error(crossed_batch)["code"] == "JOIN_CROSS_SOURCE"
    known = world.tool(
        "steward",
        upsert_joins,
        joins=[
            {
                "from_column_locator_key": world.column_a_locator,
                "to_column_locator_key": world.column_a2_locator,
                "evidence": "fk",
            }
        ],
    )
    assert known["already_known_count"] == 1

    hidden_patch = world.tool(
        "hidden", patch_join, join_id=join_id, evidence="revised"
    )
    unknown_patch = world.tool(
        "hidden", patch_join, join_id=UNKNOWN_JOIN, evidence="revised"
    )
    assert _error(hidden_patch) == _error(unknown_patch)
    assert _error(hidden_patch)["code"] == "CATALOG_JOIN_NOT_FOUND"
    assert (
        _error(world.tool("viewer", patch_join, join_id=join_id, evidence="revised"))[
            "code"
        ]
        == "AUTH_FORBIDDEN"
    )
    assert (
        _error(world.tool("reader", patch_join, join_id=join_id, evidence="revised"))[
            "code"
        ]
        == "AUTH_FORBIDDEN"
    )
    amended = world.tool("steward", patch_join, join_id=join_id, evidence="revised")
    assert amended["join"]["evidence"] == "revised"

    assert (
        _error(world.tool("hidden", reject_join, join_id=join_id))["code"]
        == "CATALOG_JOIN_NOT_FOUND"
    )
    assert (
        _error(world.tool("viewer", reject_join, join_id=join_id))["code"]
        == "AUTH_FORBIDDEN"
    )
    assert "error" not in world.tool("steward", reject_join, join_id=join_id)

    assert (
        _error(world.tool("hidden", restore_join, join_id=join_id))["code"]
        == "CATALOG_JOIN_NOT_FOUND"
    )
    assert (
        _error(world.tool("viewer", restore_join, join_id=join_id))["code"]
        == "AUTH_FORBIDDEN"
    )
    assert "error" not in world.tool("steward", restore_join, join_id=join_id)

    assert (
        _error(world.tool("hidden", delete_join, join_id=join_id))["code"]
        == "CATALOG_JOIN_NOT_FOUND"
    )
    assert (
        _error(world.tool("viewer", delete_join, join_id=join_id))["code"]
        == "AUTH_FORBIDDEN"
    )
    deleted = world.tool("steward", delete_join, join_id=join_id)
    assert deleted == {"ok": True, "id": join_id}


def test_run_sql_needs_viewer_and_query_run(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _RecordingConnector()
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: connector,
    )

    outcome = world.tool(
        "viewer",
        run_sql,
        source_locator_key=world.locator_a,
        sql="SELECT 1 AS c",
    )
    assert outcome["columns"] == ["c"]
    assert outcome["rows"] == [["ok"]]
    assert len(connector.calls) == 1

    forbidden = world.tool(
        "noquery",
        run_sql,
        source_locator_key=world.locator_a,
        sql="SELECT 1 AS c",
    )
    assert _error(forbidden)["code"] == "AUTH_FORBIDDEN"
    assert len(connector.calls) == 1

    hidden = world.tool(
        "hidden",
        run_sql,
        source_locator_key=world.locator_a,
        sql="SELECT 1 AS c",
    )
    unknown = world.tool(
        "hidden",
        run_sql,
        source_locator_key=UNKNOWN_SOURCE,
        sql="SELECT 1 AS c",
    )
    assert _error(hidden) == _error(unknown)
    assert _error(hidden)["code"] == "SOURCE_NOT_FOUND"
    assert len(connector.calls) == 1


def test_second_user_pat_does_not_see_the_first_users_sources(world: _World) -> None:
    world.client.post(
        "/auth/login",
        json={"account": "viewer", "password": PASSWORD},
    )
    assert _source_keys(world.tool("other", search_sources, limit=50)) == {"src-b"}
    foreign = world.tool("other", get_source, source_locator_key=world.locator_a)
    assert _error(foreign)["code"] == "SOURCE_NOT_FOUND"
    own = world.tool("viewer", get_object, object_locator_key=world.object_a_locator)
    assert own["id"] == world.object_a
    stolen = world.tool("other", get_object, object_locator_key=world.object_a_locator)
    assert _error(stolen)["code"] == "CATALOG_OBJECT_NOT_FOUND"


def _prompt_without_facts(locator: str) -> str:
    return f"Enrich object: {locator}\n\n" + ENRICH_SEMANTICS_BODY


def _enrich(secret: str, locator: str) -> str:
    with mcp_authorization(f"Bearer {secret}"):
        text = enrich_semantics(locator)
    assert isinstance(text, str)
    return text


def test_enrich_semantics_omits_facts_the_caller_cannot_read(world: _World) -> None:
    patched = get_catalog_store().patch_object_semantics(
        world.object_a,
        open_questions=["ledger-cutoff-unknown"],
    )
    assert patched is not None
    visible = _enrich(world.pats["viewer"], world.object_a_locator)
    assert visible.startswith(f"Enrich object: {world.object_a_locator}\n\n")
    assert visible.endswith(ENRICH_SEMANTICS_BODY)
    assert "Current gaps" in visible
    assert "ledger-cutoff-unknown" in visible
    assert "Columns missing name or description: id" in visible

    hidden = _enrich(world.pats["hidden"], world.object_a_locator)
    unknown = _enrich(world.pats["hidden"], UNKNOWN_OBJECT)
    foreign = _enrich(world.pats["viewer"], world.object_b_locator)
    assert hidden == _prompt_without_facts(world.object_a_locator)
    assert unknown == _prompt_without_facts(UNKNOWN_OBJECT)
    assert foreign == _prompt_without_facts(world.object_b_locator)

    role = create_role(
        get_role_store(),
        key="mcp_no_meta",
        name="MCP no metadata",
        permissions=["console:access", "sources:read", "tokens:write"],
    )
    user_id = _user("noread", role.id)
    _member(user_id, world.source_a, "maintainer")
    secret = _pat(world.client, "noread")
    denied = _enrich(secret, world.object_a_locator)
    assert denied == _prompt_without_facts(world.object_a_locator)


def test_session_cookie_does_not_authenticate_mcp_http(world: _World) -> None:
    login = world.client.post(
        "/auth/login",
        json={"account": "viewer", "password": PASSWORD},
    )
    assert login.status_code == 200
    session = world.client.cookies.get("refraq_sid")
    assert session
    with StarletteTestClient(create_mcp_http_app()) as mcp_client:
        mcp_client.cookies.set("refraq_sid", session)
        cookie_only = mcp_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert_problem(cookie_only, status=401, code="AUTH_UNAUTHENTICATED")


class _RecordingConnector:
    engine = "postgresql"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_readonly(
        self,
        endpoint: object,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        self.calls.append(sql)
        return QueryResult(columns=["c"], rows=[["ok"]], truncated=False)
