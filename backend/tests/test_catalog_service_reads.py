"""Catalog service read-path tests (C1) + thin HTTP/MCP join-path smoke."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

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
from backend.metadata.mcp_server import find_join_path  # noqa: E402
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
    now = datetime.utcnow()
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
    now = datetime.utcnow()
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
        source_id="src_1",
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes",
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

    sem = catalog_service.get_object_semantics(a.locator_key)
    assert sem.business_name == "Biz orders"
    assert sem.business_semantics_ready is True

    inspect = catalog_service.inspect_object(a.locator_key)
    assert inspect.id == detail.id
    assert len(inspect.columns) == 1


def test_service_lookup_join_paths() -> None:
    _seed_source()
    store = get_catalog_store()
    a = _table("obj_a", "a", [("col_a_id", "id"), ("col_a_b", "b_id")])
    b = _table("obj_b", "b", [("col_b_id", "id")])
    apply_structure_snapshot(
        source_id="src_1",
        job_id="j1",
        collected=[a, b],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes",
    )
    store.upsert_join(
        from_column_id="col_a_b",
        to_column_id="col_b_id",
        evidence="fk",
        created_by_user_id=None,
        origin="human",
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
        source_id="src_1",
        job_id="j2",
        collected=[a, b, empty],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes",
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
    now = datetime.utcnow()
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
        source_id=source_id,
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="path-src",
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
    now = datetime.utcnow()
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
        source_id=source_id,
        job_id="j1",
        collected=[a],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mcp-path",
    )
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
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
