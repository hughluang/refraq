"""Catalog semantics (B) and joins (C) HTTP / service tests."""

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

from backend.admin.audit_store import get_audit_store, reset_audit_store  # noqa: E402
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
    get_catalog_store,
    reset_catalog_store,
)
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
    reset_audit_store()
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


def _seed_object(
    source_id: str,
    *,
    object_id: str = "obj_wo",
    col_a: str = "col_a",
    col_b: str = "col_b",
    business_name: str | None = "Work Order",
    col_a_business: str | None = "WO Id",
) -> CatalogObjectRecord:
    now = datetime.utcnow()
    record = CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        object_type="table",
        schema_name="dbo",
        name="WORK_ORDER",
        ddl="CREATE TABLE ...",
        is_present=True,
        business_name=business_name,
        business_description="Orders",
        last_structure_job_id="job_1",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=col_a,
                object_id=object_id,
                name="WO_ID",
                ordinal=0,
                data_type="NUMBER",
                nullable=False,
                is_present=True,
                business_name=col_a_business,
                business_description="PK",
                created_at=now,
                updated_at=now,
            ),
            CatalogColumnRecord(
                id=col_b,
                object_id=object_id,
                name="LINE_ID",
                ordinal=1,
                data_type="NUMBER",
                nullable=True,
                is_present=True,
                business_name=None,
                business_description=None,
                created_at=now,
                updated_at=now,
            ),
        ],
    )
    get_catalog_store().replace_structure_snapshot(
        source_id=source_id,
        job_id="job_1",
        objects=[record],
        schema_scope=None,
    )
    # restore semantics wiped by structure insert of brand-new object — seed via store after
    store = get_catalog_store()
    stored = store.get_object(object_id)
    assert stored is not None
    # Structure path preserves business_* on update, but first insert uses incoming values.
    # Our record already had semantics; for first insert Sql/Memory use incoming as-is.
    # Memory insert uses incoming wholesale — good. Re-fetch.
    return store.get_object(object_id)  # type: ignore[return-value]


def test_patch_object_semantics_omit_and_null_no_wipe(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])

    only_desc = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_description": "Updated desc"},
    )
    assert only_desc.status_code == 200, only_desc.text
    body = only_desc.json()["object"]
    assert body["business_name"] == "Work Order"
    assert body["business_description"] == "Updated desc"

    null_name = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_name": None},
    )
    assert null_name.status_code == 200, null_name.text
    body = null_name.json()["object"]
    assert body["business_name"] == "Work Order"
    assert body["business_description"] == "Updated desc"

    events, _ = get_audit_store().list_events(action="semantics.object_patch")
    assert events
    assert events[0].resource_type == "catalog_object"
    assert events[0].resource_id == obj.id
    assert events[0].result == "success"


def test_patch_column_semantics(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    col_id = obj.columns[0].id

    resp = client.patch(
        f"/columns/{col_id}/semantics",
        json={"business_name": "Work Order Id", "business_description": "Primary"},
    )
    assert resp.status_code == 200, resp.text
    col = resp.json()["column"]
    assert col["id"] == col_id
    assert col["business_name"] == "Work Order Id"
    assert col["business_description"] == "Primary"

    null_wipe = client.patch(
        f"/columns/{col_id}/semantics",
        json={"business_name": None},
    )
    assert null_wipe.status_code == 200
    assert null_wipe.json()["column"]["business_name"] == "Work Order Id"

    events, _ = get_audit_store().list_events(action="semantics.column_patch")
    assert events
    assert events[0].resource_id == col_id


def test_semantics_forbidden_without_write(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="ops",
        display_name="Ops",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    login = client.post("/auth/login", json={"account": "ops", "password": "secret"})
    assert login.status_code == 200

    resp = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_name": "x"},
    )
    assert resp.status_code == 403


def test_semantics_not_found(client: TestClient) -> None:
    missing_obj = client.patch(
        "/objects/obj_missing/semantics",
        json={"business_name": "x"},
    )
    assert missing_obj.status_code == 404
    assert missing_obj.json()["code"] == "CATALOG_OBJECT_NOT_FOUND"

    missing_col = client.patch(
        "/columns/col_missing/semantics",
        json={"business_name": "x"},
    )
    assert missing_col.status_code == 404
    assert missing_col.json()["code"] == "CATALOG_COLUMN_NOT_FOUND"


def test_join_upsert_list_delete_and_audit(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id

    bad = client.put(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "   "},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "JOIN_EVIDENCE_REQUIRED"

    self_loop = client.put(
        "/joins",
        json={"from_column_id": a, "to_column_id": a, "evidence": "same"},
    )
    assert self_loop.status_code == 400
    assert self_loop.json()["code"] == "JOIN_INVALID"

    created = client.put(
        "/joins",
        json={
            "from_column_id": a,
            "to_column_id": b,
            "evidence": "Verified FK in DDL",
        },
    )
    assert created.status_code == 200, created.text
    join = created.json()["join"]
    assert join["from_column_id"] == a
    assert join["to_column_id"] == b
    assert join["evidence"] == "Verified FK in DDL"
    assert join["id"].startswith("join_")
    join_id = join["id"]

    again = client.put(
        "/joins",
        json={
            "from_column_id": a,
            "to_column_id": b,
            "evidence": "Probe query succeeded",
        },
    )
    assert again.status_code == 200
    assert again.json()["join"]["id"] == join_id
    assert again.json()["join"]["evidence"] == "Probe query succeeded"

    listed = client.get(f"/objects/{obj.id}/joins")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == join_id

    events, _ = get_audit_store().list_events(action="join.upsert")
    assert events

    deleted = client.delete(f"/joins/{join_id}")
    assert deleted.status_code == 204

    listed2 = client.get(f"/objects/{obj.id}/joins")
    assert listed2.json()["items"] == []

    missing = client.delete(f"/joins/{join_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "CATALOG_JOIN_NOT_FOUND"

    del_events, _ = get_audit_store().list_events(action="join.delete")
    assert del_events


def test_join_cross_source_rejected(client: TestClient) -> None:
    s1 = _make_source(client, key="s1")
    s2 = _make_source(client, key="s2")
    o1 = _seed_object(s1["id"], object_id="obj_1", col_a="col_1a", col_b="col_1b")
    o2 = _seed_object(s2["id"], object_id="obj_2", col_a="col_2a", col_b="col_2b")

    resp = client.put(
        "/joins",
        json={
            "from_column_id": o1.columns[0].id,
            "to_column_id": o2.columns[0].id,
            "evidence": "looks similar",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "JOIN_CROSS_SOURCE"


def test_join_missing_column(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    resp = client.put(
        "/joins",
        json={
            "from_column_id": obj.columns[0].id,
            "to_column_id": "col_missing",
            "evidence": "evidence",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "CATALOG_COLUMN_NOT_FOUND"


def test_delete_source_clears_joins(client: TestClient) -> None:
    source = _make_source(client, key="del-joins")
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.put(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "fk"},
    )
    assert created.status_code == 200
    join_id = created.json()["join"]["id"]

    client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    deleted = client.delete(f"/sources/{source['id']}")
    assert deleted.status_code == 204

    missing = client.get(f"/objects/{obj.id}/joins")
    assert missing.status_code == 404
    assert get_catalog_store().get_join(join_id) is None


def test_browse_still_works_after_router_split(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    listed = client.get(f"/sources/{source['id']}/objects")
    assert listed.status_code == 200
    assert any(i["id"] == obj.id for i in listed.json()["items"])
    detail = client.get(f"/objects/{obj.id}")
    assert detail.status_code == 200
    assert detail.json()["object"]["business_name"] == "Work Order"
