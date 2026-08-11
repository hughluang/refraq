"""Controlled query (Slice D) — L1–L5 HTTP / MCP / guards / audit."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
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
from backend.metadata.connectors.base import QueryResult  # noqa: E402
from backend.metadata.connectors.base import (  # noqa: E402
    ConnectorError,
    query_endpoint_error,
)
from backend.metadata.mcp_server import run_sql  # noqa: E402
from backend.metadata.query import service as query_service  # noqa: E402
from backend.metadata.query.guards import assert_readonly_single_statement  # noqa: E402
from backend.metadata.errors import (  # noqa: E402
    QueryMultiStatement,
    QueryNotReadonly,
    QueryRowLimit,
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
        self._rows = rows if rows is not None else [["1001"]]
        self._columns = columns if columns is not None else ["WO_ID"]
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
                "password": getattr(endpoint, "password", None),
            }
        )
        limited = self._rows[:max_rows]
        truncated = len(self._rows) > max_rows
        return QueryResult(
            columns=self._columns,
            rows=limited,
            truncated=truncated,
        )


def test_guard_allows_select() -> None:
    assert assert_readonly_single_statement("SELECT 1", engine="postgresql") == "SELECT 1"


def test_guard_allows_literal_with_write_word() -> None:
    sql = "SELECT 'delete' AS op FROM t"
    assert assert_readonly_single_statement(sql, engine="postgresql") == sql


def test_guard_allows_union() -> None:
    sql = "SELECT 1 UNION ALL SELECT 2"
    assert assert_readonly_single_statement(sql, engine="postgresql") == sql


def test_guard_allows_with_cte() -> None:
    sql = "WITH c AS (SELECT 1 AS x) SELECT * FROM c"
    assert assert_readonly_single_statement(sql, engine="postgresql") == sql


def test_guard_rejects_insert() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement("INSERT INTO t VALUES (1)", engine="postgresql")


def test_guard_rejects_multi_statement() -> None:
    with pytest.raises(QueryMultiStatement):
        assert_readonly_single_statement("SELECT 1; SELECT 2", engine="postgresql")


def test_guard_rejects_cte_dml() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement(
            "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x",
            engine="postgresql",
        )


def test_guard_rejects_select_into() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement(
            "SELECT * INTO new_table FROM old_table",
            engine="postgresql",
        )


def test_guard_rejects_comment_wrapped_ddl() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement("/*x*/ DROP TABLE t", engine="postgresql")


def test_guard_rejects_for_update() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement("SELECT 1 FOR UPDATE", engine="postgresql")


def test_guard_rejects_dangerous_function() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement("SELECT pg_sleep(3600)", engine="postgresql")


def test_guard_rejects_unsupported_engine() -> None:
    with pytest.raises(QueryNotReadonly):
        assert_readonly_single_statement("SELECT 1", engine="sqlite")


def test_guard_strips_trailing_semicolon() -> None:
    assert (
        assert_readonly_single_statement("SELECT 1;", engine="postgresql") == "SELECT 1"
    )


def test_query_success_and_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client)
    connector = _RecordingConnector(
        rows=[["1001"], ["1002"], ["1003"]],
        columns=["WO_ID"],
    )
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)

    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT WO_ID FROM WORK_ORDER", "max_rows": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["WO_ID"]
    assert body["rows"] == [["1001"], ["1002"]]
    assert body["truncated"] is True
    assert body["duration_ms"] >= 0
    assert len(connector.calls) == 1
    assert connector.calls[0]["timeout_sec"] == 30
    assert connector.calls[0]["max_rows"] == 2

    events, _ = get_audit_store().list_events(action="query.run")
    assert len(events) == 1
    assert events[0].result == "success"
    assert events[0].resource_type == "source"
    assert events[0].resource_id == source["id"]
    assert "sql_sha256" in events[0].detail
    assert "sql_summary" in events[0].detail
    dumped = json.dumps(events[0].detail)
    assert "super-secret-password" not in dumped
    assert "super-secret-password" not in resp.text


def test_query_permission_denied(client: TestClient) -> None:
    source = _make_source(client, key="op-src")
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="ops",
        display_name="Ops",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    with TestClient(app) as op_client:
        login = op_client.post(
            "/auth/login",
            json={"account": "ops", "password": "secret"},
        )
        assert login.status_code == 200
        denied = op_client.post(
            f"/sources/{source['id']}/query",
            json={"sql": "SELECT 1"},
        )
        assert denied.status_code == 403
    events, _ = get_audit_store().list_events(action="query.run")
    assert events == []


def test_query_disabled_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="dis-src")
    connector = _RecordingConnector()
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)
    disabled = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "JOB_SOURCE_DISABLED"
    assert connector.calls == []
    events, _ = get_audit_store().list_events(action="query.run")
    assert len(events) == 1
    assert events[0].result == "failure"


def test_query_missing_source(client: TestClient) -> None:
    resp = client.post(
        "/sources/src_missing/query",
        json={"sql": "SELECT 1"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "SOURCE_NOT_FOUND"
    events, _ = get_audit_store().list_events(action="query.run")
    assert len(events) == 1
    assert events[0].result == "failure"
    assert events[0].detail["code"] == "SOURCE_NOT_FOUND"


def test_query_row_limit_precheck(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="cap-src")
    connector = _RecordingConnector()
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1", "max_rows": 1001},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "QUERY_ROW_LIMIT"
    assert connector.calls == []
    events, _ = get_audit_store().list_events(action="query.run")
    assert len(events) == 1
    assert events[0].detail["code"] == "QUERY_ROW_LIMIT"


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("INSERT INTO t VALUES (1)", "QUERY_NOT_READONLY"),
        ("SELECT 1; SELECT 2", "QUERY_MULTI_STATEMENT"),
        (
            "WITH x AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM x",
            "QUERY_NOT_READONLY",
        ),
        ("SELECT a INTO b FROM c", "QUERY_NOT_READONLY"),
        ("/*noop*/ DROP TABLE t", "QUERY_NOT_READONLY"),
    ],
)
def test_query_guard_http_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    sql: str,
    code: str,
) -> None:
    source = _make_source(client, key=f"g-{abs(hash(sql)) % 10_000}")
    connector = _RecordingConnector()
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": sql},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == code
    assert connector.calls == []
    events, _ = get_audit_store().list_events(action="query.run")
    assert any(e.detail.get("code") == code and e.result == "failure" for e in events)


def test_query_application_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAQ_QUERY_TIMEOUT_SEC", "1")
    reset_settings_cache()
    source = _make_source(client, key="timeout-src")
    connector = _RecordingConnector(sleep_sec=3)
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert resp.status_code == 504
    assert resp.json()["code"] == "QUERY_TIMEOUT"
    events, _ = get_audit_store().list_events(action="query.run")
    assert any(e.detail.get("code") == "QUERY_TIMEOUT" for e in events)


def test_mcp_run_sql_success_and_forbidden(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata import mcp_server as mcp_mod
    from backend.admin.user_store import UserRecord

    source = _make_source(client, key="mcp-src")
    connector = _RecordingConnector(rows=[["ok"]], columns=["c"])
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)

    expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    tok = client.post("/tokens", json={"name": "query-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]

    raw = run_sql(
        authorization=f"Bearer {secret}",
        source_locator_key=source["locator_key"],
        sql="SELECT 1 AS c",
        max_rows=10,
    )
    payload = json.loads(raw)
    assert payload["columns"] == ["c"]
    assert payload["rows"] == [["ok"]]
    assert payload["truncated"] is False

    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    op_user = get_user_store().create_user(
        account="ops2",
        display_name="Ops2",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )

    def _fake_actor(_authorization: str | None) -> tuple[UserRecord, str]:
        return op_user, "tok_fake"

    monkeypatch.setattr(mcp_mod, "_actor_from_token", _fake_actor)
    forbidden = run_sql(
        authorization="Bearer unused",
        source_locator_key=source["locator_key"],
        sql="SELECT 1",
    )
    err = json.loads(forbidden)
    assert err["error"]["code"] == "AUTH_FORBIDDEN"


def test_query_endpoint_error_classifies_timeout() -> None:
    timeout = query_endpoint_error(
        Exception("canceling statement due to statement timeout")
    )
    assert timeout.code == "QUERY_TIMEOUT"
    other = query_endpoint_error(Exception("relation \"t\" does not exist"))
    assert other.code == "QUERY_ENDPOINT_FAILED"


def test_query_engine_timeout_maps_to_query_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="eng-timeout")

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
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert resp.status_code == 504
    assert resp.json()["code"] == "QUERY_TIMEOUT"
    events, _ = get_audit_store().list_events(action="query.run")
    assert any(e.detail.get("code") == "QUERY_TIMEOUT" for e in events)


def test_query_max_rows_below_one(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="min-rows")
    connector = _RecordingConnector()
    monkeypatch.setattr(query_service, "get_connector", lambda engine: connector)

    with pytest.raises(QueryRowLimit):
        query_service.run_controlled_query(
            source_id=source["id"],
            sql="SELECT 1",
            max_rows=0,
            actor_user_id="u1",
            actor_token_id=None,
        )
    assert connector.calls == []
    events, _ = get_audit_store().list_events(action="query.run")
    assert len(events) == 1
    assert events[0].detail.get("code") == "QUERY_ROW_LIMIT"


def test_query_unexpected_exception_maps_to_query_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="boom-src")

    class _BoomConnector(_RecordingConnector):
        def run_readonly(
            self,
            endpoint: object,
            sql: str,
            *,
            max_rows: int,
            timeout_sec: int,
        ) -> QueryResult:
            raise RuntimeError("driver blew up")

    monkeypatch.setattr(
        query_service, "get_connector", lambda engine: _BoomConnector()
    )
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert resp.status_code == 502
    assert resp.json()["code"] == "QUERY_FAILED"
    events, _ = get_audit_store().list_events(action="query.run")
    assert any(e.detail.get("code") == "QUERY_FAILED" for e in events)
