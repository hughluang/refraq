"""Regression tests for locator identity continuity and engine cascade."""

from __future__ import annotations

import os
from datetime import datetime

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
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    apply_structure_snapshot,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.locators import format_object_locator  # noqa: E402
from backend.metadata.mcp_server import upsert_joins  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402


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


def _access() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "u",
        "password": "p",
        "ssl_mode": "require",
        "extra": {},
    }


def _make_source(client: TestClient, key: str = "mes-prod") -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "database_name": "MES",
            "engine": "postgresql",
            "access": _access(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


def _object(
    *,
    source_id: str,
    object_id: str,
    object_type: str,
    schema_name: str = "public",
    name: str = "mv_orders",
    business_name: str | None = "Orders MV",
    col_id: str = "col_id",
) -> CatalogObjectRecord:
    now = datetime.utcnow()
    locator = format_object_locator(
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
        schema_name=schema_name,
        object_type=object_type,
        name=name,
    )
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=locator,
        object_type=object_type,
        schema_name=schema_name,
        name=name,
        ddl=None,
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=business_name,
        business_description="kept",
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        time_semantics=None,
        status_semantics=None,
        relation_summary=None,
        business_domain=None,
        evidence_summary=None,
        confidence=None,
        open_questions=None,
        semantic_source="user_input",
        business_semantics_ready=True,
        semantics_updated_at=now,
        last_structure_job_id="job_seed",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=col_id,
                object_id=object_id,
                locator_key=f"col/postgresql/mes-prod/{schema_name}/{object_type}/{name}/column/id",
                name="id",
                ordinal=1,
                data_type="integer",
                nullable=False,
                default_value=None,
                comment=None,
                is_present=True,
                business_name="Id",
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source="user_input",
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
        ],
        foreign_keys=[],
        indexes=[],
    )


def test_view_to_materialized_view_preserves_identity(client: TestClient) -> None:
    source = _make_source(client)
    store = get_catalog_store()
    seed = _object(
        source_id=source["id"],
        object_id="obj_mv",
        object_type="view",
        col_id="col_mv_id",
    )
    store.replace_structure_snapshot(
        source_id=source["id"],
        job_id="job_1",
        objects=[seed],
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
    )
    before = store.get_object("obj_mv")
    assert before is not None
    assert before.object_type == "view"
    assert before.business_name == "Orders MV"
    col_id = before.columns[0].id

    incoming = _object(
        source_id=source["id"],
        object_id="obj_mv_new",
        object_type="materialized_view",
        col_id="col_mv_id_new",
        business_name=None,
    )
    apply_structure_snapshot(
        source_id=source["id"],
        job_id="job_2",
        collected=[incoming],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key=source["key"],
    )
    after = store.get_object("obj_mv")
    assert after is not None
    assert after.is_present is True
    assert after.object_type == "materialized_view"
    assert after.business_name == "Orders MV"
    assert after.columns[0].id == col_id
    assert "materialized_view" in after.locator_key
    assert store.get_object("obj_mv_new") is None


def test_engine_change_recomputes_catalog_locators(client: TestClient) -> None:
    source = _make_source(client)
    store = get_catalog_store()
    seed = _object(
        source_id=source["id"],
        object_id="obj_wo",
        object_type="table",
        name="work_order",
        col_id="col_wo",
    )
    store.replace_structure_snapshot(
        source_id=source["id"],
        job_id="job_1",
        objects=[seed],
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
    )
    before = store.get_object("obj_wo")
    assert before is not None
    assert before.locator_key.startswith("obj/postgresql/")

    patched = client.patch(
        f"/sources/{source['id']}",
        json={
            "engine": "mssql",
            "access": {
                "host": "127.0.0.1",
                "port": 1433,
                "username": "u",
                "password": "p",
                "ssl_mode": "disable",
                "extra": {},
            },
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["source"]["locator_key"].startswith("src/mssql/")

    after = store.get_object("obj_wo")
    assert after is not None
    assert after.id == "obj_wo"
    assert after.locator_key.startswith("obj/mssql/")
    assert after.columns[0].locator_key.startswith("col/mssql/")


def test_mcp_upsert_joins_reports_missing_endpoints(client: TestClient) -> None:
    import json
    from datetime import timedelta

    expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    tok = client.post("/tokens", json={"name": "join-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]

    payload = upsert_joins(
        authorization=f"Bearer {secret}",
        joins=[{"evidence": "no endpoints"}],
    )
    body = json.loads(payload)
    assert body["error"]["code"] == "JOIN_BATCH_EMPTY"
    assert body["skipped_count"] == 1
    assert body["skipped_joins"][0]["reason"] == "missing_endpoint"


def test_list_objects_pagination_defaults(client: TestClient) -> None:
    source = _make_source(client, key="paged")
    store = get_catalog_store()
    now = datetime.utcnow()
    objects = []
    for i in range(105):
        objects.append(
            CatalogObjectRecord(
                id=f"obj_{i}",
                source_id=source["id"],
                locator_key=f"obj/postgresql/paged/public/table/t{i}",
                object_type="table",
                schema_name="public",
                name=f"t{i}",
                ddl=None,
                comment=None,
                primary_key=None,
                is_present=True,
                business_name=None,
                business_description=None,
                object_category=None,
                grain_description=None,
                business_primary_key=None,
                time_semantics=None,
                status_semantics=None,
                relation_summary=None,
                business_domain=None,
                evidence_summary=None,
                confidence=None,
                open_questions=None,
                semantic_source=None,
                business_semantics_ready=False,
                semantics_updated_at=None,
                last_structure_job_id=None,
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[],
                foreign_keys=[],
                indexes=[],
            )
        )
    store.replace_structure_snapshot(
        source_id=source["id"],
        job_id="job_page",
        objects=objects,
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="paged",
    )
    first = client.get(f"/sources/{source['id']}/objects")
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 105
    assert body["limit"] == 100
    assert len(body["items"]) == 100

    second = client.get(f"/sources/{source['id']}/objects?offset=100")
    assert second.status_code == 200
    assert len(second.json()["items"]) == 5
