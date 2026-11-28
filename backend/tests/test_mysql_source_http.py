"""Offline MySQL Source integration at the HTTP and connector runtime seams."""

import asyncio
import json
from base64 import b64decode
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pymysql.constants import FIELD_TYPE

from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.roles import seed_roles
from backend.admin.security import hash_password
from backend.admin.user_store import get_user_store
from backend.main import app
from backend.metadata.connectors.runtime import prepare
from backend.metadata.source_access import reset_source_access_store
from backend.metadata.sources.store import get_source_store


def mysql_access(**changes):
    return {
        "host": "db.invalid",
        "port": 3306,
        "username": "reader",
        "password": "unit-secret",
        "database": "Sales",
        "ssl_mode": "disable",
        **changes,
    }


def test_mysql_runtime_uses_one_explicit_database_scope():
    bound = prepare(engine="mysql", access=mysql_access())
    assert bound.connector.engine == "mysql"
    assert bound.endpoint.database_name == "Sales"
    assert bound.endpoint.schema_filter == "Sales"
    assert bound.endpoint.password == "unit-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    reset_source_access_store()
    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin_role.id,
        status="active",
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert response.status_code == 200, response.text
        yield test_client
    reset_source_access_store()


def create_mysql(client, key="mysql-sales"):
    response = client.post(
        "/sources",
        json={"key": key, "name": "Sales", "engine": "mysql", "access": mysql_access()},
    )
    assert response.status_code == 201, response.text
    return response


def test_mysql_http_encrypted_access_retain_replace_and_projection(client):
    created = create_mysql(client)
    source = created.json()["source"]
    source_id = source["id"]
    assert source["locator_key"] == "src/mysql/mysql-sales"
    assert source["has_access"] is True
    assert source["access"]["database"] == "Sales"
    assert "password" not in source["access"]
    assert "unit-secret" not in created.text
    stored = get_source_store().get_source(source_id)
    ciphertext = stored.access_ciphertext
    assert (
        ciphertext
        and "unit-secret" not in ciphertext
        and "db.invalid" not in ciphertext
    )
    assert client.get(f"/sources/{source_id}/access").json()["access"] == mysql_access()

    retained = client.patch(f"/sources/{source_id}", json={"name": "Sales renamed"})
    assert retained.status_code == 200, retained.text
    assert get_source_store().get_source(source_id).access_ciphertext == ciphertext
    assert client.get(f"/sources/{source_id}/access").json()["access"] == mysql_access()

    replacement = mysql_access(password="replacement-secret", database="Warehouse")
    replaced = client.patch(
        f"/sources/{source_id}", json={"engine": "mysql", "access": replacement}
    )
    assert replaced.status_code == 200, replaced.text
    assert "replacement-secret" not in replaced.text
    assert get_source_store().get_source(source_id).access_ciphertext != ciphertext
    assert client.get(f"/sources/{source_id}/access").json()["access"] == replacement
    read = client.get(f"/sources/{source_id}")
    assert read.status_code == 200
    assert read.json()["source"]["access"]["database"] == "Warehouse"
    assert "password" not in read.json()["source"]["access"]

    events = client.get(
        "/audit/events", params={"resource_type": "source", "limit": 200}
    )
    assert events.status_code == 200
    assert {row["action"] for row in events.json()["items"]} >= {
        "source.create",
        "source.update",
    }
    assert "unit-secret" not in events.text and "replacement-secret" not in events.text
    assert ciphertext not in events.text


def test_mysql_spec_filter_and_engine_catalogs(client):
    from backend.metadata.connectors.registry import get_connector
    from backend.metadata.connectors.specs import SUPPORTED_ENGINES
    from backend.metadata.schemas.sources import (
        CreateSourceRequest,
        PatchSourceRequest,
        TestSourceDraftRequest,
        TestSourceRequest,
    )
    from backend.metadata.type_mappings.seeds import PRODUCT_TYPE_MAPPING_SEEDS

    source_id = create_mysql(client).json()["source"]["id"]
    spec = client.get("/sources/access-schema/mysql")
    assert spec.status_code == 200, spec.text
    schema = spec.json()["schema"]
    assert "database" in schema["required"]
    assert "schema" not in schema["properties"]
    assert schema["properties"]["password"]["x-secret"] is True
    filtered = client.get("/sources", params={"engine": "mysql", "q": "sales"})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert [row["id"] for row in filtered.json()["items"]] == [source_id]
    assert "unit-secret" not in filtered.text
    assert (
        client.get("/sources", params={"engine": "mysql", "q": "absent"}).json()[
            "total"
        ]
        == 0
    )
    assert client.get("/sources", params={"engine": "postgresql"}).json()["total"] == 0
    assert client.get("/sources", params={"engine": "mariadb"}).status_code == 422

    for model in (
        CreateSourceRequest,
        PatchSourceRequest,
        TestSourceDraftRequest,
        TestSourceRequest,
    ):
        field = model.model_json_schema()["properties"]["engine"]
        literal = field if "enum" in field else field["anyOf"][0]
        assert set(literal["enum"]) == SUPPORTED_ENGINES
    assert {row[0] for row in PRODUCT_TYPE_MAPPING_SEEDS} == SUPPORTED_ENGINES
    for engine in SUPPORTED_ENGINES:
        assert get_connector(engine).engine == engine
    mappings = client.get("/type-mappings", params={"engine": "mysql"})
    assert mappings.status_code == 200, mappings.text
    assert mappings.json()["total"] > 0
    assert {row["engine"] for row in mappings.json()["items"]} == {"mysql"}


