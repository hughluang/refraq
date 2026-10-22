"""Entity Data API integration tests against a real Postgres head table.

Each test runs on a throwaway bootstrapped entity database: writes use the owner
pool, reads use the ``refraq_reader`` pool through the seeded profile views.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.entity.table_name import compose_physical_table_name as compose_physical
from backend.entity.records import AttributeRecord, attribute_to_dict
from backend.tests.entity_access_oracle import prepare_legacy_entity
from backend.entity.table_port import PostgresEntityTablePort
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

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


@pytest.fixture()
def data_client(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_edata") as urls:
        yield from _serve(monkeypatch, urls)


def _serve(monkeypatch: pytest.MonkeyPatch, urls):
    os.environ["REFRAQ_STORE_BACKEND"] = "memory"
    os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")

    monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
    monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")

    from backend.core.config import get_settings, reset_settings_cache
    from backend.entity.access import enforce
    from backend.entity.entity_db import (
        get_entity_engine,
        get_entity_reader_engine,
        reset_entity_engine,
    )
    from backend.entity.data import sql as data_sql
    from backend.admin.roles import create_role, seed_roles
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
    from backend.entity.store import get_entity_store, reset_entity_store
    from backend.entity.table_port import bind_entity_table_port
    from backend.main import app

    reset_settings_cache()
    reset_entity_engine()
    reset_entity_store()
    monkeypatch.setattr(data_sql, "require_entity_capacity", get_entity_engine)
    monkeypatch.setattr(data_sql, "require_entity_reader_capacity", get_entity_reader_engine)
    signing = get_settings().model_copy(update={"store_backend": "persistent"})
    monkeypatch.setattr(enforce, "get_settings", lambda: signing)
    bind_entity_table_port(PostgresEntityTablePort())

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
    schema = "entity_data"
    port.create_physical_table(schema, physical, attrs)
    port.swap_stem_view(schema, stem, physical=physical, expected_target=None)
    prepare_legacy_entity(entity.id)

    try:
        with TestClient(app) as client:
            login = client.post(
                "/auth/login", json={"account": "admin", "password": "secret"}
            )
            assert login.status_code == 200, login.text
            yield client, stem, physical, entity.id
    finally:
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
    port.create_physical_table("entity_data", supplier_physical, supplier_attrs)
    port.swap_stem_view(
        "entity_data", supplier_stem, physical=supplier_physical, expected_target=None
    )
    port.create_physical_table("entity_data", material_physical, material_attrs)
    port.swap_stem_view(
        "entity_data", material_stem, physical=material_physical, expected_target=None
    )
    prepare_legacy_entity(supplier_id)
    prepare_legacy_entity(material_id)

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

    blank_match = client.post(
        f"/entities/{material_stem}/query",
        json={"filters": {"field": "sku", "op": "eq", "value": ""}},
    )
    assert blank_match.status_code == 200, blank_match.text
    assert blank_match.json()["total"] == 0

    upserted = client.post(
        f"/entities/{material_stem}/upsert",
        json={"values": {"sku": "M1", "supplier_code": "S2"}},
    )
    assert upserted.status_code == 200, upserted.text
    assert upserted.json()["row"]["supplier_code"] == "S2"


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
    port.create_physical_table("entity_data", physical, attrs)
    prepare_legacy_entity(entity.id)
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


def test_reads_need_the_reader_role_and_a_signed_context(data_client) -> None:
    client, stem, _physical, entity_id = data_client
    from sqlalchemy.exc import ProgrammingError

    from backend.entity.access.store import get_access_store
    from backend.entity.entity_db import get_entity_engine, get_entity_reader_engine

    created = client.post(f"/entities/{stem}/create", json={"values": {"sku": "V1"}})
    assert created.status_code == 201, created.text
    row_id = created.json()["row"]["row_id"]
    got = client.post(f"/entities/{stem}/get", json={"row_id": row_id})
    assert got.status_code == 200, got.text
    views = {item.view_name for item in get_access_store().bindings(entity_id)}
    assert views
    view = sorted(views)[0]
    with get_entity_engine().connect() as conn:
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text(f'SELECT 1 FROM "entity_access"."{view}"'))
    with get_entity_reader_engine().connect() as conn:
        for name in views:
            seen = conn.execute(text(f'SELECT count(*) FROM "entity_access"."{name}"'))
            assert seen.scalar_one() == 0


def test_masked_writer_never_sees_the_raw_value(data_client) -> None:
    client, stem, _physical, entity_id = data_client
    from backend.admin.roles import create_role
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.entity.access.plan import load_head
    from backend.entity.access.service import create_grant, create_profile, put_ladder
    from backend.entity.access.views import rebuild_entity_views

    raw = "card-1234-5678"
    created = client.post(
        f"/entities/{stem}/create", json={"values": {"sku": "M1", "note": raw}}
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["row"]["row_id"]

    role = create_role(
        get_role_store(),
        key="masked_writer",
        name="Masked writer",
        permissions=["console:access", "entity:data_read", "entity:data_write"],
    )
    masker = get_user_store().create_user(
        account="masker",
        display_name="Masker",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    ids = {attr.name: attr.attribute_id for attr in load_head(entity_id).attributes}
    put_ladder(
        entity_id,
        ids["note"],
        [
            {"key": "clear", "mode": "clear"},
            {"key": "last4", "mode": {"type": "partial", "keep_first": 0, "keep_last": 4}},
        ],
        actor_user_id=masker.id,
        actor_token_id=None,
    )
    profile = create_profile(
        entity_id,
        key="masked_note",
        name="Masked note",
        description=None,
        columns=[
            {"attribute_id": ids["sku"], "level": "clear"},
            {"attribute_id": ids["qty"], "level": "clear"},
            {"attribute_id": ids["flag"], "level": "clear"},
            {"attribute_id": ids["note"], "level": "last4"},
        ],
        actor_user_id=masker.id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": masker.id},
        profile_id=profile["profile"]["id"],
        row_rule=None,
        actions=["read", "write"],
        status="active",
        valid_until=None,
        actor_user_id=masker.id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity_id)

    client.post("/auth/logout")
    login = client.post("/auth/login", json={"account": "masker", "password": "secret"})
    assert login.status_code == 200, login.text

    updated = client.post(
        f"/entities/{stem}/update", json={"row_id": row_id, "values": {"qty": 5}}
    )
    assert updated.status_code == 200, updated.text
    row = updated.json()["row"]
    assert row["qty"] == 5
    assert row["note"] != raw
    assert row["note"].endswith("5678")
    assert raw not in updated.text
    got = client.post(f"/entities/{stem}/get", json={"row_id": row_id})
    assert got.status_code == 200, got.text
    assert raw not in got.text
    denied = client.post(
        f"/entities/{stem}/update", json={"row_id": row_id, "values": {"note": "x"}}
    )
    assert denied.status_code == 403, denied.text


def test_write_rows_upsert_is_idempotent_and_channel_run_writes(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.runs import start_run
    from backend.channel.tasks import run_job
    from backend.entity.access.seed import ensure_system_grant
    from backend.entity.access.views import rebuild_entity_views
    from backend.entity.lifecycle import latest_published_of
    from backend.entity.rows import read_rows, write_rows
    from backend.entity.store import get_entity_store
    from backend.jobs.store import get_job_store

    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    first = write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=[{"sku": "RUN1", "qty": 2, "note": "keep"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert first.inserted == 1
    second = write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=[{"sku": "RUN1", "qty": 2, "note": "keep"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert second.unchanged == 1
    rows, _total = read_rows(entity_id, filters=[], user=admin, limit=50)
    kept = next(row for row in rows if row["sku"] == "RUN1")
    assert kept["note"] == "keep"

    version = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert version is not None
    ensure_system_grant(entity_id, list(version.attributes))
    rebuild_entity_views(entity_id)

    from backend.channel.service import create_channel, save_draft

    created = create_channel(
        name="Fill",
        description=None,
        actor_user_id=admin.id,
        actor_token_id=None,
    )
    graph = {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "run_manually",
                "type": "trigger.manual",
                "name": "Run manually",
                "position": {"x": 0, "y": 0},
                "config": {"payload": {}},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_write",
                "ref": "write_materials",
                "type": "write.entity",
                "name": "Write materials",
                "position": {"x": 200, "y": 0},
                "config": {
                    "entity_id": entity_id,
                    "mode": "upsert",
                    "match_key": "sku",
                    "source": '[{"sku": "RUN2", "qty": 9, "note": "from-run"}]',
                    "mapping": [
                        {"attribute": "sku", "key": "sku"},
                        {"attribute": "qty", "key": "qty"},
                        {"attribute": "note", "key": "note"},
                    ],
                    "on_incompatible_head": "fail",
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_1",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_write", "port": "main"},
            }
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    save_draft(
        channel_id=created.id,
        base_revision=created.draft_revision,
        graph=graph,
        actor_user_id=admin.id,
        actor_token_id=None,
    )

    previous = set_dispatcher(run_job)
    try:
        job, _record = start_run(
            channel_id=created.id,
            target="draft",
            ignore_checkpoints=False,
            actor=admin,
            actor_token_id=None,
        )
    finally:
        set_dispatcher(previous)
    finished = get_job_store().get(job.id)
    assert finished is not None
    assert finished.status == "succeeded", finished.error_summary
    rows, _total = read_rows(entity_id, filters=[], user=admin, limit=50)
    written = next(row for row in rows if row["sku"] == "RUN2")
    assert written["qty"] == 9
    assert written["note"] == "from-run"


def _publish_entity(attrs: list[AttributeRecord]) -> str:
    from backend.entity.access.views import rebuild_entity_views
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
    from backend.entity.store import get_entity_store
    from backend.entity.table_port import PostgresEntityTablePort
    from backend.tests.entity_access_oracle import prepare_legacy_entity

    stem = f"mat_{uuid.uuid4().hex[:10]}"
    version_id = new_version_id()
    physical, _ = compose_physical(stem, 1, version_id)
    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=stem,
        name="Typed",
        description="Typed values",
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
    port.create_physical_table("entity_data", physical, attrs)
    port.swap_stem_view("entity_data", stem, physical=physical, expected_target=None)
    prepare_legacy_entity(entity.id)
    rebuild_entity_views(entity.id)
    return entity.id


_TYPED_ROW = {
    "code": "A",
    "payload": {"n": 1, "ok": True},
    "when": "2020-01-02",
    "at": "13:05:00",
    "moment": "2020-01-02T13:05:00Z",
    "amount": "1.50",
}


def test_equal_json_date_time_timestamp_and_decimal_count_as_unchanged(data_client) -> None:
    from backend.admin.user_store import get_user_store
    from backend.entity.rows import read_rows, write_rows

    entity_id = _publish_entity(
        [
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
            AttributeRecord(name="payload", type="json"),
            AttributeRecord(name="when", type="date"),
            AttributeRecord(name="at", type="time"),
            AttributeRecord(name="moment", type="timestamp"),
            AttributeRecord(name="amount", type="decimal", precision=10, scale=2),
        ]
    )
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    created = write_rows(
        entity_id,
        mode="upsert",
        match_key="code",
        rows=[dict(_TYPED_ROW)],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert created.inserted == 1
    again = write_rows(
        entity_id,
        mode="upsert",
        match_key="code",
        rows=[dict(_TYPED_ROW)],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (again.inserted, again.updated, again.unchanged, again.deleted, again.unmatched) == (
        0,
        0,
        1,
        0,
        0,
    )
    rows, _total = read_rows(entity_id, filters=[], user=admin, limit=10)
    stored = next(row for row in rows if row["code"] == "A")
    assert stored["payload"] == {"n": 1, "ok": True}
    assert stored["when"] == "2020-01-02"
    assert stored["at"] == "13:05:00"
    assert stored["moment"] == "2020-01-02T13:05:00Z"
    assert stored["amount"] == "1.50"


def test_chunk_iterator_matches_the_same_rows_as_a_list(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    rows = [
        {"sku": "C1", "qty": 1, "note": "a"},
        {"sku": "C2", "qty": 2, "note": "b"},
    ]
    listed = write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=rows,
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (listed.inserted, listed.updated, listed.unchanged, listed.deleted, listed.unmatched) == (
        2,
        0,
        0,
        0,
        0,
    )
    chunked = write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=iter([rows[:1], rows[1:]]),
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (chunked.inserted, chunked.updated, chunked.unchanged, chunked.deleted, chunked.unmatched) == (
        0,
        0,
        2,
        0,
        0,
    )
    changed = write_rows(
        entity_id,
        mode="update",
        match_key="sku",
        rows=iter([[{"sku": "C1", "qty": 9}], [{"sku": "GONE", "qty": 1}]]),
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (changed.inserted, changed.updated, changed.unchanged, changed.deleted, changed.unmatched) == (
        0,
        1,
        0,
        0,
        1,
    )
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    kept = next(row for row in stored if row["sku"] == "C1")
    assert kept["qty"] == 9
    assert kept["note"] == "a"
    removed = write_rows(
        entity_id,
        mode="delete",
        match_key="sku",
        rows=[{"sku": "C2"}, {"sku": "MISSING"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (removed.deleted, removed.unmatched) == (1, 1)
    empty = write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=[],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert (empty.inserted, empty.updated, empty.unchanged, empty.deleted, empty.unmatched) == (
        0,
        0,
        0,
        0,
        0,
    )


def test_bad_row_in_the_last_chunk_leaves_the_target_unchanged(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    def chunks():
        yield [{"sku": "GOOD", "qty": 1, "note": "keep"}]
        yield [{"sku": "BAD", "qty": "nope", "note": "drop"}]

    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=chunks(),
            user=admin,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "invalid"
    assert raised.value.row_index == 1
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert [row["sku"] for row in stored] == []


def test_ordinal_pairs_keep_that_ord_and_roll_back(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    def chunks():
        yield [(1, {"sku": "OK", "qty": 1, "note": "keep"})]
        yield [(7, {"sku": "BAD", "qty": "nope", "note": "drop"})]

    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=chunks(),
            user=admin,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "invalid"
    assert raised.value.row_index == 7
    assert "integer" in raised.value.message
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert [row["sku"] for row in stored] == []


def test_duplicate_match_key_reports_the_smallest_index_and_rolls_back(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    def chunks():
        yield [{"sku": "DUP", "qty": 1, "note": "a"}, {"sku": "OTHER", "qty": 2, "note": "b"}]
        yield [{"sku": "DUP", "qty": 3, "note": "c"}]

    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=chunks(),
            user=admin,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "duplicate_key"
    assert raised.value.row_index == 0
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert stored == []


def test_create_of_an_existing_key_reports_that_row_and_rolls_back(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    write_rows(
        entity_id,
        mode="create",
        match_key="sku",
        rows=[{"sku": "OLD", "qty": 1, "note": "stay"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="create",
            match_key="sku",
            rows=[
                {"sku": "NEW", "qty": 2, "note": "no"},
                {"sku": "OLD", "qty": 3, "note": "no"},
            ],
            user=admin,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "key_exists"
    assert raised.value.row_index == 1
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert [row["sku"] for row in stored] == ["OLD"]
    assert stored[0]["note"] == "stay"


def test_null_unique_match_key_does_not_match_another_null(data_client) -> None:
    from typing import Literal

    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    entity_id = _publish_entity(
        [
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
            AttributeRecord(
                name="tag",
                type="string",
                unique=True,
                max_length=32,
            ),
        ]
    )
    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    def write(
        mode: Literal["upsert", "create", "update", "delete"],
        rows: list[dict[str, object]],
    ):
        return write_rows(
            entity_id,
            mode=mode,
            match_key="tag",
            rows=rows,
            user=admin,
            statement_timeout_ms=5000,
        )

    first = write("create", [{"code": "A", "tag": None}])
    second = write("create", [{"code": "B", "tag": None}])
    assert first.inserted == 1
    assert second.inserted == 1
    with pytest.raises(EntityRowWriteFailed) as raised:
        write("create", [{"code": "D", "tag": None}, {"code": "E", "tag": None}])
    assert raised.value.reason == "duplicate_key"
    assert raised.value.row_index == 0
    updated = write("update", [{"code": "Z", "tag": None}])
    assert (updated.updated, updated.unchanged, updated.unmatched) == (0, 0, 1)
    removed = write("delete", [{"tag": None}])
    assert (removed.deleted, removed.unmatched) == (0, 1)
    third = write("upsert", [{"code": "C", "tag": None}])
    assert (third.inserted, third.updated, third.unchanged, third.unmatched) == (
        1,
        0,
        0,
        0,
    )
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=10)
    assert sorted(row["code"] for row in stored) == ["A", "B", "C"]


def test_business_key_change_reports_that_row_and_rolls_back(data_client) -> None:
    from backend.admin.user_store import get_user_store
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    entity_id = _publish_entity(
        [
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                max_length=32,
            ),
            AttributeRecord(
                name="sku",
                type="string",
                business_key=True,
                max_length=32,
            ),
            AttributeRecord(name="note", type="text"),
        ]
    )
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    write_rows(
        entity_id,
        mode="upsert",
        match_key="code",
        rows=[{"code": "1", "sku": "A", "note": "n"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="code",
            rows=[{"code": "1", "sku": "B", "note": "n"}],
            user=admin,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "business_key"
    assert raised.value.row_index == 0
    assert raised.value.attribute == "sku"
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=10)
    assert stored[0]["sku"] == "A"


def test_cancel_between_chunks_leaves_the_target_unchanged(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    def chunks():
        yield [{"sku": "HOLD", "qty": 1, "note": "a"}]
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=chunks(),
            user=admin,
            statement_timeout_ms=5000,
        )
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert stored == []


def test_lock_timeout_mid_write_leaves_the_row_unchanged(data_client) -> None:
    _client, _stem, physical, entity_id = data_client
    from sqlalchemy import text

    from backend.admin.user_store import get_user_store
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.rows import read_rows, write_rows

    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    write_rows(
        entity_id,
        mode="upsert",
        match_key="sku",
        rows=[{"sku": "LOCK", "qty": 1, "note": "n"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    held = get_entity_engine().connect()
    transaction = held.begin()
    held.execute(
        text(f'SELECT "row_id" FROM "entity_data"."{physical}" WHERE "sku" = :sku FOR UPDATE'),
        {"sku": "LOCK"},
    )
    try:
        with pytest.raises(Exception):
            write_rows(
                entity_id,
                mode="update",
                match_key="sku",
                rows=[{"sku": "LOCK", "qty": 8, "note": "n"}],
                user=admin,
                pulse=lambda: 400,
            )
    finally:
        transaction.rollback()
        held.close()
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert next(row["qty"] for row in stored if row["sku"] == "LOCK") == 1


def _writer(entity_id: str, *, account: str, columns: list[dict[str, str]], row_rule):
    from backend.admin.roles import create_role
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.entity.access.service import create_grant, create_profile
    from backend.entity.access.views import rebuild_entity_views

    role = create_role(
        get_role_store(),
        key=account,
        name=account,
        permissions=["console:access", "entity:data_read", "entity:data_write"],
    )
    user = get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    profile = create_profile(
        entity_id,
        key=account,
        name=account,
        description=None,
        columns=columns,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": user.id},
        profile_id=profile["profile"]["id"],
        row_rule=row_rule,
        actions=["read", "write"],
        status="active",
        valid_until=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity_id)
    return user


def test_column_outside_the_clear_grant_names_the_row_and_rolls_back(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.access.plan import load_head
    from backend.entity.access.service import put_ladder
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    ids = {attr.name: attr.attribute_id for attr in load_head(entity_id).attributes}
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    put_ladder(
        entity_id,
        ids["note"],
        [
            {"key": "clear", "mode": "clear"},
            {"key": "last4", "mode": {"type": "partial", "keep_first": 0, "keep_last": 4}},
        ],
        actor_user_id=admin.id,
        actor_token_id=None,
    )
    writer = _writer(
        entity_id,
        account="narrow",
        columns=[
            {"attribute_id": ids["sku"], "level": "clear"},
            {"attribute_id": ids["qty"], "level": "clear"},
            {"attribute_id": ids["flag"], "level": "clear"},
            {"attribute_id": ids["note"], "level": "last4"},
        ],
        row_rule=None,
    )

    def chunks():
        yield [{"sku": "ALLOW", "qty": 1}]
        yield [{"sku": "DENY", "qty": 2, "note": "secret"}]

    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=chunks(),
            user=writer,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "column"
    assert raised.value.row_index == 1
    assert raised.value.attribute == "note"
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert stored == []


def test_failing_row_rule_names_the_row_and_rolls_back(data_client) -> None:
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.access.plan import load_head
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    ids = {attr.name: attr.attribute_id for attr in load_head(entity_id).attributes}
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    writer = _writer(
        entity_id,
        account="ruled",
        columns=[
            {"attribute_id": ids["sku"], "level": "clear"},
            {"attribute_id": ids["qty"], "level": "clear"},
            {"attribute_id": ids["flag"], "level": "clear"},
            {"attribute_id": ids["note"], "level": "clear"},
        ],
        row_rule={"lte": {"attr": ids["qty"], "value": 5}},
    )
    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=[
                {"sku": "OK", "qty": 1, "note": "a"},
                {"sku": "NO", "qty": 9, "note": "b"},
            ],
            user=writer,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "row_rule"
    assert raised.value.row_index == 1
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert stored == []


def test_one_grant_must_accept_every_written_row(data_client) -> None:
    """Two grants that each accept a different row do not authorize the write."""
    _client, _stem, _physical, entity_id = data_client
    from backend.admin.user_store import get_user_store
    from backend.entity.access.plan import load_head
    from backend.entity.access.service import create_grant, create_profile
    from backend.entity.access.views import rebuild_entity_views
    from backend.entity.errors import EntityRowWriteFailed
    from backend.entity.rows import read_rows, write_rows

    ids = {attr.name: attr.attribute_id for attr in load_head(entity_id).attributes}
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    columns = [
        {"attribute_id": ids["sku"], "level": "clear"},
        {"attribute_id": ids["qty"], "level": "clear"},
        {"attribute_id": ids["flag"], "level": "clear"},
        {"attribute_id": ids["note"], "level": "clear"},
    ]
    writer = _writer(
        entity_id,
        account="split_low",
        columns=columns,
        row_rule={"lte": {"attr": ids["qty"], "value": 5}},
    )
    high = create_profile(
        entity_id,
        key="split_high",
        name="split_high",
        description=None,
        columns=columns,
        actor_user_id=writer.id,
        actor_token_id=None,
    )
    create_grant(
        entity_id,
        subject={"type": "user", "id": writer.id},
        profile_id=high["profile"]["id"],
        row_rule={"gte": {"attr": ids["qty"], "value": 5}},
        actions=["read", "write"],
        status="active",
        valid_until=None,
        actor_user_id=writer.id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity_id)
    with pytest.raises(EntityRowWriteFailed) as raised:
        write_rows(
            entity_id,
            mode="upsert",
            match_key="sku",
            rows=[
                {"sku": "LOW", "qty": 1, "note": "a"},
                {"sku": "HIGH", "qty": 9, "note": "b"},
            ],
            user=writer,
            statement_timeout_ms=5000,
        )
    assert raised.value.reason == "row_rule"
    assert raised.value.row_index == 0
    stored, _total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert stored == []

