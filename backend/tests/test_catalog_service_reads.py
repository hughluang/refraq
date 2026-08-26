"""Catalog service read-path tests (C1) + thin HTTP/MCP join-path smoke."""

from __future__ import annotations

from backend.core.time import utc_now, format_instant
import json
import os
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog import service as catalog_service  # noqa: E402
from backend.metadata.catalog import semantics as catalog_semantics  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.errors import (  # noqa: E402
    CatalogSearchQueryRequired,
    JoinPathUnavailable,
)
from backend.metadata.mcp_server import (  # noqa: E402
    find_join_path,
    get_object as mcp_get_object,
    get_object_ddl as mcp_get_object_ddl,
    list_joins as mcp_list_joins,
    list_objects as mcp_list_objects,
    search_columns as mcp_search_columns,
    search_objects as mcp_search_objects,
    search_sources as mcp_search_sources,
)
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
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


def _seed_source() -> None:
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_1",
            key="mes",
            locator_key="src/postgresql/mes",
            name="MES",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )


def _table(
    object_id: str,
    name: str,
    columns: list[tuple[str, str]],
) -> CatalogObjectRecord:
    now = utc_now()
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_1",
        locator_key=f"obj/postgresql/mes/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl=f"CREATE TABLE {name} ();",
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=f"Biz {name}",
        business_description="desc",
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source="mcp",
        business_semantics_ready=True,
        semantics_updated_at=now,
        last_structure_job_id=None,
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=cid,
                object_id=object_id,
                locator_key=f"col/postgresql/mes/public/table/{name}/column/{cname}",
                name=cname,
                ordinal=i,
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
            for i, (cid, cname) in enumerate(columns)
        ],
    )


def test_service_empty_search_raises() -> None:
    _seed_source()
    with pytest.raises(CatalogSearchQueryRequired):
        catalog_service.search_objects("   ")
    with pytest.raises(CatalogSearchQueryRequired):
        catalog_service.search_columns("")


def test_service_read_model_and_semantics() -> None:
    _seed_source()
    store = get_catalog_store()
    a = _table("obj_a", "orders", [("col_id", "id")])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    items, total = catalog_service.list_objects_for_source("src_1")
    assert total == 1
    assert items[0].name == "orders"
    assert items[0].business_name == "Biz orders"
    assert items[0].columns == []

    detail = catalog_service.get_object("obj_a")
    assert detail.ddl is not None
    assert len(detail.columns) == 1
    assert detail.columns[0].name == "id"

    sem = catalog_semantics.get_object_semantics(a.locator_key)
    assert sem.business_name == "Biz orders"
    assert sem.business_semantics_ready is True


def test_list_q_and_readiness_filters_and_present_keeps_columns() -> None:
    _seed_source()
    ready = _table("obj_a", "orders", [("col_id", "id")])
    not_ready = replace(
        _table("obj_b", "payments", [("col_b", "id")]),
        business_name="Payment slip",
        business_description="contains the word orders here",
        business_semantics_ready=False,
    )
    wildcard = replace(
        _table("obj_c", "foo%bar", [("col_c", "id")]),
        business_name=None,
        business_semantics_ready=False,
    )
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[ready, not_ready, wildcard],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )

    listed, total = catalog_service.list_objects_for_source("src_1", q="Payment")
    assert total == 1
    assert listed[0].name == "payments"
    assert listed[0].columns == []

    by_name, total = catalog_service.list_objects_for_source("src_1", q="orders")
    assert total == 1
    assert by_name[0].name == "orders"

    by_locator, total = catalog_service.list_objects_for_source("src_1", q="mes")
    assert total == 0
    assert by_locator == []

    by_percent, total = catalog_service.list_objects_for_source("src_1", q="%")
    assert total == 1
    assert by_percent[0].name == "foo%bar"

    only_ready, total = catalog_service.list_objects_for_source(
        "src_1", business_semantics_ready=True
    )
    assert total == 1
    assert only_ready[0].name == "orders"

    only_not_ready, total = catalog_service.list_objects_for_source(
        "src_1", business_semantics_ready=False
    )
    assert total == 2
    assert {o.name for o in only_not_ready} == {"payments", "foo%bar"}

    present = get_catalog_store().list_present_for_source("src_1")
    assert len(present) == 3
    assert all(o.columns for o in present)


def test_include_absent_changes_list_total() -> None:
    _seed_source()
    keep = _table("obj_a", "orders", [("col_id", "id")])
    gone = _table("obj_b", "payments", [("col_b", "id")])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[keep, gone],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j2",
        collected=[keep],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )

    with_absent, total_all = catalog_service.list_objects_for_source(
        "src_1", include_absent=True
    )
    present_only, total_present = catalog_service.list_objects_for_source(
        "src_1", include_absent=False
    )
    assert total_all == 2
    assert total_present == 1
    assert total_all != total_present
    assert {o.name for o in with_absent} == {"orders", "payments"}
    assert present_only[0].name == "orders"
    assert all(not o.columns for o in with_absent)
    assert len(get_catalog_store().list_present_for_source("src_1")) == 1


