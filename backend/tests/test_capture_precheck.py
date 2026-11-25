"""Capture Precheck observations, login selection, and the HTTP seam."""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest

from backend.metadata.capture.precheck import (
    inspect_capture,
    mssql_edition_result,
    resolve_capture_login,
    run_capture_precheck,
)
from backend.metadata.connectors.base import ConnectorError
from backend.tests.test_sources_jobs import _access, _make_source, client


class Result:
    def __init__(self, records):
        self.records = records

    def scalar(self):
        if not self.records:
            return None
        first = self.records[0]
        if isinstance(first, dict):
            return next(iter(first.values()))
        return first[0] if isinstance(first, tuple) else first

    def scalars(self):
        return self

    def mappings(self):
        return self

    def all(self):
        if not self.records:
            return []
        first = self.records[0]
        if isinstance(first, dict):
            return list(self.records)
        if isinstance(first, tuple) and len(first) == 1:
            return [row[0] for row in self.records]
        return list(self.records)

    def fetchmany(self, count):
        return self.all()[:count]

    def fetchone(self):
        return None if not self.records else self.records[0]

    def fetchall(self):
        return list(self.records)


class Conn:
    def __init__(self, answers, default=None):
        self.answers = answers
        self.default = default

    def execute(self, statement, params=None):
        sql = str(statement)
        for needle, payload in self.answers:
            if needle in sql:
                if isinstance(payload, BaseException):
                    raise payload
                return Result(payload)
        if isinstance(self.default, BaseException):
            raise self.default
        if self.default is not None:
            return Result(self.default)
        raise AssertionError(sql)

    class dialect:
        class identifier_preparer:
            @staticmethod
            def quote_identifier(name):
                return f"`{name}`"


def _by_key(items):
    return {item["key"]: item for item in items}


def test_mssql_edition_recognizes_cdc_editions():
    assert mssql_edition_result("Express Edition") == "fail"
    assert mssql_edition_result("Express Edition with Advanced Services") == "fail"
    assert mssql_edition_result("Web Edition") == "fail"
    assert mssql_edition_result("Standard Edition (64-bit)") == "pass"
    assert mssql_edition_result("Developer Edition") == "pass"
    assert mssql_edition_result("Enterprise Evaluation Edition") == "pass"
    assert mssql_edition_result("Business Intelligence Edition") == "pass"
    assert mssql_edition_result(None) == "unknown"
    assert mssql_edition_result("Something Else") == "unknown"


def test_mssql_precheck_reports_pass_fail_and_unknown():
    passing = Conn([
        ("ProductVersion", [("16.0.1000.6",)]),
        ("Edition", [("Standard Edition",)]),
        ("is_cdc_enabled", [(1,)]),
        ("dm_server_services", [("Running",)]),
        ("cdc_jobs", [(4320,)]),
        ("VIEW SERVER STATE", [(1,)]),
        ("INFORMATION_SCHEMA.TABLES", [("orders",)]),
        ("source_object_id", [("dbo_orders",)]),
        ("FROM sys.columns", [("id",), ("body",)]),
        ("captured_columns", [("id",), ("body",)]),
        ("HAS_PERMS_BY_NAME", [(1,)]),
    ])
    items, tables = inspect_capture("mssql", passing, {"schema": "dbo"}, "stored")
    found = _by_key(items)
    assert found["engine_version"]["result"] == "not_applicable"
    assert found["engine_version"]["observed"] == "16.0.1000.6"
    assert found["edition"]["result"] == "pass"
    assert found["cdc_enabled"]["result"] == "pass"
    assert found["agent_running"]["result"] == "pass"
    assert found["retention"]["result"] == "not_applicable"
    assert found["retention"]["observed"] == "4320"
    assert found["view_server_state"]["note"] is None
    assert tables["items"] == [{
        "name": "dbo.orders", "result": "pass", "cause": None, "observed": "instances=1", "note": None,
    }]

    failing = Conn([
        ("ProductVersion", [("16.0.1000.6",)]),
        ("Edition", [("Express Edition",)]),
        ("is_cdc_enabled", [(0,)]),
        ("dm_server_services", [("Stopped",)]),
        ("cdc_jobs", []),
        ("VIEW SERVER STATE", [(0,)]),
        ("INFORMATION_SCHEMA.TABLES", [("orders",)]),
        ("source_object_id", []),
        ("FROM sys.columns", [("id",)]),
        ("HAS_PERMS_BY_NAME", [(0,)]),
    ])
    items, tables = inspect_capture("mssql", failing, {"schema": "dbo"}, "access")
    found = _by_key(items)
    assert found["edition"]["result"] == "fail"
    assert found["cdc_enabled"]["result"] == "fail"
    assert found["agent_running"]["result"] == "fail"
    assert found["retention"]["result"] == "fail"
    assert found["view_server_state"]["note"] == "access_credential"
    assert tables["items"][0]["result"] == "fail"
    assert tables["items"][0]["cause"] == "schema"
    assert tables["items"][0]["note"] == "access_credential"

    unknown = Conn([], default=RuntimeError("denied"))
    items, tables = inspect_capture("mssql", unknown, {"schema": "dbo"}, "stored")
    assert {item["result"] for item in items} == {"unknown"}
    assert tables == {"total": 0, "truncated": False, "limit": 200, "items": []}


