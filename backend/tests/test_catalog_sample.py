"""Catalog Sample compile + HTTP tests."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

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
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.store import get_catalog_store, reset_catalog_store  # noqa: E402
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.connectors.base import ConnectorError, QueryResult  # noqa: E402
from backend.metadata.errors import SampleColumnUnknown, SampleFilterInvalid  # noqa: E402
from backend.metadata.query import service as query_service  # noqa: E402
from backend.metadata.query.compile_sample import (  # noqa: E402
    SampleFilterSpec,
    SampleOrderSpec,
    compile_sample_sql,
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
        "password": "super-secret-password",
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


def _seed_object(source_id: str, *, source_key: str = "mes-prod") -> CatalogObjectRecord:
    now = datetime.utcnow()
    object_id = "obj_sample_1"
    record = CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/postgresql/{source_key}/public/table/orders",
        object_type="table",
        schema_name="public",
        name="orders",
        ddl=None,
        comment=None,
        primary_key=["id"],
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
        last_structure_job_id="job_sample",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id="col_1",
                object_id=object_id,
                locator_key=f"col/postgresql/{source_key}/public/table/orders/column/id",
                name="id",
                ordinal=0,
                data_type="integer",
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
            ),
            CatalogColumnRecord(
                id="col_2",
                object_id=object_id,
                locator_key=f"col/postgresql/{source_key}/public/table/orders/column/status",
                name="status",
                ordinal=1,
                data_type="text",
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
        indexes=[],
    )
    apply_structure_snapshot(
        source_id=source_id,
        job_id="job_sample",
        collected=[record],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key=source_key,
    )
    stored = get_catalog_store().get_object(object_id)
    assert stored is not None
    return stored


class _RecordingConnector:
    engine = "postgresql"

    def __init__(
        self,
        *,
        rows: list[list[Any]] | None = None,
        columns: list[str] | None = None,
        sleep_sec: float = 0,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rows = rows if rows is not None else [["1", "open"]]
        self._columns = columns if columns is not None else ["id", "status"]
        self._sleep_sec = sleep_sec

    def test_connection(self, endpoint: object) -> None:
        return None

    def collect_structure(self, endpoint: object) -> object:
        raise NotImplementedError

    def run_readonly(
        self,
        endpoint: object,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        if self._sleep_sec:
            time.sleep(self._sleep_sec)
        self.calls.append(
            {
                "sql": sql,
                "max_rows": max_rows,
                "timeout_sec": timeout_sec,
            }
        )
        limited = self._rows[:max_rows]
        truncated = len(self._rows) > max_rows
        return QueryResult(
            columns=self._columns,
            rows=limited,
            truncated=truncated,
        )


def test_compile_dialects_and_ops() -> None:
    known = {"id", "status"}
    pg = compile_sample_sql(
        engine="postgresql",
        schema_name="public",
        object_name="orders",
        known_columns=known,
        columns=None,
        filters=[SampleFilterSpec("status", "eq", "open")],
        order_by=[],
        offset=0,
        limit=50,
    )
    assert "LIMIT 50" in pg
    assert "status = 'open'" in pg

    mssql = compile_sample_sql(
        engine="mssql",
        schema_name="dbo",
        object_name="orders",
        known_columns=known,
        columns=None,
        filters=[],
        order_by=[],
        offset=0,
        limit=10,
    )
    assert "TOP 10" in mssql

    oracle = compile_sample_sql(
        engine="oracle",
        schema_name="APP",
        object_name="ORDERS",
        known_columns=known,
        columns=["id"],
        filters=[SampleFilterSpec("status", "is_null", "")],
        order_by=[SampleOrderSpec("id", "asc")],
        offset=5,
        limit=10,
    )
    assert "FETCH FIRST 10 ROWS ONLY" in oracle
    assert "OFFSET 5" in oracle
    assert "IS NULL" in oracle

    contains = compile_sample_sql(
        engine="postgresql",
        schema_name="public",
        object_name="orders",
        known_columns=known,
        columns=None,
        filters=[SampleFilterSpec("status", "contains", "a%b")],
        order_by=[],
        offset=0,
        limit=5,
    )
    assert "ILIKE" in contains
    assert "ESCAPE" in contains


def test_compile_unknown_column() -> None:
    with pytest.raises(SampleColumnUnknown):
        compile_sample_sql(
            engine="postgresql",
            schema_name="public",
            object_name="orders",
            known_columns={"id"},
            columns=["missing"],
            filters=[],
            order_by=[],
            offset=0,
            limit=10,
        )


def test_compile_empty_columns_rejected() -> None:
    with pytest.raises(SampleFilterInvalid):
        compile_sample_sql(
            engine="postgresql",
            schema_name="public",
            object_name="orders",
            known_columns={"id"},
            columns=[],
            filters=[],
            order_by=[],
            offset=0,
            limit=10,
        )


def test_sample_success_permission_and_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"], source_key=source["key"])
    connector = _RecordingConnector(
        rows=[["1", "open"], ["2", "open"]],
        columns=["id", "status"],
    )
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)

    resp = client.post(
        f"/objects/{obj.id}/sample",
        json={
            "filters": [{"column": "status", "op": "eq", "value": "open"}],
            "offset": 0,
            "limit": 50,
            "include_sql": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["id", "status"]
    assert len(body["rows"]) == 2
    assert body["offset"] == 0
    assert body["limit"] == 50
    assert body["has_more"] is False
    assert body["sql"] is not None
    assert "LIMIT 50" in body["sql"]
    assert len(connector.calls) == 1
    assert "status = 'open'" in connector.calls[0]["sql"]

    events, _ = get_audit_store().list_events(action="catalog.sample")
    assert len(events) == 1
    assert events[0].resource_type == "catalog_object"
    assert events[0].resource_id == obj.id
    assert events[0].result == "success"


def test_sample_connector_timeout_maps(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="sample-timeout")
    obj = _seed_object(source["id"], source_key=source["key"])

    class _TimeoutConnector(_RecordingConnector):
        def run_readonly(
            self,
            endpoint: object,
            sql: str,
            *,
            max_rows: int,
            timeout_sec: int,
        ) -> QueryResult:
            raise ConnectorError(
                "QUERY_TIMEOUT",
                "canceling statement due to statement timeout",
            )

    monkeypatch.setattr(
        query_service, "get_connector", lambda engine: _TimeoutConnector()
    )
    resp = client.post(f"/objects/{obj.id}/sample", json={"limit": 10})
    assert resp.status_code == 504
    assert resp.json()["code"] == "QUERY_TIMEOUT"
    events, _ = get_audit_store().list_events(action="catalog.sample")
    assert any(e.detail.get("code") == "QUERY_TIMEOUT" for e in events)


def test_sample_endpoint_failed_maps(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="sample-fail")
    obj = _seed_object(source["id"], source_key=source["key"])

    class _FailConnector(_RecordingConnector):
        def run_readonly(
            self,
            endpoint: object,
            sql: str,
            *,
            max_rows: int,
            timeout_sec: int,
        ) -> QueryResult:
            raise ConnectorError("QUERY_ENDPOINT_FAILED", "relation missing")

    monkeypatch.setattr(
        query_service, "get_connector", lambda engine: _FailConnector()
    )
    resp = client.post(f"/objects/{obj.id}/sample", json={"limit": 10})
    assert resp.status_code == 502
    assert resp.json()["code"] == "QUERY_FAILED"
    events, _ = get_audit_store().list_events(action="catalog.sample")
    assert any(e.detail.get("code") == "QUERY_FAILED" for e in events)


def test_sample_page_cap_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAQ_QUERY_MAX_ROWS", "100")
    reset_settings_cache()
    source = _make_source(client, key="cap-src")
    obj = _seed_object(source["id"], source_key=source["key"])
    resp = client.post(
        f"/objects/{obj.id}/sample",
        json={"offset": 90, "limit": 20},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "QUERY_ROW_LIMIT"
    events, _ = get_audit_store().list_events(action="catalog.sample")
    assert len(events) == 1
    assert events[0].detail["code"] == "QUERY_ROW_LIMIT"


def test_sample_permission_denied(client: TestClient) -> None:
    source = _make_source(client, key="deny-src")
    obj = _seed_object(source["id"], source_key=source["key"])
    roles = get_role_store()
    operator = roles.get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="op",
        display_name="Op",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    client.post("/auth/logout")
    login = client.post("/auth/login", json={"account": "op", "password": "secret"})
    assert login.status_code == 200
    resp = client.post(f"/objects/{obj.id}/sample", json={"limit": 10})
    assert resp.status_code == 403


def test_permissions_catalog_includes_sample(client: TestClient) -> None:
    resp = client.get("/permissions")
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()["items"]}
    assert "catalog:sample" in keys
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    assert "catalog:sample" not in operator.permissions