def test_mysql_http_draft_and_stored_probe_use_explicit_scope(client, monkeypatch):
    from backend.metadata.connectors.mysql import MysqlConnector

    endpoints = []
    monkeypatch.setattr(
        MysqlConnector,
        "test_connection",
        lambda self, endpoint: endpoints.append(endpoint),
    )
    draft = client.post(
        "/sources/test", json={"engine": "mysql", "access": mysql_access()}
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["ok"] is True
    source_id = create_mysql(client).json()["source"]["id"]
    stored = client.post(f"/sources/{source_id}/test", json={"engine": "mysql"})
    assert stored.status_code == 200, stored.text
    assert stored.json()["ok"] is True
    override = client.post(
        f"/sources/{source_id}/test",
        json={
            "engine": "mysql",
            "access": mysql_access(database="Other", password="probe-secret"),
        },
    )
    assert override.status_code == 200, override.text
    assert override.json()["ok"] is True
    assert [(ep.database_name, ep.schema_filter, ep.password) for ep in endpoints] == [
        ("Sales", "Sales", "unit-secret"),
        ("Sales", "Sales", "unit-secret"),
        ("Other", "Other", "probe-secret"),
    ]
    assert client.get(f"/sources/{source_id}/access").json()["access"] == mysql_access()
    audit = client.get(
        "/audit/events", params={"resource_type": "source", "limit": 200}
    )
    assert "probe-secret" not in audit.text and "unit-secret" not in audit.text


def test_mysql_full_access_edit_obeys_role_and_source_membership(client):
    from backend.metadata.source_access import create_membership, change_level

    source_id = create_mysql(client).json()["source"]["id"]
    roles = get_role_store()
    roles.insert(
        RoleRecord(
            id="role_mysql_operator",
            key="mysql_operator",
            name="MySQL operator",
            permissions=["console:access", "sources:read", "sources:write"],
        )
    )
    user = get_user_store().create_user(
        account="operator",
        display_name="Operator",
        password_hash=hash_password("secret"),
        role_id="role_mysql_operator",
        status="active",
    )
    login = client.post(
        "/auth/login", json={"account": "operator", "password": "secret"}
    )
    assert login.status_code == 200
    assert client.get(f"/sources/{source_id}/access").status_code == 404
    membership = create_membership(
        subject_type="user", subject_id=user.id, target=source_id, level="viewer"
    )
    read = client.get(f"/sources/{source_id}")
    assert read.status_code == 200 and "unit-secret" not in read.text
    assert client.get(f"/sources/{source_id}/access").status_code == 403
    assert (
        client.patch(
            f"/sources/{source_id}", json={"access": mysql_access(password="denied")}
        ).status_code
        == 403
    )
    assert client.post(f"/sources/{source_id}/test", json={}).status_code == 403
    change_level(membership.id, "maintainer")
    assert client.get(f"/sources/{source_id}/access").json()["access"] == mysql_access()
    updated = client.patch(
        f"/sources/{source_id}", json={"access": mysql_access(password="allowed")}
    )
    assert updated.status_code == 200, updated.text
    role = roles.get_by_id("role_mysql_operator")
    role.permissions = ["sources:read"]
    roles.save(role)
    assert client.get(f"/sources/{source_id}/access").status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"database": None},
        {"database": ""},
        {"schema": "fake"},
        {"ssl_mode": "require"},
        {"extra": {"ssl": "ignored"}},
    ],
)
def test_mysql_http_rejects_invalid_scope_and_unwired_options(client, change):
    source_id = create_mysql(client).json()["source"]["id"]
    invalid = mysql_access(**change)
    for response in (
        client.post(
            "/sources",
            json={
                "key": "invalid",
                "name": "Invalid",
                "engine": "mysql",
                "access": invalid,
            },
        ),
        client.patch(f"/sources/{source_id}", json={"access": invalid}),
        client.post("/sources/test", json={"engine": "mysql", "access": invalid}),
        client.post(f"/sources/{source_id}/test", json={"access": invalid}),
    ):
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "SOURCE_ACCESS_INVALID"
    assert client.get(f"/sources/{source_id}/access").json()["access"] == mysql_access()