def test_postgresql_precheck_reports_pass_fail_and_unknown():
    covered = ("orders", "capture_pub", False, ["id", "body"], ["body", "id"], False, True)
    passing = Conn([
        ("current_database", [("app", "logical", 180000, True, False)]),
        ("SELECT DISTINCT published.pubname", [("capture_pub",)]),
        ("has_table_privilege(relation.oid", [covered]),
    ])
    items, tables = inspect_capture("postgresql", passing, {"schema": "public"}, "request")
    found = _by_key(items)
    assert found["wal_level"]["result"] == "pass"
    assert found["replication_role"]["result"] == "pass"
    assert found["engine_version"]["result"] == "not_applicable"
    assert found["engine_version"]["observed"] == "180000"
    assert found["publications"]["result"] == "pass"
    assert tables["items"][0]["result"] == "pass"
    assert tables["items"][0]["name"] == "public.orders"

    failing = Conn([
        ("current_database", [("app", "replica", 180000, True, True)]),
        ("SELECT DISTINCT published.pubname", []),
        ("has_table_privilege(relation.oid", [("orders", None, None, None, ["id"], False, False)]),
    ])
    items, tables = inspect_capture("postgresql", failing, {"schema": "public"}, "stored")
    found = _by_key(items)
    assert found["wal_level"]["result"] == "fail"
    assert found["replication_role"]["result"] == "fail"
    assert found["replication_role"]["action"] == "reject_superuser"
    assert found["publications"]["result"] == "fail"
    assert tables["items"][0]["cause"] == "schema"
    assert tables["items"][0]["observed"] == "unpublished"

    items, tables = inspect_capture(
        "postgresql", Conn([], default=RuntimeError("denied")), {"schema": "public"}, "stored",
    )
    assert _by_key(items)["wal_level"]["result"] == "unknown"
    assert _by_key(items)["table_list"]["result"] == "unknown"
    assert tables["items"] == []


def test_mysql_precheck_reports_pass_fail_and_unknown():
    variables = [
        {"VARIABLE_NAME": name, "VARIABLE_VALUE": value}
        for name, value in (
            ("version", "8.0.36"), ("log_bin", "ON"), ("binlog_format", "ROW"),
            ("binlog_row_image", "FULL"), ("gtid_mode", "OFF"),
            ("binlog_expire_logs_seconds", "86400"),
        )
    ]
    passing = Conn([
        ("global_variables", variables),
        ("USER_PRIVILEGES", [("REPLICATION SLAVE",), ("REPLICATION CLIENT",)]),
        ("TABLE_NAME FROM information_schema.TABLES", [("orders",)]),
        ("SELECT * FROM", []),
    ])
    items, tables = inspect_capture("mysql", passing, {"database": "sales"}, "stored")
    found = _by_key(items)
    assert found["binlog_enabled"]["result"] == "pass"
    assert found["row_format"]["result"] == "pass"
    assert found["full_row_image"]["result"] == "pass"
    assert found["lineage_mode"]["result"] == "not_applicable"
    assert found["lineage_mode"]["observed"] == "OFF"
    assert found["retention"]["result"] == "not_applicable"
    assert found["retention"]["observed"] == "86400"
    assert found["privileges"]["result"] == "pass"
    assert found["engine_version"]["result"] == "not_applicable"
    assert tables["items"][0] == {
        "name": "sales.orders", "result": "pass", "cause": None, "observed": None, "note": None,
    }

    failing = Conn([
        ("global_variables", [{"VARIABLE_NAME": "log_bin", "VARIABLE_VALUE": "OFF"}]),
        ("USER_PRIVILEGES", [("SELECT",)]),
        ("TABLE_NAME FROM information_schema.TABLES", [("orders",)]),
        ("SELECT * FROM", RuntimeError("denied")),
    ])
    items, tables = inspect_capture("mysql", failing, {"database": "sales"}, "access")
    found = _by_key(items)
    assert found["binlog_enabled"]["result"] == "fail"
    assert found["privileges"]["result"] == "fail"
    assert found["privileges"]["note"] == "access_credential"
    assert tables["items"][0]["cause"] == "permission"

    items, _tables = inspect_capture(
        "mysql", Conn([], default=RuntimeError("denied")), {"database": "sales"}, "stored",
    )
    assert _by_key(items)["binlog_enabled"]["result"] == "unknown"
    assert _by_key(items)["privileges"]["result"] == "unknown"