def test_list_filters_http_and_mcp(client: TestClient) -> None:
    _seed_source()
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _table("obj_a", "orders", [("col_id", "id")]),
            replace(
                _table("obj_b", "payments", [("col_b", "id")]),
                business_name="Payment slip",
                business_semantics_ready=False,
            ),
        ],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )

    ready = client.get("/sources/src_1/objects?business_semantics_ready=true")
    assert ready.status_code == 200
    body = ready.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "orders"
    assert body["items"][0]["columns"] == []

    named = client.get("/sources/src_1/objects?q=Payment")
    assert named.status_code == 200
    assert named.json()["total"] == 1
    assert named.json()["items"][0]["name"] == "payments"

    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "list-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]
    payload = json.loads(
        mcp_list_objects(
            authorization=f"Bearer {secret}",
            source_locator_key="src/postgresql/mes",
            business_semantics_ready=False,
        )
    )
    assert payload["total"] == 1
    assert payload["items"][0]["name"] == "payments"
    assert "columns" not in payload["items"][0]

    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j2",
        collected=[_table("obj_a", "orders", [("col_id", "id")])],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    with_absent = client.get("/sources/src_1/objects")
    present_only = client.get("/sources/src_1/objects?include_absent=false")
    assert with_absent.status_code == 200
    assert present_only.status_code == 200
    assert with_absent.json()["total"] == 2
    assert present_only.json()["total"] == 1
    assert with_absent.json()["total"] != present_only.json()["total"]


_OBJECT_IDENTITY = (
    "id",
    "locator_key",
    "source_id",
    "name",
    "schema_name",
    "object_type",
    "is_present",
)
_MCP_SUMMARY_OMIT = frozenset({"columns", "foreign_keys", "indexes", "ddl"})
_MCP_DETAIL_OMIT = frozenset({"foreign_keys", "indexes"})


def _pat_secret(client: TestClient) -> str:
    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "parity-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    return tok.json()["secret"]


def _pick(payload: dict, keys: tuple[str, ...]) -> dict:
    return {k: payload[k] for k in keys}


def test_catalog_http_mcp_projection_parity(client: TestClient) -> None:
    _seed_source()
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[_table("obj_a", "orders", [("col_id", "id")])],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    get_catalog_store().write_insert_join(
        from_column_id="col_id",
        to_column_id="col_id",
        evidence="self probe",
        created_by_user_id=None,
        attester="human",
        join_expression="id = id",
    )
    secret = _pat_secret(client)
    auth = f"Bearer {secret}"
    locator = "obj/postgresql/mes/public/table/orders"

    http_list = client.get("/sources/src_1/objects")
    assert http_list.status_code == 200
    mcp_list = json.loads(
        mcp_list_objects(authorization=auth, source_locator_key="src/postgresql/mes")
    )
    assert "error" not in mcp_list, mcp_list
    assert http_list.json()["total"] == mcp_list["total"] == 1
    http_item = http_list.json()["items"][0]
    mcp_item = mcp_list["items"][0]
    assert _pick(http_item, _OBJECT_IDENTITY) == _pick(mcp_item, _OBJECT_IDENTITY)
    assert http_item["columns"] == []
    assert http_item["foreign_keys"] == []
    assert _MCP_SUMMARY_OMIT.isdisjoint(mcp_item)

    http_obj = client.get("/objects/obj_a")
    assert http_obj.status_code == 200
    mcp_obj = json.loads(mcp_get_object(authorization=auth, object_locator_key=locator))
    assert "error" not in mcp_obj, mcp_obj
    http_detail = http_obj.json()["object"]
    assert _pick(http_detail, _OBJECT_IDENTITY) == _pick(mcp_obj, _OBJECT_IDENTITY)
    assert "foreign_keys" in http_detail
    assert "indexes" in http_detail
    assert _MCP_DETAIL_OMIT.isdisjoint(mcp_obj)
    assert "normalized_type" in http_detail["columns"][0]
    assert "normalized_type" not in mcp_obj["columns"][0]

    http_search = client.get("/catalog/objects/search?q=order")
    mcp_search = json.loads(
        mcp_search_objects(authorization=auth, query_text="order")
    )
    assert http_search.status_code == 200
    assert "error" not in mcp_search, mcp_search
    assert http_search.json()["total"] == mcp_search["total"]
    assert _pick(http_search.json()["items"][0], _OBJECT_IDENTITY) == _pick(
        mcp_search["items"][0], _OBJECT_IDENTITY
    )
    assert _MCP_SUMMARY_OMIT.isdisjoint(mcp_search["items"][0])

    http_cols = client.get("/catalog/columns/search?q=id")
    mcp_cols = json.loads(mcp_search_columns(authorization=auth, query_text="id"))
    assert http_cols.status_code == 200
    assert "error" not in mcp_cols, mcp_cols
    assert http_cols.json()["total"] == mcp_cols["total"]
    assert http_cols.json()["items"][0]["id"] == mcp_cols["items"][0]["id"]
    assert "normalized_type" in http_cols.json()["items"][0]
    assert "normalized_type" not in mcp_cols["items"][0]

    http_joins = client.get("/objects/obj_a/joins")
    mcp_joins = json.loads(mcp_list_joins(authorization=auth, object_locator_key=locator))
    assert http_joins.status_code == 200
    assert "error" not in mcp_joins, mcp_joins
    assert http_joins.json()["total"] == mcp_joins["total"] == 1
    assert http_joins.json()["items"][0]["id"] == mcp_joins["items"][0]["id"]

    http_ddl = client.get("/objects/obj_a/ddl")
    mcp_ddl = json.loads(mcp_get_object_ddl(authorization=auth, object_locator_key=locator))
    assert http_ddl.status_code == 200
    assert "error" not in mcp_ddl, mcp_ddl
    assert http_ddl.json()["id"] == mcp_ddl["id"]
    assert http_ddl.json()["ddl"] == mcp_ddl["ddl"]
    assert "locator_key" not in http_ddl.json()
    assert mcp_ddl["locator_key"] == locator

    http_sources = client.get("/sources?limit=50")
    mcp_sources = json.loads(mcp_search_sources(authorization=auth, limit=50))
    assert http_sources.status_code == 200
    assert "error" not in mcp_sources, mcp_sources
    assert http_sources.json()["total"] == mcp_sources["total"]
    http_src = http_sources.json()["items"][0]
    mcp_src = mcp_sources["items"][0]
    assert http_src["id"] == mcp_src["id"]
    assert http_src["key"] == mcp_src["key"]
    assert http_src["locator_key"] == mcp_src["locator_key"]

    filtered = json.loads(
        mcp_search_sources(authorization=auth, query_text="mes", limit=50)
    )
    assert filtered["total"] == 1
    miss = json.loads(
        mcp_search_sources(authorization=auth, query_text="zzz-no-such", limit=50)
    )
    assert miss["total"] == 0