@pytest.fixture
def mysql_result_source(client, monkeypatch):
    from backend.metadata.connectors import mysql

    columns = ["id", "payload", "label", "total", "document", "elapsed"]
    codes = [
        FIELD_TYPE.VAR_STRING,
        FIELD_TYPE.BLOB,
        FIELD_TYPE.BLOB,
        FIELD_TYPE.NEWDECIMAL,
        FIELD_TYPE.JSON,
        FIELD_TYPE.TIME,
    ]
    rows = [
        (
            b"abc",
            b"\xff\x00",
            "abc",
            Decimal("12345678901234567890.12345678901234567890"),
            '{"encoding":"base64","data":"/wA="}',
            timedelta(hours=-30, microseconds=-123456),
        ),
        (b"", b"", "", None, None, None),
        (b"xyz", None, None, None, None, None),
    ]

    class Result:
        cursor = SimpleNamespace(
            description=[
                (
                    name,
                    code,
                    None,
                    None,
                    None,
                    6 if code == FIELD_TYPE.TIME else None,
                    name != "id",
                )
                for name, code in zip(columns, codes, strict=True)
            ]
        )

        def keys(self):
            return columns

        def __iter__(self):
            return iter(rows)

    connection = SimpleNamespace(
        exec_driver_sql=lambda sql: Result() if sql.startswith("SELECT") else None,
        execution_options=lambda **options: connection,
    )
    engine = SimpleNamespace(
        connect=lambda: nullcontext(connection), dispose=lambda: None
    )
    monkeypatch.setattr(mysql, "create_engine", lambda *args, **kwargs: engine)
    return create_mysql(client).json()["source"]


def _assert_mysql_result_cells(body):
    assert body["columns"] == ["id", "payload", "label", "total", "document", "elapsed"]
    assert body["declarations"][-1] == {
        "name": "elapsed",
        "temporal_kind": "interval",
        "precision": 6,
        "nullable": True,
    }
    assert body["rows"] == [
        [
            {"encoding": "base64", "data": "YWJj"},
            {"encoding": "base64", "data": "/wA="},
            "abc",
            "12345678901234567890.12345678901234567890",
            '{"encoding":"base64","data":"/wA="}',
            "-P1DT6H0.123456S",
        ],
        [
            {"encoding": "base64", "data": ""},
            {"encoding": "base64", "data": ""},
            "",
            None,
            None,
            None,
        ],
        [{"encoding": "base64", "data": "eHl6"}, None, None, None, None, None],
    ]
    key, payload = body["rows"][0][:2]
    assert b64decode(key["data"], validate=True) == b"abc"
    assert b64decode(payload["data"], validate=True) == b"\xff\x00"


def test_mysql_controlled_query_preserves_binary_and_other_result_cells(
    client, mysql_result_source
):
    response = client.post(
        f"/sources/{mysql_result_source['id']}/query",
        json={
            "sql": "SELECT id, payload, label, total, document, elapsed FROM result_cells"
        },
    )
    assert response.status_code == 200, response.text
    _assert_mysql_result_cells(response.json())


def test_mysql_mcp_query_preserves_binary_and_other_result_cells(
    client, mysql_result_source
):
    from backend.core.time import format_instant, utc_now
    from backend.admin.principal import mcp_authorization
    from backend.metadata.mcp_server import run_sql

    token = client.post(
        "/tokens",
        json={
            "name": "mysql-query",
            "expires_at": format_instant(utc_now() + timedelta(days=7)),
        },
    )
    assert token.status_code == 201
    with mcp_authorization(f"Bearer {token.json()['secret']}"):
        payload = asyncio.run(
            run_sql(
                source_locator_key=mysql_result_source["locator_key"],
                sql="SELECT id, payload, label, total, document, elapsed FROM result_cells",
            )
        )
    body = json.loads(payload)
    assert "error" not in body, body
    _assert_mysql_result_cells(body)


def test_mysql_catalog_sample_preserves_binary_and_other_result_cells(
    client, mysql_result_source
):
    from backend.core.time import utc_now
    from backend.metadata.catalog.records import CatalogObjectRecord
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot

    source_id = mysql_result_source["id"]
    now = utc_now()
    record = CatalogObjectRecord(
        id="obj_mysql_result_cells",
        source_id=source_id,
        locator_key="obj/mysql/mysql-sales/Sales/table/result_cells",
        object_type="table",
        schema_name="Sales",
        name="result_cells",
        ddl=None,
        comment=None,
        primary_key=["id"],
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
        last_structure_job_id="job_mysql_result_cells",
        collected_at=now,
        created_at=now,
        updated_at=now,
    )
    apply_structure_snapshot(
        source=get_source_store().get_source(source_id),
        job_id="job_mysql_result_cells",
        collected=[record],
        schema_scope="Sales",
    )

    response = client.post(f"/objects/{record.id}/sample", json={})
    assert response.status_code == 200, response.text
    _assert_mysql_result_cells(response.json())
