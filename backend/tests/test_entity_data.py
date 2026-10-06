"""Entity Data API integration tests against a real Postgres head table."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.entity.table_name import compose_physical_table_name as compose_physical
from backend.entity.records import AttributeRecord, attribute_to_dict
from backend.entity.table_port import PostgresEntityTablePort

pytestmark = pytest.mark.integration

INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _ensure_db(database_url: str) -> None:
    url = make_url(database_url)
    admin = create_engine(
        url.set(database=make_url(_MAINTENANCE_DATABASE_URL).database),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture()
def data_client(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    _ensure_db(INTEGRATION_DATABASE_URL)

    os.environ["REFRAQ_STORE_BACKEND"] = "memory"
    os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")

    monkeypatch.setenv("ENTITY_DATABASE_URL", INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")

    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import get_entity_engine, reset_entity_engine
    from backend.entity.data import sql as data_sql
    from backend.admin.roles import create_role, seed_roles
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
    from backend.entity.store import get_entity_store, reset_entity_store
    from backend.main import app

    reset_settings_cache()
    reset_entity_engine()
    reset_entity_store()
    monkeypatch.setattr(data_sql, "require_entity_capacity", get_entity_engine)

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    reader = create_role(
        roles,
        key="data_reader",
        name="Data reader",
        permissions=["console:access", "entity:data_read", "tokens:write"],
    )
    get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )

    stem = f"mat_{uuid.uuid4().hex[:10]}"
    version_id = new_version_id()
    physical, _ = compose_physical(stem, 1, version_id)
    attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            max_length=32,
        ),
        AttributeRecord(name="qty", type="integer", required=False),
        AttributeRecord(name="flag", type="boolean"),
        AttributeRecord(name="note", type="text"),
    ]
    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=stem,
        name="Material",
        description="Stock",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=version_id,
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)

    port = PostgresEntityTablePort()
    schema = "public"
    port.create_physical_table(schema, physical, attrs)
    port.swap_stem_view(schema, stem, physical=physical, expected_target=None)

    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        yield client, stem, physical, entity.id

    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    with engine.begin() as conn:
        conn.execute(text(f'DROP VIEW IF EXISTS "{schema}"."{stem}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{physical}"'))
    reset_entity_engine()
    reset_entity_store()
    reset_settings_cache()


def test_create_get_update_delete_query_and_upsert(data_client) -> None:
    client, stem, _physical, entity_id = data_client

    # id path must not resolve on the data plane
    bad = client.post(f"/entities/{entity_id}/create", json={"values": {"sku": "X"}})
    assert bad.status_code == 404
    assert bad.json()["code"] == "ENTITY_NOT_FOUND"

    schema = client.post(f"/entities/{stem}/schema", json={})
    assert schema.status_code == 200
    attr_names = {item["name"] for item in schema.json()["attributes"]}

    created = client.post(
        f"/entities/{stem}/create",
        json={"values": {"sku": "A1", "qty": 3, "flag": True, "note": "n1"}},
    )
    assert created.status_code == 201, created.text
    row = created.json()["row"]
    assert set(row.keys()) - {"row_id"} == attr_names
    assert row["sku"] == "A1"
    row_id = row["row_id"]

    got = client.post(f"/entities/{stem}/get", json={"row_id": row_id})
    assert got.status_code == 200
    assert got.json()["row"]["sku"] == "A1"

    missing = client.post(f"/entities/{stem}/get", json={"row_id": 999999})
    assert missing.status_code == 404
    assert missing.json()["code"] == "ENTITY_ROW_NOT_FOUND"

    updated = client.post(
        f"/entities/{stem}/update",
        json={"row_id": row_id, "values": {"qty": 9}},
    )
    assert updated.status_code == 200
    assert updated.json()["row"]["qty"] == 9

    conflict = client.post(
        f"/entities/{stem}/create",
        json={"values": {"sku": "A1", "flag": False}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ENTITY_ROW_CONFLICT"

    many = client.post(
        f"/entities/{stem}/create-many",
        json={
            "items": [
                {"values": {"sku": "B1", "qty": 1, "flag": False}},
                {"values": {"sku": "B2", "qty": 2, "flag": None}},
            ]
        },
    )
    assert many.status_code == 201, many.text
    rows = many.json()["rows"]
    assert [item["sku"] for item in rows] == ["B1", "B2"]

    empty_many = client.post(f"/entities/{stem}/create-many", json={"items": []})
    assert empty_many.status_code == 422
    assert empty_many.json()["code"] == "REQUEST_INVALID"

    dup_many = client.post(
        f"/entities/{stem}/create-many",
        json={
            "items": [
                {"values": {"sku": "C1", "flag": True}},
                {"values": {"sku": "C1", "flag": False}},
            ]
        },
    )
    assert dup_many.status_code == 409

    offset = client.post(
        f"/entities/{stem}/query",
        json={"filters": {"field": "sku", "op": "eq", "value": "A1"}},
    )
    assert offset.status_code == 200
    page = offset.json()
    assert page["total"] == 1
    assert page["items"][0]["sku"] == "A1"
    assert "offset" in page

    no_total = client.post(
        f"/entities/{stem}/query",
        json={"include_total": False, "limit": 10},
    )
    assert no_total.status_code == 200
    assert no_total.json()["total"] is None

    keyset = client.post(
        f"/entities/{stem}/query",
        json={"after_row_id": None, "limit": 1},
    )
    assert keyset.status_code == 200
    kpage = keyset.json()
    assert "next_after_row_id" in kpage
    assert "total" not in kpage
    assert len(kpage["items"]) == 1

    mixed = client.post(
        f"/entities/{stem}/query",
        json={"after_row_id": 1, "offset": 0},
    )
    assert mixed.status_code == 422

    cursor = client.post(f"/entities/{stem}/query", json={"cursor": "x"})
    assert cursor.status_code == 422

    ne = client.post(
        f"/entities/{stem}/query",
        json={"filters": {"field": "sku", "op": "ne", "value": "A1"}},
    )
    assert ne.status_code == 200
    assert all(item["sku"] != "A1" for item in ne.json()["items"])

    contains = client.post(
        f"/entities/{stem}/query",
        json={"filters": {"field": "note", "op": "contains", "value": "n"}},
    )
    assert contains.status_code == 200

    updated_where = client.post(
        f"/entities/{stem}/update-where",
        json={
            "filters": {"field": "sku", "op": "eq", "value": "B1"},
            "set": {"qty": 42},
        },
    )
    assert updated_where.status_code == 200
    assert updated_where.json()["affected"] == 1

    empty_filter = client.post(
        f"/entities/{stem}/delete-where",
        json={"filters": {"all": []}},
    )
    assert empty_filter.status_code == 422
    assert empty_filter.json()["code"] == "ENTITY_ROW_INVALID"

    upsert_new = client.post(
        f"/entities/{stem}/upsert",
        json={"key": "sku", "values": {"sku": "U1", "qty": 5, "flag": True}},
    )
    assert upsert_new.status_code == 201
    upsert_upd = client.post(
        f"/entities/{stem}/upsert",
        json={"key": "sku", "values": {"sku": "U1", "qty": 7, "flag": True}},
    )
    assert upsert_upd.status_code == 200
    assert upsert_upd.json()["row"]["qty"] == 7

    deleted = client.post(f"/entities/{stem}/delete", json={"row_id": row_id})
    assert deleted.status_code == 204
    assert client.post(f"/entities/{stem}/get", json={"row_id": row_id}).status_code == 404


def test_business_key_addressing_reference_and_upsert_default(data_client) -> None:
    client, _stem, _physical, _entity_id = data_client
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
    from backend.entity.store import get_entity_store
    from backend.entity.table_port import PostgresEntityTablePort

    now = datetime.now(timezone.utc)
    supplier_id = new_entity_id()
    supplier_version = new_version_id()
    supplier_stem = f"sup_{uuid.uuid4().hex[:10]}"
    supplier_physical, _ = compose_physical(supplier_stem, 1, supplier_version)
    supplier_attrs = [
        AttributeRecord(
            name="code",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=16,
        )
    ]
    material_stem = f"lnk_{uuid.uuid4().hex[:10]}"
    material_version = new_version_id()
    material_physical, _ = compose_physical(material_stem, 1, material_version)
    material_id = new_entity_id()
    material_attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
        ),
        AttributeRecord(
            name="supplier_code",
            type="reference",
            required=False,
            target_entity_id=supplier_id,
            reference_key_type="string",
            reference_max_length=16,
        ),
    ]
    store = get_entity_store()
    store.create_entity(
        BusinessEntityRecord(
            id=supplier_id,
            table_name=supplier_stem,
            name="Supplier",
            description="Party",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        EntityVersionRecord(
            id=supplier_version,
            entity_id=supplier_id,
            version=1,
            attributes=list(supplier_attrs),
            materialized_attributes=[
                attribute_to_dict(item) for item in supplier_attrs
            ],
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    store.create_entity(
        BusinessEntityRecord(
            id=material_id,
            table_name=material_stem,
            name="Linked",
            description="Has a reference",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        EntityVersionRecord(
            id=material_version,
            entity_id=material_id,
            version=1,
            attributes=list(material_attrs),
            materialized_attributes=[
                attribute_to_dict(item) for item in material_attrs
            ],
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            reference_snapshots={
                "supplier_code": {
                    "attribute": "code",
                    "type": "string",
                    "max_length": 16,
                }
            },
            created_at=now,
            updated_at=now,
        ),
    )
    port = PostgresEntityTablePort()
    port.create_physical_table("public", supplier_physical, supplier_attrs)
    port.swap_stem_view(
        "public", supplier_stem, physical=supplier_physical, expected_target=None
    )
    port.create_physical_table("public", material_physical, material_attrs)
    port.swap_stem_view(
        "public", material_stem, physical=material_physical, expected_target=None
    )

    created = client.post(
        f"/entities/{material_stem}/create",
        json={"values": {"sku": "M1", "supplier_code": "S1"}},
    )
    assert created.status_code == 201, created.text
    assert created.json()["row"]["supplier_code"] == "S1"

    by_key = client.post(
        f"/entities/{material_stem}/get", json={"business_key": "M1"}
    )
    assert by_key.status_code == 200, by_key.text
    assert by_key.json()["row"]["sku"] == "M1"

    blocked = client.post(
        f"/entities/{material_stem}/update",
        json={"business_key": "M1", "values": {"sku": "M2"}},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "ENTITY_ROW_INVALID"

    contains = client.post(
        f"/entities/{material_stem}/query",
        json={
            "filters": {
                "field": "supplier_code",
                "op": "contains",
                "value": "S",
            }
        },
    )
    assert contains.status_code == 200, contains.text
    assert contains.json()["total"] == 1

    upserted = client.post(
        f"/entities/{material_stem}/upsert",
        json={"values": {"sku": "M1", "supplier_code": "S2"}},
    )
    assert upserted.status_code == 200, upserted.text
    assert upserted.json()["row"]["supplier_code"] == "S2"

    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    with engine.begin() as conn:
        conn.execute(text(f'DROP VIEW IF EXISTS "public"."{supplier_stem}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS "public"."{supplier_physical}"'))
        conn.execute(text(f'DROP VIEW IF EXISTS "public"."{material_stem}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS "public"."{material_physical}"'))


def test_pat_data_read_can_schema_and_query(data_client) -> None:
    client, stem, _physical, _entity_id = data_client
    client.post(
        f"/entities/{stem}/create",
        json={"values": {"sku": "P1", "qty": 1}},
    )
    client.post("/auth/logout")
    assert (
        client.post(
            "/auth/login", json={"account": "reader", "password": "secret"}
        ).status_code
        == 200
    )
    from datetime import timedelta

    from backend.core.time import format_instant, utc_now

    expires = format_instant(utc_now() + timedelta(days=1))
    tok = client.post("/tokens", json={"name": "data-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]
    client.post("/auth/logout")

    headers = {"Authorization": f"Bearer {secret}"}
    schema = client.post(
        f"/entities/{stem}/schema", json={}, headers=headers
    )
    assert schema.status_code == 200
    query = client.post(
        f"/entities/{stem}/query",
        json={"after_row_id": None, "limit": 10},
        headers=headers,
    )
    assert query.status_code == 200
    write = client.post(
        f"/entities/{stem}/create",
        json={"values": {"sku": "P2"}},
        headers=headers,
    )
    assert write.status_code == 403


def test_type_roundtrip_create_and_create_many(data_client) -> None:
    client, _stem, _physical, _entity_id = data_client
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.table_name import compose_physical_table_name as compose_physical
    from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
    from backend.entity.store import get_entity_store
    from backend.entity.table_port import PostgresEntityTablePort

    stem2 = f"rt_{uuid.uuid4().hex[:10]}"
    version_id = new_version_id()
    physical, _ = compose_physical(stem2, 1, version_id)
    attrs = [
        AttributeRecord(
            name="code", type="string", required=True, unique=True, max_length=16
        ),
        AttributeRecord(name="amount", type="decimal", precision=10, scale=2),
        AttributeRecord(name="ratio", type="number"),
        AttributeRecord(name="on_date", type="date"),
        AttributeRecord(name="at_time", type="time"),
        AttributeRecord(name="payload", type="json"),
    ]
    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=stem2,
        name="Roundtrip",
        description="Types",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=version_id,
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    port = PostgresEntityTablePort()
    port.create_physical_table("public", physical, attrs)
    try:
        created = client.post(
            f"/entities/{stem2}/create",
            json={
                "values": {
                    "code": "R1",
                    "amount": "12.50",
                    "ratio": 1.5,
                    "on_date": "2024-01-02",
                    "at_time": "13:45:01",
                    "payload": {"a": [1, True]},
                }
            },
        )
        assert created.status_code == 201, created.text
        row = created.json()["row"]
        assert row["amount"] == "12.50"
        assert row["ratio"] == 1.5
        assert row["on_date"] == "2024-01-02"
        assert row["at_time"].startswith("13:45:01")
        assert row["payload"] == {"a": [1, True]}

        many = client.post(
            f"/entities/{stem2}/create-many",
            json={
                "items": [
                    {"values": {"code": "R2", "amount": 3, "ratio": 0.25}},
                    {"values": {"code": "R3", "payload": None}},
                ]
            },
        )
        assert many.status_code == 201, many.text
        assert [item["code"] for item in many.json()["rows"]] == ["R2", "R3"]
    finally:
        engine = get_entity_engine()
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "public"."{physical}"'))