def test_service_lookup_join_paths() -> None:
    _seed_source()
    store = get_catalog_store()
    a = _table("obj_a", "a", [("col_a_id", "id"), ("col_a_b", "b_id")])
    b = _table("obj_b", "b", [("col_b_id", "id")])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[a, b],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    store.write_insert_join(
        from_column_id="col_a_b",
        to_column_id="col_b_id",
        evidence="fk",
        created_by_user_id=None,
        attester="human",
        join_expression="a.b_id = b.id",
    )
    result = catalog_service.lookup_join_paths(
        a.locator_key,
        b.locator_key,
        max_hops=1,
    )
    assert result.paths_found == 1
    assert result.paths[0].hops[0].from_column_locator_key is not None

    empty = _table("obj_empty", "empty", [])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j2",
        collected=[a, b, empty],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    with pytest.raises(JoinPathUnavailable):
        catalog_service.lookup_join_paths(empty.locator_key)


def test_http_join_path_smoke(client: TestClient) -> None:
    source = client.post(
        "/sources",
        json={
            "key": "path-src",
            "name": "path",
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["source"]["id"]
    store = get_catalog_store()
    now = utc_now()
    a = CatalogObjectRecord(
        id="obj_http_a",
        source_id=source_id,
        locator_key="obj/postgresql/path-src/public/table/a",
        object_type="table",
        schema_name="public",
        name="a",
        ddl=None,
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=None,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
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
                id="col_http_a",
                object_id="obj_http_a",
                locator_key="col/postgresql/path-src/public/table/a/column/id",
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
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    resp = client.get(
        "/joins/path",
        params={"start": a.locator_key, "max_hops": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "paths_found" in body
    assert "direct_joins" in body


def test_mcp_find_join_path_smoke(client: TestClient) -> None:
    source = client.post(
        "/sources",
        json={
            "key": "mcp-path",
            "name": "mcp-path",
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["source"]["id"]
    store = get_catalog_store()
    now = utc_now()
    a = CatalogObjectRecord(
        id="obj_mcp_a",
        source_id=source_id,
        locator_key="obj/postgresql/mcp-path/public/table/a",
        object_type="table",
        schema_name="public",
        name="a",
        ddl=None,
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=None,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
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
                id="col_mcp_a",
                object_id="obj_mcp_a",
                locator_key="col/postgresql/mcp-path/public/table/a/column/id",
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
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "path-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]
    payload = find_join_path(
        authorization=f"Bearer {secret}",
        start_locator_key=a.locator_key,
        max_hops=1,
    )
    body = json.loads(payload)
    assert "error" not in body
    assert "paths_found" in body