def test_oracle_precheck_reports_pass_fail_and_unknown():
    passing = Conn([
        ("version_full", [("19.21.0.0.0",)]),
        ("log_mode", [("ARCHIVELOG",)]),
        ("supplemental_log_data_min", [("YES",)]),
        ("v$archived_log", [(7200,)]),
        ("session_privs", [("CREATE SESSION",), ("LOGMINING",), ("SELECT ANY TRANSACTION",)]),
        ("all_tables", [("ORDERS",)]),
        ("all_log_groups", [(1,)]),
        ("SELECT 1 FROM", []),
    ])
    items, tables = inspect_capture("oracle", passing, {"owner": "APP"}, "stored")
    found = _by_key(items)
    assert found["archivelog"]["result"] == "pass"
    assert found["supplemental_logging"]["result"] == "pass"
    assert found["retention"]["result"] == "not_applicable"
    assert found["retention"]["observed"] == "7200"
    assert found["privileges"]["result"] == "pass"
    assert found["engine_version"]["result"] == "not_applicable"
    assert tables["items"][0]["name"] == "APP.ORDERS"
    assert tables["items"][0]["result"] == "pass"

    failing = Conn([
        ("version_full", [("19.21.0.0.0",)]),
        ("log_mode", [("NOARCHIVELOG",)]),
        ("supplemental_log_data_min", [("NO",)]),
        ("v$archived_log", []),
        ("session_privs", [("CREATE SESSION",)]),
        ("all_tables", [("ORDERS",)]),
        ("all_log_groups", [(0,)]),
    ])
    items, tables = inspect_capture("oracle", failing, {"owner": "APP"}, "access")
    found = _by_key(items)
    assert found["archivelog"]["result"] == "fail"
    assert found["supplemental_logging"]["result"] == "fail"
    assert found["retention"]["result"] == "fail"
    assert found["privileges"]["result"] == "fail"
    assert found["privileges"]["note"] == "access_credential"
    assert tables["items"][0]["cause"] == "schema"

    items, _tables = inspect_capture(
        "oracle", Conn([], default=RuntimeError("denied")), {"owner": "APP"}, "stored",
    )
    assert _by_key(items)["archivelog"]["result"] == "unknown"
    assert _by_key(items)["privileges"]["result"] == "unknown"


def test_table_results_sort_failures_first_and_cap_at_200():
    names = [(f"t{index:03d}",) for index in range(205)]
    rows = []
    for index in range(205):
        readable = index == 0
        rows.append((f"t{index:03d}", None, None, None, ["id"], False, readable))
    connection = Conn([
        ("current_database", [("app", "logical", 1, True, False)]),
        ("SELECT DISTINCT published.pubname", [("pub",)]),
        ("has_table_privilege(relation.oid", rows),
    ])
    _items, tables = inspect_capture("postgresql", connection, {"schema": "public"}, "stored")
    assert tables["total"] == 205
    assert tables["truncated"] is True
    assert len(tables["items"]) == 200
    assert tables["items"][0]["result"] == "fail"
    assert tables["items"][-1]["result"] == "fail"
    assert [item["name"] for item in tables["items"]] == sorted(
        item["name"] for item in tables["items"]
    )


def test_login_cascade_prefers_request_then_stored_then_access():
    access = {"username": "ordinary", "password": "ordinary-secret"}
    request = resolve_capture_login(
        request_username="typed", request_password="typed-secret",
        stored_ciphertext="ignored", access=access,
    )
    assert request == ("typed", "typed-secret", "request")
    assert resolve_capture_login(
        request_username=None, request_password=None, stored_ciphertext=None, access=access,
    ) == ("ordinary", "ordinary-secret", "access")
    assert resolve_capture_login(
        request_username=None, request_password=None, stored_ciphertext="not-a-secret", access=access,
    )[2] == "access"


def _canned(**kwargs):
    from backend.metadata.capture.precheck import PrecheckResult

    return PrecheckResult(
        ok=True, credential=kwargs["credential"], engine=kwargs["engine"],
        items=[{"key": "wal_level", "result": "unknown", "expected": None, "observed": None,
                "action": "unobserved", "note": None}],
        tables={"total": 0, "truncated": False, "limit": 200, "items": []},
    )


