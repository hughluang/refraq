"""run_sql refusals that do not open an entity connection."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.bulkhead import reset_peek_bulkhead  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.runtime import reset_runtime_capacity  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.access.compiler import compile_policy  # noqa: E402
from backend.entity.access.plan import load_head, load_policy  # noqa: E402
from backend.entity.access.records import GrantRecord, ProfileRecord  # noqa: E402
from backend.entity.access.store import (  # noqa: E402
    get_access_store,
    reset_access_store,
)
from backend.entity.access.views import persist_ready  # noqa: E402
from backend.entity.ids import new_access_grant_id, new_access_profile_id  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.mcp.sql_tools import run_sql  # noqa: E402
from backend.entity.store import reset_entity_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.worker.app import celery_app  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

PASSWORD = "secret"
SKU = {
    "name": "sku",
    "type": "string",
    "required": True,
    "unique": True,
    "indexed": False,
    "description": "SKU code",
    "config": {"max_length": 32},
}


def _call(secret: str, **kwargs: Any) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        with mcp_authorization(f"Bearer {secret}"):
            return json.loads(await run_sql(**kwargs))

    return asyncio.run(_run())


def _not_found(table_name: str) -> dict[str, Any]:
    return {
        "error": {
            "code": "ENTITY_NOT_FOUND",
            "message": (
                f"Business Entity with table_name '{table_name}' was not found"
            ),
        }
    }


def _assert_no_logs(*entity_ids: str) -> None:
    store = get_access_store()
    for entity_id in entity_ids:
        assert store.logs_for_entity(entity_id) == []


@pytest.fixture()
def world() -> dict[str, Any]:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_entity_store()
    reset_access_store()
    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password(PASSWORD),
        role_id=admin_role.id,
        status="active",
    )
    reader_role = create_role(
        roles,
        key="sql_reader",
        name="SQL reader",
        permissions=["console:access", "tokens:write", "entity:data_read"],
    )
    noread_role = create_role(
        roles,
        key="sql_noread",
        name="No data read",
        permissions=["console:access", "tokens:write", "entity:write"],
    )
    reader = get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password(PASSWORD),
        role_id=reader_role.id,
        status="active",
    )
    get_user_store().create_user(
        account="noread",
        display_name="No read",
        password_hash=hash_password(PASSWORD),
        role_id=noread_role.id,
        status="active",
    )
    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        ids: dict[str, str] = {}
        attributes: dict[str, str] = {}
        for table_name in ("sql_alpha", "sql_hidden"):
            created = client.post(
                "/entities",
                json={
                    "table_name": table_name,
                    "name": table_name,
                    "description": table_name,
                    "attributes": [SKU],
                },
            )
            assert created.status_code == 201, created.text
            entity = created.json()["entity"]
            version_id = entity["current_version"]["id"]
            published = client.post(
                f"/entities/{entity['id']}/versions/{version_id}/publish"
            )
            assert published.status_code == 201, published.text
            detail = client.get(f"/entities/{entity['id']}/versions/{version_id}")
            assert detail.status_code == 200, detail.text
            attributes[table_name] = detail.json()["version"]["attributes"][0][
                "attribute_id"
            ]
            ids[table_name] = entity["id"]
        now = utc_now()
        profile_id = new_access_profile_id()
        get_access_store().insert_profile(
            ProfileRecord(
                id=profile_id,
                entity_id=ids["sql_alpha"],
                key="clear",
                name="clear",
                description=None,
                columns=[{"attribute_id": attributes["sql_alpha"], "level": "clear"}],
                created_at=now,
                updated_at=now,
            )
        )
        get_access_store().insert_grant(
            GrantRecord(
                id=new_access_grant_id(),
                entity_id=ids["sql_alpha"],
                subject_type="user",
                subject_id=reader.id,
                profile_id=profile_id,
                row_rule=None,
                actions=["read"],
                status="active",
                valid_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        head = load_head(ids["sql_alpha"])
        revision = get_access_store().revision(ids["sql_alpha"])
        persist_ready(head, compile_policy(load_policy(head, revision)), revision)

        def _pat(account: str) -> str:
            signed = client.post(
                "/auth/login", json={"account": account, "password": PASSWORD}
            )
            assert signed.status_code == 200, signed.text
            expires = format_instant(utc_now() + timedelta(days=7))
            created_token = client.post(
                "/tokens",
                json={"name": f"{account}-pat", "expires_at": expires},
            )
            assert created_token.status_code == 201, created_token.text
            return created_token.json()["secret"]

        secrets = {"reader": _pat("reader"), "noread": _pat("noread")}
    return {"ids": ids, "secrets": secrets}


def test_gate_rejection_writes_no_access_log(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _opened() -> None:
        raise AssertionError("entity pool opened")

    monkeypatch.setattr("backend.entity.mcp.sql_run.get_entity_reader_engine", _opened)
    monkeypatch.setattr("backend.entity.mcp.sql_run._signing_ring", _opened)
    monkeypatch.setattr("backend.entity.entity_db.get_entity_engine", _opened)
    secret = world["secrets"]["reader"]
    alpha = world["ids"]["sql_alpha"]
    hidden = world["ids"]["sql_hidden"]
    cases = {
        "DELETE FROM sql_alpha": {
            "code": "ENTITY_SQL_INVALID",
            "message": "DELETE is not allowed",
        },
        "SELECT pg_get_viewdef('v')": {
            "code": "ENTITY_SQL_INVALID",
            "message": "Function pg_get_viewdef is not allowed",
        },
        "SELECT * FROM pg_catalog.pg_class": {
            "code": "ENTITY_SQL_INVALID",
            "message": "Schema-qualified relation pg_catalog.pg_class is not allowed",
        },
        "SELECT * FROM entity_data.sql_alpha": {
            "code": "ENTITY_SQL_INVALID",
            "message": "Schema-qualified relation entity_data.sql_alpha is not allowed",
        },
    }
    for sql, error in cases.items():
        assert _call(secret, sql=sql) == {"error": error}
    assert _call(secret, sql="SELECT sku FROM no_such_entity") == _not_found(
        "no_such_entity"
    )
    assert _call(secret, sql="SELECT sku FROM sql_hidden") == _not_found("sql_hidden")
    _assert_no_logs(alpha, hidden)


def test_zero_admission_slots_return_the_tool_error(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRAQ_ADMISSION_SLOTS", "0")
    reset_runtime_capacity()
    reset_peek_bulkhead()
    try:
        refused = _call(world["secrets"]["reader"], sql="SELECT 1")
        assert refused == {
            "error": {
                "code": "ADMISSION_CAPACITY_EXCEEDED",
                "message": "Platform admission is at capacity",
            }
        }
        _assert_no_logs(world["ids"]["sql_alpha"], world["ids"]["sql_hidden"])
    finally:
        monkeypatch.delenv("REFRAQ_ADMISSION_SLOTS", raising=False)
        reset_runtime_capacity()
        reset_peek_bulkhead()


def test_statement_timeout_stays_entity_sql_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.entity.mcp.sql_prepare import PreparedSql
    from backend.entity.mcp.sql_run import _map_execution_error

    seen: list[str] = []
    monkeypatch.setattr(
        "backend.core.db.record_reject", lambda code: seen.append(code)
    )

    class _Cancel(Exception):
        sqlstate = "57014"

    class _Wrapped(Exception):
        def __init__(self) -> None:
            self.orig = _Cancel()

    prepared = PreparedSql(
        submitted_sql="SELECT 1",
        bound_sql="SELECT 1",
        entities=(),
        partial_columns=(),
        decisions=(),
        views={},
    )
    direct = _map_execution_error(_Cancel(), prepared)
    wrapped = _map_execution_error(_Wrapped(), prepared)
    assert direct.code == wrapped.code == "ENTITY_SQL_TIMEOUT"
    assert seen == []


def test_database_error_hides_bound_sql_and_relation_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    from types import SimpleNamespace

    from backend.entity.errors import EntitySqlFailed
    from backend.entity.mcp.sql_prepare import PreparedSql
    from backend.entity.mcp.sql_run import run_entity_sql

    access = SimpleNamespace(
        outcome=SimpleNamespace(
            shape=SimpleNamespace(view_name="orders__p_ab12cd34"),
            grant_ids=("g1",),
        ),
        target=SimpleNamespace(
            entity=SimpleNamespace(id="ent_orders", table_name="orders"),
            physical_table="orders__v1__deadbeef",
        ),
        full=SimpleNamespace(physical_table="orders__v1__deadbeef"),
        head=SimpleNamespace(physical="orders__v1__deadbeef"),
        revision=3,
    )
    submitted = "SELECT region FROM orders"
    bound = "SELECT region FROM orders__p_ab12cd34"
    prepared = PreparedSql(
        submitted_sql=submitted,
        bound_sql=bound,
        entities=("orders",),
        partial_columns=(),
        decisions=(access,),  # type: ignore[arg-type]
        views={"orders__p_ab12cd34": "orders"},
    )

    class _Bad(Exception):
        sqlstate = "22P02"

        def __init__(self) -> None:
            super().__init__(f"({bound})")
            self.diag = SimpleNamespace(
                message_primary=(
                    'relation "entity_access.orders__p_ab12cd34" does not exist; '
                    "see orders__v1__deadbeef"
                )
            )

    logs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.prepare_entity_sql", lambda sql, user: prepared
    )
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.entity_query_timeout_sec", lambda: 30
    )
    monkeypatch.setattr("backend.entity.mcp.sql_run.entity_query_max_rows", lambda: 100)
    monkeypatch.setattr("backend.entity.mcp.sql_run._sign", lambda *args, **kwargs: "tok")

    def _execute(*args: object, **kwargs: object) -> dict[str, Any]:
        raise _Bad()

    monkeypatch.setattr("backend.entity.mcp.sql_run._execute", _execute)
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.append_sql_log",
        lambda **kwargs: logs.append(kwargs),
    )
    with pytest.raises(EntitySqlFailed) as raised:
        run_entity_sql(
            submitted,
            _user(),
            pat_id="pat_1",
            request_id="req_1",
            max_rows=None,
        )
    message = raised.value.message
    assert message == (
        'relation "orders" does not exist; see orders (SQLSTATE 22P02)'
    )
    assert bound not in message
    assert "orders__p_ab12cd34" not in message
    assert "orders__v1__deadbeef" not in message
    assert "entity_access" not in message
    assert len(logs) == 1
    assert logs[0]["outcome_code"] == "ENTITY_SQL_FAILED"
    assert logs[0]["row_count"] is None
    assert logs[0]["view_name"] == "orders__p_ab12cd34"
    assert logs[0]["sql_sha256"] == hashlib.sha256(submitted.encode()).hexdigest()
    assert logs[0]["statement_summary"] == submitted
    assert logs[0]["pat_id"] == "pat_1"
    assert logs[0]["request_id"] == "req_1"


def test_pool_timeout_writes_no_sql_log(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    from backend.core.errors import PlatformCapacityExceeded
    from backend.entity.mcp.sql_prepare import PreparedSql
    from backend.entity.mcp.sql_run import run_entity_sql

    prepared = PreparedSql(
        submitted_sql="SELECT 1",
        bound_sql="SELECT 1",
        entities=(),
        partial_columns=(),
        decisions=(),
        views={},
    )
    logs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.prepare_entity_sql", lambda sql, user: prepared
    )
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.entity_query_timeout_sec", lambda: 30
    )
    monkeypatch.setattr("backend.entity.mcp.sql_run.entity_query_max_rows", lambda: 100)
    monkeypatch.setattr("backend.entity.mcp.sql_run._sign", lambda *args, **kwargs: "tok")
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.append_sql_log",
        lambda **kwargs: logs.append(kwargs),
    )

    class _Engine:
        def connect(self) -> None:
            raise PoolTimeoutError("pool")

    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.get_entity_reader_engine", lambda: _Engine()
    )
    with pytest.raises(PlatformCapacityExceeded):
        run_entity_sql(
            "SELECT 1",
            _user(),
            pat_id="pat_1",
            request_id="req_1",
            max_rows=None,
        )
    assert logs == []


def test_read_only_execution_rolls_back_and_hides_bound_sql() -> None:
    import json
    from types import SimpleNamespace

    from backend.entity.mcp.sql_prepare import PreparedSql
    from backend.entity.mcp.sql_run import _query

    class _SqlFailure(Exception):
        pass

    class _RollbackFailure(Exception):
        pass

    class _Column:
        def __init__(self, name: str, type_code: int) -> None:
            self.name = name
            self.type_code = type_code

    class _Tx:
        def __init__(self) -> None:
            self.rollbacks = 0
            self.error: BaseException | None = None

        def rollback(self) -> None:
            self.rollbacks += 1
            if self.error is not None:
                raise self.error

    class _Cursor:
        def __init__(self, raw: _Raw) -> None:
            self.raw = raw
            self.description = [_Column("region", 12345)]

        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def _execute_send(
            self,
            query: object,
            *,
            force_extended: bool = False,
            binary: object = None,
        ) -> None:
            self.raw.extended.append(force_extended)

        def execute(self, sql: str, params: object = None, **kwargs: object) -> None:
            self.raw.statements.append((sql, params))
            if self.raw.fail and params is None and "pg_type" not in sql:
                raise _SqlFailure()
            if params is None:
                # binary=True is how the runner selects PQsendQueryParams.
                self._execute_send(sql, force_extended=bool(kwargs.get("binary")))

        def fetchmany(self, _size: int) -> list[tuple[object, ...]]:
            return [("east",)]

        def fetchall(self) -> list[tuple[object, ...]]:
            return [(12345, "_orders__p_ab12cd34")]

    class _Raw:
        def __init__(self) -> None:
            self.statements: list[tuple[str, object]] = []
            self.extended: list[bool] = []
            self.fail = False

        def cursor(self) -> _Cursor:
            return _Cursor(self)

    class _Conn:
        def __init__(self, raw: _Raw) -> None:
            self.raw = raw
            self.connection = SimpleNamespace(driver_connection=raw)
            self.calls: list[tuple[str, object]] = []
            self.tx = _Tx()

        def begin(self) -> _Tx:
            return self.tx

        def exec_driver_sql(self, sql: str, params: object = None) -> None:
            self.calls.append((sql, params))

    submitted = "SELECT region FROM orders"
    bound = "SELECT region FROM orders__p_ab12cd34"
    prepared = PreparedSql(
        submitted_sql=submitted,
        bound_sql=bound,
        entities=("orders",),
        partial_columns=(),
        decisions=(),
        views={"orders__p_ab12cd34": "orders"},
    )
    raw = _Raw()
    conn = _Conn(raw)
    result = _query(conn, prepared, "signed-token", 10, 30)
    rendered = json.dumps(result)
    assert conn.tx.rollbacks == 1
    assert ("SET TRANSACTION READ ONLY", None) in conn.calls
    assert ("SELECT set_config('app.ctx', %s, true)", ("signed-token",)) in conn.calls
    assert ("SET LOCAL statement_timeout = 30000", None) in conn.calls
    assert raw.statements[0] == (bound, None)
    assert raw.extended == [True]
    assert raw.statements[1][0].startswith("SELECT oid, typname FROM pg_catalog.pg_type")
    assert result["sql"] == submitted
    assert result["columns"] == [{"name": "region", "type": "_orders"}]
    assert bound not in rendered
    assert "orders__p_ab12cd34" not in rendered
    assert "signed-token" not in rendered

    raw.fail = True
    failed = _Conn(raw)
    with pytest.raises(_SqlFailure):
        _query(failed, prepared, "signed-token", 10, 30)
    assert failed.tx.rollbacks == 1

    raw.fail = True
    swallowed = _Conn(raw)
    swallowed.tx.error = _RollbackFailure()
    with pytest.raises(_SqlFailure):
        _query(swallowed, prepared, "signed-token", 10, 30)
    assert swallowed.tx.rollbacks == 1


def _user() -> Any:
    from datetime import datetime, timezone

    from backend.admin.user_store import UserRecord

    return UserRecord(
        id="user_1",
        account="reader",
        display_name="Reader",
        password_hash=None,
        role_id="role_1",
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_missing_data_read_is_forbidden(world: dict[str, Any]) -> None:
    refused = _call(world["secrets"]["noread"], sql="SELECT sku FROM sql_alpha")
    assert refused == {
        "error": {
            "code": "AUTH_FORBIDDEN",
            "message": "Missing permission entity:data_read",
        }
    }
    _assert_no_logs(world["ids"]["sql_alpha"])
