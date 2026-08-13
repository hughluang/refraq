"""Catalog semantics (B) and joins (C) HTTP / service tests."""

from __future__ import annotations

from backend.core.time import utc_now
import os
from datetime import datetime

import pytest
from dataclasses import replace
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
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.sources.service import require_source  # noqa: E402
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
        "database": "MES",
        "schema": "public",
        "extra": {},
    }


def _make_source(client: TestClient, key: str = "mes-prod") -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
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
    now = utc_now()
    line = CatalogObjectRecord(
        id="obj_line",
        source_id=source_id,
        locator_key="obj/postgresql/mes-prod/dbo/table/LINE",
        object_type="table",
        schema_name="dbo",
        name="LINE",
        ddl=None,
        comment=None,
        primary_key=["LINE_ID"],
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
        last_structure_job_id="job_1",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id="col_line_id",
                object_id="obj_line",
                locator_key="col/postgresql/mes-prod/dbo/table/LINE/column/LINE_ID",
                name="LINE_ID",
                ordinal=0,
                data_type="NUMBER",
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
    record = CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key="obj/postgresql/mes-prod/dbo/table/WORK_ORDER",
        object_type="table",
        schema_name="dbo",
        name="WORK_ORDER",
        ddl="CREATE TABLE ...",
        comment="Work order header",
        primary_key=["WO_ID"],
        is_present=True,
        business_name=business_name,
        business_description="Orders",
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=False,
        semantics_updated_at=None,
        last_structure_job_id="job_1",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=col_a,
                object_id=object_id,
                locator_key="col/postgresql/mes-prod/dbo/table/WORK_ORDER/column/WO_ID",
                name="WO_ID",
                ordinal=0,
                data_type="NUMBER",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=col_a_business,
                business_description="PK",
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            ),
            CatalogColumnRecord(
                id=col_b,
                object_id=object_id,
                locator_key="col/postgresql/mes-prod/dbo/table/WORK_ORDER/column/LINE_ID",
                name="LINE_ID",
                ordinal=1,
                data_type="NUMBER",
                nullable=True,
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
            ),
        ],
        indexes=[
            CatalogIndexRecord(
                name="ix_wo_id",
                columns=["WO_ID"],
                is_unique=True,
                is_present=True,
            )
        ],
    )
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="job_1",
        collected=[line, record],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    # restore semantics wiped by structure insert of brand-new object — seed via store after
    store = get_catalog_store()
    stored = store.get_object(object_id)
    assert stored is not None
    # Structure path preserves business_* on update, but first insert uses incoming values.
    # Our record already had semantics; for first insert Sql/Memory use incoming as-is.
    # Memory insert uses incoming wholesale — good. Re-fetch.
    return store.get_object(object_id)  # type: ignore[return-value]


def test_patch_object_semantics_omit_unchanged_present_null_clears(
    client: TestClient,
) -> None:
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
    assert body["business_name"] is None
    assert body["business_description"] == "Updated desc"

    events, _ = get_audit_store().list_events(action="semantics.object_patch")
    assert events
    assert events[0].resource_type == "catalog_object"
    assert events[0].resource_id == obj.id
    assert events[0].result == "success"
    assert "business_name" in (events[0].detail or {}).get("cleared", [])


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
    assert null_wipe.json()["column"]["business_name"] is None
    assert null_wipe.json()["column"]["business_description"] == "Primary"

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


def test_patch_object_open_questions_and_ready(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])

    with_q = client.patch(
        f"/objects/{obj.id}/semantics",
        json={
            "business_name": "Work Order",
            "business_description": "Orders",
            "open_questions": ["What is the grain?"],
        },
    )
    assert with_q.status_code == 200, with_q.text
    body = with_q.json()["object"]
    assert body["open_questions"] == ["What is the grain?"]
    assert body["business_semantics_ready"] is False
    assert body["semantic_source"] == "user_input"
    assert body["locator_key"]

    cleared = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"open_questions": []},
    )
    assert cleared.status_code == 200
    body = cleared.json()["object"]
    assert body["open_questions"] is None
    assert body["business_semantics_ready"] is True


