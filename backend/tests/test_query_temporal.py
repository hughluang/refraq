"""Controlled query and MCP run_sql temporal cells."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

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
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.metadata.connectors.base import QueryColumn, QueryResult  # noqa: E402
from backend.metadata.mcp_actor import mcp_authorization  # noqa: E402
from backend.metadata.mcp_server import run_sql  # noqa: E402
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


def _access() -> dict[str, Any]:
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


def _make_source(client: TestClient, *, key: str, engine: str = "postgresql") -> dict[str, Any]:
    access = _access()
    if engine == "oracle":
        access = {
            "host": "127.0.0.1",
            "port": 1521,
            "username": "u",
            "password": "super-secret-password",
            "ssl_mode": "disable",
            "service_name": "ORCL",
            "owner": "APP",
        }
    elif engine == "mssql":
        access = {
            "host": "127.0.0.1",
            "port": 1433,
            "username": "u",
            "password": "super-secret-password",
            "ssl_mode": "disable",
            "database": "MES",
            "schema": "dbo",
        }
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "engine": engine,
            "access": access,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


class _DriverConnector:
    engine = "postgresql"

    def __init__(
        self,
        *,
        columns: list[str],
        rows: list[list[Any]],
        native_types: list[str | None],
        nullables: list[bool | None] | None = None,
    ) -> None:
        self._columns = columns
        self._rows = rows
        self._native_types = native_types
        self._nullables = nullables

    def run_readonly(
        self,
        endpoint: object,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        del endpoint, sql, timeout_sec
        limited = self._rows[:max_rows]
        info = [
            QueryColumn(
                name=name,
                native_type=self._native_types[index],
                nullable=None if self._nullables is None else self._nullables[index],
            )
            for index, name in enumerate(self._columns)
        ]
        return QueryResult(
            columns=self._columns,
            rows=limited,
            truncated=len(self._rows) > max_rows,
            column_info=info,
        )


def _query(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str,
    engine: str,
    columns: list[str],
    rows: list[list[Any]],
    native_types: list[str | None],
    nullables: list[bool | None] | None = None,
) -> dict[str, Any]:
    source = _make_source(client, key=key, engine=engine)
    connector = _DriverConnector(
        columns=columns,
        rows=rows,
        native_types=native_types,
        nullables=nullables,
    )
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine_name: connector,
    )
    resp = client.post(
        f"/sources/{source['id']}/query",
        json={"sql": "SELECT 1", "max_rows": 10},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_query_keeps_plain_string_and_reports_declarations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="plain-text",
        engine="postgresql",
        columns=["label"],
        rows=[["2024-06-01"]],
        native_types=["text"],
    )
    assert body["columns"] == ["label"]
    assert body["declarations"] == [
        {
            "name": "label",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        }
    ]
    assert body["rows"] == [["2024-06-01"]]


def test_query_encodes_date_as_calendar_day(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    near_midnight = datetime(2024, 6, 2, 1, 0, tzinfo=timezone(timedelta(hours=8)))
    body = _query(
        client,
        monkeypatch,
        key="calendar-date",
        engine="postgresql",
        columns=["born", "shifted"],
        rows=[[date(2024, 6, 1), near_midnight]],
        native_types=["date", "date"],
    )
    assert [item["temporal_kind"] for item in body["declarations"]] == ["date", "date"]
    assert body["rows"] == [["2024-06-01", "2024-06-02"]]


def test_query_encodes_time_without_date_or_offset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="clock-time",
        engine="postgresql",
        columns=["starts"],
        rows=[[time(1, 2, 3, 450000)]],
        native_types=["time without time zone"],
    )
    assert body["declarations"][0]["temporal_kind"] == "time"
    assert body["rows"] == [["01:02:03.45"]]


def test_query_encodes_local_datetime_without_offset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="local-stamp",
        engine="postgresql",
        columns=["happened"],
        rows=[[datetime.fromisoformat("2024-06-01T01:02:03.450000")]],
        native_types=["timestamp without time zone"],
    )
    assert body["declarations"][0]["temporal_kind"] == "local_datetime"
    assert body["rows"] == [["2024-06-01T01:02:03.45"]]


def test_query_keeps_time_zone_timestamp_fraction(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = datetime(2024, 6, 1, 1, 2, 3, 450000, tzinfo=timezone(timedelta(hours=8)))
    body = _query(
        client,
        monkeypatch,
        key="zoned-stamp",
        engine="postgresql",
        columns=["at"],
        rows=[[value]],
        native_types=["timestamp(3) with time zone"],
    )
    assert body["declarations"][0]["temporal_kind"] == "timestamp_with_time_zone"
    assert body["declarations"][0]["precision"] == 3
    assert body["rows"] == [["2024-06-01T01:02:03.45+08:00"]]
    assert body["rows"][0][0] != format_instant(value)


def test_mcp_run_sql_encodes_date_time_and_elapsed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client, key="mcp-temporal", engine="postgresql")
    elapsed = timedelta(days=1, seconds=3661, microseconds=500000)
    connector = _DriverConnector(
        columns=["born", "starts", "span", "note"],
        rows=[
            [
                date(2024, 6, 1),
                time(1, 2, 3),
                elapsed,
                datetime.fromisoformat("2024-06-01T01:02:03"),
            ]
        ],
        native_types=["date", "time", "interval", "text"],
    )
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine_name: connector,
    )

    def _forbid_instant(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("format_instant")

    monkeypatch.setattr("backend.metadata.mcp_server.format_instant", _forbid_instant)
    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "query-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    with mcp_authorization(f"Bearer {tok.json()['secret']}"):
        raw = asyncio.run(
            run_sql(
                source_locator_key=source["locator_key"],
                sql="SELECT 1",
                max_rows=10,
            )
        )
    payload = json.loads(raw)
    assert "error" not in payload
    assert [item["temporal_kind"] for item in payload["declarations"]] == [
        "date",
        "time",
        "interval",
        None,
    ]
    assert payload["rows"] == [
        ["2024-06-01", "01:02:03", "P1DT1H1M1.5S", "2024-06-01T01:02:03"]
    ]


def test_query_keeps_time_offset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = time(1, 2, 3, 450000, tzinfo=timezone(timedelta(hours=8)))
    body = _query(
        client,
        monkeypatch,
        key="offset-time",
        engine="postgresql",
        columns=["starts"],
        rows=[[value]],
        native_types=["time(6) with time zone"],
    )
    assert body["declarations"][0]["temporal_kind"] == "time_with_offset"
    assert body["declarations"][0]["precision"] == 6
    assert body["rows"] == [["01:02:03.45+08:00"]]


def test_query_does_not_treat_naive_zoned_timestamp_as_utc(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="naive-zoned",
        engine="postgresql",
        columns=["at"],
        rows=[[datetime.fromisoformat("2024-06-01T01:02:03.450000")]],
        native_types=["timestamptz"],
    )
    assert body["declarations"][0]["temporal_kind"] == "timestamp_with_time_zone"
    assert body["rows"] == [["2024-06-01T01:02:03.45"]]


def test_query_oracle_date_is_local_datetime(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="oracle-date",
        engine="oracle",
        columns=["created"],
        rows=[[datetime.fromisoformat("2024-06-02T15:04:05")]],
        native_types=["DATE"],
    )
    assert body["declarations"][0]["temporal_kind"] == "local_datetime"
    assert body["rows"] == [["2024-06-02T15:04:05"]]


def test_query_keeps_local_time_zone_wall_clock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = datetime(2024, 6, 1, 1, 2, 3, 450000, tzinfo=timezone(timedelta(hours=8)))
    body = _query(
        client,
        monkeypatch,
        key="oracle-ltz",
        engine="oracle",
        columns=["seen"],
        rows=[[value]],
        native_types=["TIMESTAMP WITH LOCAL TIME ZONE"],
    )
    assert body["declarations"][0]["temporal_kind"] == "timestamp_with_local_time_zone"
    assert body["rows"] == [["2024-06-01T01:02:03.45"]]


def test_query_keeps_calendar_interval_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="calendar-span",
        engine="oracle",
        columns=["tenure", "elapsed"],
        rows=[["1 year 2 mons", timedelta(seconds=90, microseconds=250000)]],
        native_types=["interval year(2) to month", "interval day(2) to second(6)"],
    )
    assert [item["temporal_kind"] for item in body["declarations"]] == [
        "interval_calendar",
        "interval_fixed",
    ]
    assert [item["precision"] for item in body["declarations"]] == [None, 6]
    assert body["rows"] == [["1 year 2 mons", "PT1M30.25S"]]


def test_query_keeps_driver_nullable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="nullability",
        engine="postgresql",
        columns=["born", "label"],
        rows=[[date(2024, 6, 1), "2024-06-01"]],
        native_types=["date", "text"],
        nullables=[False, None],
    )
    assert [item["nullable"] for item in body["declarations"]] == [False, None]
    assert body["rows"] == [["2024-06-01", "2024-06-01"]]


def test_query_sqlserver_datetime_stays_local(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="mssql-local",
        engine="mssql",
        columns=["at"],
        rows=[[datetime.fromisoformat("2024-01-02T03:04:05.000001")]],
        native_types=["datetime2(7)"],
    )
    assert body["declarations"][0]["temporal_kind"] == "local_datetime"
    assert body["declarations"][0]["precision"] == 7
    assert body["rows"] == [["2024-01-02T03:04:05.000001"]]


def test_query_interval_fractional_seconds_follow_second_or_type(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="interval-precision",
        engine="postgresql",
        columns=["fine", "own", "plain"],
        rows=[["P1D", "P1D", "P1D"]],
        native_types=[
            "interval day(2) to second(6)",
            "interval(3)",
            "interval day(2) to second",
        ],
    )
    assert [item["precision"] for item in body["declarations"]] == [6, 3, None]


def test_query_sqlserver_timestamp_is_not_a_clock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _query(
        client,
        monkeypatch,
        key="mssql-rowversion",
        engine="mssql",
        columns=["rv"],
        rows=[["00000000000007D1"]],
        native_types=["timestamp"],
    )
    assert body["declarations"][0]["temporal_kind"] is None
    assert body["declarations"][0]["precision"] is None
    assert body["rows"] == [["00000000000007D1"]]
