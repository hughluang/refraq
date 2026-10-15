"""Live Source query node through Controlled Query."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store, reset_audit_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import ensure_system_user, get_user_store, reset_user_store  # noqa: E402
from backend.channel.executors import EXECUTORS  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.connectors.base import QueryResult  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402


class _Hooks:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.job_id = "job_channel_query"
        self._channel_id = "chn_channel_query"

    def evaluate(self, expression: str) -> Any:
        raise AssertionError(expression)


class _RecordingConnector:
    engine = "postgresql"

    def __init__(self, rows: list[list[Any]], columns: list[str]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rows = rows
        self._columns = columns

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
        self.calls.append({"sql": sql, "max_rows": max_rows, "timeout_sec": timeout_sec})
        limited = self._rows[:max_rows]
        return QueryResult(
            columns=self._columns,
            rows=limited,
            truncated=len(self._rows) > max_rows,
        )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_audit_store()
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
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200
        yield test_client


def _make_source(client: TestClient) -> dict:
    response = client.post(
        "/sources",
        json={
            "key": "mes-live",
            "name": "MES",
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "super-secret-password",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["source"]


def _node(source_id: str, sql: str, row_cap: int) -> dict:
    return {
        "id": "nd_lookup",
        "ref": "lookup",
        "type": "read.source_query",
        "name": "Lookup",
        "config": {"source_id": source_id, "sql": sql, "row_cap": row_cap},
    }


def test_source_query_node_uses_controlled_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_source(client)
    user = ensure_system_user(get_user_store())
    hooks = _Hooks(user)
    execute = EXECUTORS["read.source_query"]

    write_connector = _RecordingConnector(rows=[["1"]], columns=["n"])
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: write_connector,
    )
    rejected = execute(
        _node(source["id"], "INSERT INTO t VALUES (1)", 10),
        hooks,
    )
    assert rejected.status == "failed"
    assert rejected.error_code == "CHANNEL_NODE_FAILED"
    assert rejected.error_detail == {"code": "QUERY_NOT_READONLY"}
    assert rejected.error_message
    assert write_connector.calls == []
    failures = [
        event
        for event in get_audit_store().list_events(action="query.run")[0]
        if event.resource_id == source["id"] and event.result == "failure"
    ]
    assert len(failures) == 1
    assert failures[0].actor_user_id == user.id
    assert failures[0].detail["code"] == "QUERY_NOT_READONLY"
    assert failures[0].detail["channel_id"] == "chn_channel_query"
    assert failures[0].detail["job_id"] == "job_channel_query"
    assert failures[0].detail["node_id"] == "nd_lookup"
    assert "super-secret-password" not in str(failures[0].detail)

    read_connector = _RecordingConnector(
        rows=[["1001"], ["1002"], ["1003"]],
        columns=["WO_ID"],
    )
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: read_connector,
    )
    accepted = execute(_node(source["id"], "SELECT WO_ID FROM work_order", 2), hooks)
    assert accepted.status == "succeeded"
    assert accepted.output == {
        "rows": [{"WO_ID": "1001"}, {"WO_ID": "1002"}],
        "count": 2,
        "truncated": True,
    }
    assert read_connector.calls[0]["max_rows"] == 2
    successes = [
        event
        for event in get_audit_store().list_events(action="query.run")[0]
        if event.resource_id == source["id"] and event.result == "success"
    ]
    assert len(successes) == 1
    assert successes[0].actor_user_id == user.id
    assert successes[0].detail["channel_id"] == "chn_channel_query"
    assert successes[0].detail["job_id"] == "job_channel_query"
    assert successes[0].detail["node_id"] == "nd_lookup"
    assert "super-secret-password" not in str(successes[0].detail)