def test_http_hides_secrets_and_uses_the_selected_login(client, monkeypatch):
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()
    seen = {}

    def fake(**kwargs):
        seen["override"] = kwargs["credential_override"]
        seen["credential"] = kwargs["credential"]
        return _canned(**kwargs)

    monkeypatch.setattr("backend.metadata.routers.sources.run_capture_precheck", fake)
    access = _access(password="access-secret-value", username="ordinary-user")
    response = client.post("/sources/capture-check", json={
        "engine": "postgresql",
        "access": access,
        "capture_credential": {"username": "capture-user", "password": "capture-secret-value"},
    })
    assert response.status_code == 200, response.text
    assert seen["override"] == ("capture-user", "capture-secret-value")
    assert seen["credential"] == "request"
    assert response.json()["credential"] == "request"
    assert response.json()["advisory"] is True
    for secret in ("capture-secret-value", "access-secret-value", "capture-user", "ordinary-user"):
        assert secret not in response.text
    events, _total = get_audit_store().list_events(action="source.capture_check")
    assert len(events) == 1
    assert events[0].resource_id == "draft"
    detail = str(events[0].detail)
    assert events[0].detail["credential"] == "request"
    assert "capture-secret-value" not in detail
    assert "capture-user" not in detail
    assert "ordinary-user" not in detail

    source = client.post("/sources", json={
        "key": "checked", "name": "Checked", "engine": "postgresql", "access": access,
        "capture_credential": {"username": "saved-user", "password": "saved-secret-value"},
    })
    assert source.status_code == 201, source.text
    source_id = source.json()["source"]["id"]
    stored = client.post(f"/sources/{source_id}/capture-check", json={})
    assert stored.status_code == 200, stored.text
    assert seen["override"] == ("saved-user", "saved-secret-value")
    assert seen["credential"] == "stored"
    assert "saved-secret-value" not in stored.text
    assert "saved-user" not in stored.text

    requested = client.post(f"/sources/{source_id}/capture-check", json={
        "capture_credential": {"username": "typed-user", "password": "typed-secret-value"},
    })
    assert requested.status_code == 200, requested.text
    assert seen["override"] == ("typed-user", "typed-secret-value")
    assert "typed-secret-value" not in requested.text

    plain = _make_source(client, key="plain-source")
    fallback = client.post(f"/sources/{plain['id']}/capture-check", json={})
    assert fallback.status_code == 200, fallback.text
    assert seen["credential"] == "access"
    assert seen["override"] is None
    assert fallback.json()["credential"] == "access"


def test_capture_check_permission_and_missing_source(client):
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store

    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="ops-check", display_name="Ops", password_hash=hash_password("secret"),
        role_id=operator.id, status="active",
    )
    denied = client.post("/auth/login", json={"account": "ops-check", "password": "secret"})
    assert denied.status_code == 200
    draft = client.post("/sources/capture-check", json={"engine": "postgresql", "access": _access()})
    assert draft.status_code == 403

    admin = client.post("/auth/login", json={"account": "admin", "password": "secret"})
    assert admin.status_code == 200
    source = _make_source(client, key="hidden-check")
    role = create_role(
        get_role_store(), key="check_writer", name="Check writer",
        permissions=["console:access", "sources:read", "sources:write"],
    )
    get_user_store().create_user(
        account="checker", display_name="Checker", password_hash=hash_password("secret"),
        role_id=role.id, status="active",
    )
    writer = client.post("/auth/login", json={"account": "checker", "password": "secret"})
    assert writer.status_code == 200
    hidden = client.post(f"/sources/{source['id']}/capture-check", json={})
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "SOURCE_NOT_FOUND"


def test_connection_failure_and_timeout_hide_the_driver_error(monkeypatch):
    from backend.metadata.capture import precheck as precheck_mod

    class Boom:
        engine = "postgresql"

        @contextmanager
        def inspection_connection(self, endpoint):
            raise ConnectorError("JOB_ENDPOINT_FAILED", f"password={endpoint.password}")
            yield None

    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector", lambda engine: Boom(),
    )
    failed = run_capture_precheck(
        engine="postgresql", access=_access(password="super-secret-token"),
    )
    assert failed.ok is False
    assert failed.code == "SOURCE_CAPTURE_CHECK_FAILED"
    assert "super-secret-token" not in failed.message

    class Hang:
        engine = "postgresql"

        @contextmanager
        def inspection_connection(self, endpoint):
            time.sleep(1.5)
            yield None

    monkeypatch.setattr(precheck_mod, "PRECHECK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector", lambda engine: Hang(),
    )
    started = time.monotonic()
    timed_out = run_capture_precheck(engine="postgresql", access=_access())
    assert timed_out.code == "SOURCE_CAPTURE_CHECK_TIMEOUT"
    assert time.monotonic() - started < 1