def test_mcp_overwrites_existing_semantics(client: TestClient) -> None:
    from backend.metadata.catalog import service as catalog_service

    source = _make_source(client)
    obj = _seed_object(source["id"])
    patched = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_name": "Human Name", "business_description": "Human desc"},
    )
    assert patched.status_code == 200
    assert patched.json()["object"]["semantic_source"] == "user_input"

    record = catalog_service.patch_object_semantics(
        object_id=obj.id,
        data={
            "business_name": "Agent Name",
            "business_description": "Agent desc",
            "object_category": "transaction_fact",
        },
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert record.business_name == "Agent Name"
    assert record.business_description == "Agent desc"
    assert record.object_category == "transaction_fact"
    assert record.semantic_source == "mcp"


def test_batch_semantics_updated_count_only_on_apply(client: TestClient) -> None:
    from backend.metadata.catalog import service as catalog_service

    source = _make_source(client)
    obj = _seed_object(source["id"])
    col_name = obj.columns[0].name
    empty = catalog_service.set_column_semantics_batch(
        object_id=obj.id,
        columns=[{"column_name": col_name}],
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert empty["updated_count"] == 0
    assert empty["skipped_columns"][0]["reason"] == "no_changes"

    applied = catalog_service.set_column_semantics_batch(
        object_id=obj.id,
        columns=[{"column_name": col_name, "business_name": "WO ID"}],
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert applied["updated_count"] == 1
    assert applied["skipped_columns"] == []


def test_join_response_includes_depth_fields(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.put(
        "/joins",
        json={
            "from_column_id": a,
            "to_column_id": b,
            "evidence": "Verified FK in DDL",
            "join_kind": "LEFT",
        },
    )
    assert created.status_code == 200, created.text
    join = created.json()["join"]
    assert join["join_kind"] == "LEFT"
    assert join["origin"] == "human"
    assert join["join_expression"]
    assert join["from_column_locator_key"]
    assert join["to_column_locator_key"]


def test_object_detail_exposes_structure_facts(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    # Attach FK on a second structure pass (LINE already present from seed).
    store = get_catalog_store()
    current = store.get_object(obj.id)
    assert current is not None
    with_fk = replace(
        current,
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_wo_line",
                columns=["LINE_ID"],
                ref_schema="dbo",
                ref_table="LINE",
                ref_columns=["LINE_ID"],
                is_present=True,
            )
        ],
    )
    line = store.get_object("obj_line")
    assert line is not None
    apply_structure_snapshot(
        source=require_source(source["id"]),
        job_id="job_2",
        collected=[line, with_fk],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )

    detail = client.get(f"/objects/{obj.id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()["object"]
    assert body["comment"] == "Work order header"
    assert body["primary_key"] == ["WO_ID"]
    assert len(body["foreign_keys"]) == 1
    assert body["foreign_keys"][0]["name"] == "fk_wo_line"
    assert body["foreign_keys"][0]["ref_table"] == "LINE"
    assert len(body["indexes"]) == 1
    assert body["indexes"][0]["is_unique"] is True

    listed = client.get(f"/sources/{source['id']}/objects")
    assert listed.status_code == 200
    item = next(i for i in listed.json()["items"] if i["id"] == obj.id)
    assert item["foreign_keys"] == []
    assert item["indexes"] == []
    assert item["columns"] == []


def test_patch_columns_semantics_batch_http(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    resp = client.patch(
        f"/objects/{obj.id}/columns/semantics",
        json={
            "columns": [
                {
                    "column_name": "LINE_ID",
                    "business_name": "Line",
                    "business_description": "Production line",
                    "column_semantics": {
                        "semantic_type": "id",
                        "value_pattern": None,
                        "unit": None,
                    },
                    "enum_catalog": [
                        {"code": "A", "label": "Line A", "description": None}
                    ],
                },
                {"column_name": "MISSING", "business_name": "x"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated_count"] == 1
    assert body["requested_count"] == 2
    assert body["skipped_columns"][0]["column_name"] == "MISSING"
    line = next(c for c in body["object"]["columns"] if c["name"] == "LINE_ID")
    assert line["business_name"] == "Line"
    assert line["semantic_source"] == "user_input"
    assert line["enum_catalog"][0]["code"] == "A"
    assert line["column_semantics"]["semantic_type"] == "id"


def test_http_clears_grain_category_domain_and_blank_name(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    domain = client.post(
        "/business-domains",
        json={"code": "mes", "name": "MES"},
    )
    assert domain.status_code == 201, domain.text

    filled = client.patch(
        f"/objects/{obj.id}/semantics",
        json={
            "grain_description": "one row is one WO",
            "object_category": "transaction_fact",
            "business_domain_code": "mes",
            "business_name": "Work Order",
            "business_description": "Orders",
        },
    )
    assert filled.status_code == 200, filled.text
    body = filled.json()["object"]
    assert body["grain_description"] == "one row is one WO"
    assert body["object_category"] == "transaction_fact"
    assert body["business_domain"]["code"] == "mes"

    cleared = client.patch(
        f"/objects/{obj.id}/semantics",
        json={
            "grain_description": None,
            "object_category": None,
            "business_domain_code": None,
            "business_name": "  ",
        },
    )
    assert cleared.status_code == 200, cleared.text
    body = cleared.json()["object"]
    assert body["grain_description"] is None
    assert body["object_category"] is None
    assert body["business_domain"] is None
    assert body["business_name"] is None
    assert body["business_description"] == "Orders"
    assert body["business_semantics_ready"] is False


def test_http_clears_column_semantics_blob_and_enum_catalog(
    client: TestClient,
) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    col_id = obj.columns[0].id

    filled = client.patch(
        f"/columns/{col_id}/semantics",
        json={
            "column_semantics": {
                "semantic_type": "id",
                "value_pattern": None,
                "unit": None,
            },
            "enum_catalog": [{"code": "A", "label": "A", "description": None}],
        },
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["column"]["column_semantics"]["semantic_type"] == "id"
    assert filled.json()["column"]["enum_catalog"][0]["code"] == "A"

    cleared = client.patch(
        f"/columns/{col_id}/semantics",
        json={"column_semantics": None, "enum_catalog": []},
    )
    assert cleared.status_code == 200, cleared.text
    col = cleared.json()["column"]
    assert col["column_semantics"] is None
    assert col["enum_catalog"] is None


def test_mcp_strip_empty_does_not_clear_existing(client: TestClient) -> None:
    from backend.metadata.catalog import service as catalog_service
    from backend.metadata.mcp_server import _mcp_strip_empty

    source = _make_source(client)
    obj = _seed_object(source["id"])
    assert _mcp_strip_empty(
        {
            "grain_description": None,
            "business_name": "  ",
            "open_questions": [],
            "evidence_summary": ["ddl"],
        }
    ) == {"evidence_summary": ["ddl"]}

    seeded = client.patch(
        f"/objects/{obj.id}/semantics",
        json={
            "business_name": "Human Name",
            "business_description": "Human desc",
            "grain_description": "one row is one WO",
            "object_category": "transaction_fact",
        },
    )
    assert seeded.status_code == 200

    stripped = _mcp_strip_empty(
        {
            "business_name": "",
            "grain_description": None,
            "object_category": None,
            "open_questions": [],
            "business_primary_key": [],
        }
    )
    assert stripped == {}
    unchanged = catalog_service.patch_object_semantics(
        object_id=obj.id,
        data=stripped,
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert unchanged.business_name == "Human Name"
    assert unchanged.grain_description == "one row is one WO"
    assert unchanged.object_category == "transaction_fact"

    col_name = obj.columns[0].name
    client.patch(
        f"/columns/{obj.columns[0].id}/semantics",
        json={"business_name": "WO Id Kept"},
    )
    stripped_cols = [
        {
            "column_name": col_name,
            **_mcp_strip_empty(
                {
                    "business_name": None,
                    "business_description": "  ",
                    "column_semantics": None,
                    "enum_catalog": [],
                }
            ),
        }
    ]
    batch = catalog_service.set_column_semantics_batch(
        object_id=obj.id,
        columns=stripped_cols,
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert batch["updated_count"] == 0
    assert batch["skipped_columns"][0]["reason"] == "no_changes"
    col = catalog_service.require_column(obj.columns[0].id)
    assert col.business_name == "WO Id Kept"
