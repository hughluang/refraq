"""run_sql on a PostgreSQL 18 entity database."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_ENV_KEYS = (
    "REFRAQ_STORE_BACKEND",
    "REFRAQ_SECRETS_MASTER_KEY",
    "CELERY_TASK_ALWAYS_EAGER",
    "CELERY_BROKER_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "ENTITY_DATABASE_URL",
    "ENTITY_READER_DATABASE_URL",
    "ENTITY_SIGNER_DATABASE_URL",
    "REFRAQ_PROCESS_ROLE",
    "REFRAQ_ENTITY_DB_POOL_SIZE",
    "REFRAQ_ENTITY_DB_MAX_OVERFLOW",
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


def _call(
    fn: Any,
    secret: str,
    *,
    request_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from backend.core.request_id import bind_request_id
    from backend.entity.mcp.actor import mcp_authorization

    async def _run() -> dict[str, Any]:
        with mcp_authorization(f"Bearer {secret}"):
            if request_id is None:
                body = await fn(**kwargs)
            else:
                with bind_request_id(request_id):
                    body = await fn(**kwargs)
            return json.loads(body)

    return asyncio.run(_run())


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in payload, payload
    return payload


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    names = [column["name"] for column in payload["columns"]]
    return [dict(zip(names, row, strict=True)) for row in payload["rows"]]


def _assert_public(payload: dict[str, Any], world: dict[str, Any]) -> None:
    rendered = json.dumps(payload)
    assert world["orders_physical"] not in rendered
    assert world["lines_physical"] not in rendered
    assert "entity_access" not in rendered
    assert "entity_data" not in rendered
    from backend.entity.access.store import get_access_store

    store = get_access_store()
    for entity_id in (world["orders_id"], world["lines_id"]):
        for item in store.logs_for_entity(entity_id):
            if item.view_name:
                assert item.view_name not in rendered
    assert world["opened"]["count"] == 0


def _sql_logs(entity_id: str, request_id: str) -> list[Any]:
    from backend.entity.access.store import get_access_store

    return [
        item
        for item in get_access_store().logs_for_entity(entity_id)
        if item.verb == "sql" and item.request_id == request_id
    ]


@pytest.fixture()
def sql_world():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_esql") as urls:
        yield from _serve(urls)


def _serve(urls: Any):
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ["REFRAQ_STORE_BACKEND"] = "memory"
    os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")
    os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
    os.environ["ENTITY_READER_DATABASE_URL"] = urls.reader_url
    os.environ["ENTITY_SIGNER_DATABASE_URL"] = urls.signer_url

    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role, seed_roles
    from backend.admin.security import hash_password
    from backend.core.config import get_settings, reset_settings_cache
    from backend.core.runtime import (
        current_process_role,
        reset_runtime_capacity,
        set_process_role,
    )
    from backend.core.time import format_instant, utc_now
    from backend.entity import entity_db, table_port
    from backend.entity.access import enforce
    from backend.entity.access.enforce import reset_signing_ring
    from backend.entity.access.plan import load_head
    from backend.entity.access.service import create_grant, create_profile, put_ladder
    from backend.entity.access.views import rebuild_entity_views
    from backend.entity.data import sql as data_sql
    from backend.entity.entity_db import (
        get_entity_engine,
        get_entity_reader_engine,
        reset_entity_engine,
    )
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.mcp.sql_tools import run_sql
    from backend.entity.records import (
        AttributeRecord,
        BusinessEntityRecord,
        EntityVersionRecord,
        attribute_to_dict,
    )
    from backend.entity.store import get_entity_store, reset_entity_store
    from backend.entity.table_name import compose_physical_table_name as compose_physical
    from backend.entity.table_port import PostgresEntityTablePort, bind_entity_table_port
    from backend.main import app
    from backend.tests.entity_access_oracle import prepare_legacy_entity

    reset_settings_cache()
    reset_entity_engine()
    reset_entity_store()
    reset_signing_ring()
    set_process_role("api")
    reset_runtime_capacity()
    real_owner = entity_db.get_entity_engine
    real_require = data_sql.require_entity_capacity
    real_reader_require = data_sql.require_entity_reader_capacity
    real_data_owner = data_sql.get_entity_engine
    real_enforce_owner = enforce.get_entity_engine
    real_enforce_settings = enforce.get_settings
    real_table_owner = table_port.get_entity_engine
    data_sql.require_entity_capacity = get_entity_engine
    data_sql.require_entity_reader_capacity = get_entity_reader_engine
    signing = get_settings().model_copy(update={"store_backend": "persistent"})
    enforce.get_settings = lambda: signing
    bind_entity_table_port(PostgresEntityTablePort())

    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    from backend.admin.user_store import get_user_store

    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin_role.id,
        status="active",
    )

    orders = f"ord_{uuid.uuid4().hex[:10]}"
    lines = f"lin_{uuid.uuid4().hex[:10]}"
    orders_version_id = new_version_id()
    lines_version_id = new_version_id()
    orders_physical, _shortened = compose_physical(orders, 1, orders_version_id)
    lines_physical, _lines_shortened = compose_physical(lines, 1, lines_version_id)
    order_attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=32,
        ),
        AttributeRecord(name="qty", type="integer"),
        AttributeRecord(name="note", type="text"),
        AttributeRecord(name="region", type="string", max_length=16),
    ]
    line_attrs = [
        AttributeRecord(
            name="line_no",
            type="string",
            required=True,
            unique=True,
            business_key=True,
            max_length=16,
        ),
        AttributeRecord(name="order_sku", type="string", max_length=32),
        AttributeRecord(name="amount", type="integer"),
    ]
    now = datetime.now(timezone.utc)

    def _entity(
        stem: str,
        version_id: str,
        name: str,
        attrs: list[AttributeRecord],
    ) -> BusinessEntityRecord:
        entity = BusinessEntityRecord(
            id=new_entity_id(),
            table_name=stem,
            name=name,
            description=name,
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
        return entity

    orders_entity = _entity(orders, orders_version_id, "Orders", order_attrs)
    lines_entity = _entity(lines, lines_version_id, "Lines", line_attrs)
    port = PostgresEntityTablePort()
    port.create_physical_table("entity_data", orders_physical, order_attrs)
    port.swap_stem_view(
        "entity_data", orders, physical=orders_physical, expected_target=None
    )
    port.create_physical_table("entity_data", lines_physical, line_attrs)
    port.swap_stem_view(
        "entity_data", lines, physical=lines_physical, expected_target=None
    )
    prepare_legacy_entity(orders_entity.id)
    prepare_legacy_entity(lines_entity.id)

    opened = {"count": 0}

    def _refuse_owner() -> None:
        opened["count"] += 1
        raise AssertionError("owner engine constructed")

    raw = {
        "E-HIGH": "shown-note-1234",
        "E-LOW": "secret-note-9999",
        "W-HIGH": "west-secret-abcd",
    }
    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        seeded = [("E-HIGH", 20, "east"), ("E-LOW", 1, "east"), ("W-HIGH", 30, "west")]
        for sku, qty, region in seeded:
            created = client.post(
                f"/entities/{orders}/create",
                json={
                    "values": {
                        "sku": sku,
                        "qty": qty,
                        "note": raw[sku],
                        "region": region,
                    }
                },
            )
            assert created.status_code == 201, created.text
        for line_no, order_sku, amount in (
            ("L1", "E-HIGH", 5),
            ("L2", "W-HIGH", 9),
            ("L3", "E-LOW", 1),
        ):
            created = client.post(
                f"/entities/{lines}/create",
                json={
                    "values": {
                        "line_no": line_no,
                        "order_sku": order_sku,
                        "amount": amount,
                    }
                },
            )
            assert created.status_code == 201, created.text

        def _reader(account: str) -> str:
            role = create_role(
                get_role_store(),
                key=account,
                name=account,
                permissions=["console:access", "tokens:write", "entity:data_read"],
            )
            user = get_user_store().create_user(
                account=account,
                display_name=account,
                password_hash=hash_password("secret"),
                role_id=role.id,
                status="active",
            )
            return user.id

        masked_id = _reader("masked")
        combo_id = _reader("combo")
        order_ids = {
            attr.name: attr.attribute_id
            for attr in load_head(orders_entity.id).attributes
        }
        line_ids = {
            attr.name: attr.attribute_id
            for attr in load_head(lines_entity.id).attributes
        }
        put_ladder(
            orders_entity.id,
            order_ids["note"],
            [
                {"key": "clear", "mode": "clear"},
                {
                    "key": "last4",
                    "mode": {"type": "partial", "keep_first": 0, "keep_last": 4},
                },
            ],
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        masked_orders = create_profile(
            orders_entity.id,
            key="masked_east",
            name="Masked east",
            description=None,
            columns=[
                {"attribute_id": order_ids["sku"], "level": "clear"},
                {"attribute_id": order_ids["note"], "level": "last4"},
                {"attribute_id": order_ids["region"], "level": "clear"},
            ],
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        create_grant(
            orders_entity.id,
            subject={"type": "user", "id": masked_id},
            profile_id=masked_orders["profile"]["id"],
            row_rule={"eq": {"attr": order_ids["region"], "value": "east"}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        high_profile = create_profile(
            orders_entity.id,
            key="with_note",
            name="With note",
            description=None,
            columns=[
                {"attribute_id": order_ids["sku"], "level": "clear"},
                {"attribute_id": order_ids["qty"], "level": "clear"},
                {"attribute_id": order_ids["note"], "level": "clear"},
                {"attribute_id": order_ids["region"], "level": "clear"},
            ],
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        create_grant(
            orders_entity.id,
            subject={"type": "user", "id": combo_id},
            profile_id=high_profile["profile"]["id"],
            row_rule={"gte": {"attr": order_ids["qty"], "value": 10}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        low_profile = create_profile(
            orders_entity.id,
            key="without_note",
            name="Without note",
            description=None,
            columns=[
                {"attribute_id": order_ids["sku"], "level": "clear"},
                {"attribute_id": order_ids["qty"], "level": "clear"},
                {"attribute_id": order_ids["region"], "level": "clear"},
            ],
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        create_grant(
            orders_entity.id,
            subject={"type": "user", "id": combo_id},
            profile_id=low_profile["profile"]["id"],
            row_rule={"lt": {"attr": order_ids["qty"], "value": 10}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        masked_lines = create_profile(
            lines_entity.id,
            key="large_lines",
            name="Large lines",
            description=None,
            columns=[
                {"attribute_id": line_ids["line_no"], "level": "clear"},
                {"attribute_id": line_ids["order_sku"], "level": "clear"},
                {"attribute_id": line_ids["amount"], "level": "clear"},
            ],
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        create_grant(
            lines_entity.id,
            subject={"type": "user", "id": masked_id},
            profile_id=masked_lines["profile"]["id"],
            row_rule={"gte": {"attr": line_ids["amount"], "value": 5}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        combo_lines = create_profile(
            lines_entity.id,
            key="all_lines",
            name="All lines",
            description=None,
            columns=[
                {"attribute_id": line_ids["line_no"], "level": "clear"},
                {"attribute_id": line_ids["order_sku"], "level": "clear"},
                {"attribute_id": line_ids["amount"], "level": "clear"},
            ],
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        create_grant(
            lines_entity.id,
            subject={"type": "user", "id": combo_id},
            profile_id=combo_lines["profile"]["id"],
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        rebuild_entity_views(orders_entity.id)
        rebuild_entity_views(lines_entity.id)

        def _pat(account: str) -> tuple[str, str]:
            logged_out = client.post("/auth/logout")
            assert logged_out.status_code == 200, logged_out.text
            signed_in = client.post(
                "/auth/login", json={"account": account, "password": "secret"}
            )
            assert signed_in.status_code == 200, signed_in.text
            expires = format_instant(utc_now() + timedelta(days=7))
            created = client.post(
                "/tokens",
                json={"name": f"{account}-pat", "expires_at": expires},
            )
            assert created.status_code == 201, created.text
            body = created.json()
            return body["secret"], body["token"]["id"]

        masked_secret, masked_token = _pat("masked")
        combo_secret, combo_token = _pat("combo")

    try:
        reset_signing_ring()
        reset_entity_engine()
        os.environ["REFRAQ_PROCESS_ROLE"] = "entity_mcp"
        os.environ["REFRAQ_ENTITY_DB_POOL_SIZE"] = "1"
        os.environ["REFRAQ_ENTITY_DB_MAX_OVERFLOW"] = "0"
        set_process_role("entity_mcp")
        reset_runtime_capacity()
        assert current_process_role() == "entity_mcp"
        entity_db.get_entity_engine = _refuse_owner
        enforce.get_entity_engine = _refuse_owner
        data_sql.get_entity_engine = _refuse_owner
        data_sql.require_entity_capacity = _refuse_owner
        table_port.get_entity_engine = _refuse_owner
        reset_signing_ring()
        yield {
            "orders": orders,
            "lines": lines,
            "orders_id": orders_entity.id,
            "lines_id": lines_entity.id,
            "orders_physical": orders_physical,
            "lines_physical": lines_physical,
            "raw": raw,
            "masked_id": masked_id,
            "masked_secret": masked_secret,
            "masked_token": masked_token,
            "combo_id": combo_id,
            "combo_secret": combo_secret,
            "combo_token": combo_token,
            "opened": opened,
            "run_sql": run_sql,
        }
    finally:
        entity_db.get_entity_engine = real_owner
        enforce.get_entity_engine = real_enforce_owner
        enforce.get_settings = real_enforce_settings
        data_sql.get_entity_engine = real_data_owner
        data_sql.require_entity_capacity = real_require
        data_sql.require_entity_reader_capacity = real_reader_require
        table_port.get_entity_engine = real_table_owner
        os.environ.pop("REFRAQ_PROCESS_ROLE", None)
        set_process_role("api")
        reset_runtime_capacity()
        reset_signing_ring()
        reset_entity_engine()
        reset_settings_cache()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _two_users_see_different_rows_columns_and_join(
    sql_world: dict[str, Any],
) -> None:
    orders = sql_world["orders"]
    lines = sql_world["lines"]
    raw = sql_world["raw"]
    run_sql = sql_world["run_sql"]
    listed = f"SELECT * FROM {orders} ORDER BY sku"
    masked = _ok(_call(run_sql, sql_world["masked_secret"], sql=listed))
    combo = _ok(_call(run_sql, sql_world["combo_secret"], sql=listed))
    _assert_public(masked, sql_world)
    _assert_public(combo, sql_world)
    assert {column["name"] for column in masked["columns"]} == {
        "row_id",
        "sku",
        "note",
        "region",
    }
    assert {column["name"] for column in combo["columns"]} == {
        "row_id",
        "sku",
        "qty",
        "note",
        "region",
        "__withheld",
    }
    masked_rows = _records(masked)
    combo_rows = _records(combo)
    assert [row["sku"] for row in masked_rows] == ["E-HIGH", "E-LOW"]
    assert [row["sku"] for row in combo_rows] == ["E-HIGH", "E-LOW", "W-HIGH"]
    assert masked_rows[0]["note"].endswith("1234")
    assert raw["E-HIGH"] not in json.dumps(masked)
    assert raw["W-HIGH"] not in json.dumps(masked)
    assert combo_rows[0]["note"] == raw["E-HIGH"]
    assert combo_rows[0]["qty"] == 20
    assert combo_rows[1]["note"] is None
    assert combo_rows[1]["__withheld"] == ["note"]
    assert combo_rows[2]["note"] == raw["W-HIGH"]
    assert raw["E-LOW"] not in json.dumps(combo)
    qty = next(column for column in combo["columns"] if column["name"] == "qty")
    assert qty["type"] == "int8"
    assert isinstance(combo_rows[0]["qty"], int)

    joined_sql = (
        f"SELECT o.sku, o.note, l.line_no FROM {orders} o "
        f"JOIN {lines} l ON l.order_sku = o.sku "
        "ORDER BY o.sku, l.line_no"
    )
    request_id = uuid.uuid4().hex
    masked_join = _ok(
        _call(
            run_sql,
            sql_world["masked_secret"],
            request_id=request_id,
            sql=joined_sql,
        )
    )
    combo_request = uuid.uuid4().hex
    combo_join = _ok(
        _call(
            run_sql,
            sql_world["combo_secret"],
            request_id=combo_request,
            sql=joined_sql,
        )
    )
    _assert_public(masked_join, sql_world)
    _assert_public(combo_join, sql_world)
    assert _records(masked_join) == [
        {"sku": "E-HIGH", "note": masked_rows[0]["note"], "line_no": "L1"}
    ]
    assert masked_join["partial_columns"] == []
    assert _records(combo_join) == [
        {"sku": "E-HIGH", "note": raw["E-HIGH"], "line_no": "L1"},
        {"sku": "E-LOW", "note": None, "line_no": "L3"},
        {"sku": "W-HIGH", "note": raw["W-HIGH"], "line_no": "L2"},
    ]
    assert combo_join["partial_columns"] == [
        {"table_name": orders, "column": "note"}
    ]
    assert combo_join["sql"] == joined_sql
    assert combo_join["entities"] == sorted([orders, lines])
    assert combo_join["row_count"] == 3
    assert combo_join["truncated"] is False
    digest = hashlib.sha256(joined_sql.encode("utf-8")).hexdigest()
    order_logs = _sql_logs(sql_world["orders_id"], combo_request)
    line_logs = _sql_logs(sql_world["lines_id"], combo_request)
    assert len(order_logs) == 1
    assert len(line_logs) == 1
    assert order_logs[0].request_id == line_logs[0].request_id == combo_request
    assert order_logs[0].pat_id == line_logs[0].pat_id == sql_world["combo_token"]
    assert order_logs[0].user_id == line_logs[0].user_id == sql_world["combo_id"]
    assert order_logs[0].sql_sha256 == line_logs[0].sql_sha256 == digest
    assert order_logs[0].statement_summary == line_logs[0].statement_summary == joined_sql
    assert order_logs[0].row_count == line_logs[0].row_count == 3
    assert order_logs[0].outcome_code == line_logs[0].outcome_code == "ok"
    assert order_logs[0].verb == line_logs[0].verb == "sql"
    assert order_logs[0].view_name and line_logs[0].view_name
    assert order_logs[0].view_name != line_logs[0].view_name
    assert order_logs[0].effective_grant_ids
    assert line_logs[0].effective_grant_ids
    assert order_logs[0].duration_ms >= 0
    assert isinstance(order_logs[0].policy_revision, int)

    from backend.admin.audit_store import get_audit_store
    from backend.core.time import utc_now

    before = utc_now()
    _ok(_call(run_sql, sql_world["combo_secret"], sql=f"SELECT sku FROM {orders}"))
    events, _cursor = get_audit_store().list_events(from_dt=before, limit=50)
    assert events == []


def _withheld_cell_is_null_and_listed(
    sql_world: dict[str, Any],
) -> None:
    orders = sql_world["orders"]
    sql = (
        f"SELECT sku, note, __withheld FROM {orders} "
        "WHERE sku = 'E-LOW'"
    )
    payload = _ok(_call(sql_world["run_sql"], sql_world["combo_secret"], sql=sql))
    _assert_public(payload, sql_world)
    assert payload["partial_columns"] == [{"table_name": orders, "column": "note"}]
    row = _records(payload)[0]
    assert row["sku"] == "E-LOW"
    assert row["note"] is None
    assert row["__withheld"] == ["note"]
    withheld = next(column for column in payload["columns"] if column["name"] == "__withheld")
    assert withheld["type"] == "_text"


def _aggregates_windows_and_ctes_follow_each_grant(
    sql_world: dict[str, Any],
) -> None:
    orders = sql_world["orders"]
    sql = (
        "WITH counted AS ("
        f" SELECT region, count(*) AS n FROM {orders} GROUP BY region"
        ") "
        "SELECT region, n, sum(n) OVER () AS total FROM counted ORDER BY region"
    )
    masked = _ok(_call(sql_world["run_sql"], sql_world["masked_secret"], sql=sql))
    combo = _ok(_call(sql_world["run_sql"], sql_world["combo_secret"], sql=sql))
    _assert_public(masked, sql_world)
    _assert_public(combo, sql_world)
    assert _records(masked) == [{"region": "east", "n": 2, "total": "2"}]
    assert _records(combo) == [
        {"region": "east", "n": 2, "total": "3"},
        {"region": "west", "n": 1, "total": "3"},
    ]
    total = next(column for column in combo["columns"] if column["name"] == "total")
    count = next(column for column in combo["columns"] if column["name"] == "n")
    assert count["type"] == "int8"
    assert total["type"] == "numeric"


def _forged_and_expired_context_return_no_rows(
    sql_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.entity.access.context import load_shared_ring, sign_payload
    from backend.entity.entity_db import get_entity_signer_engine

    orders = sql_world["orders"]
    sql = f"SELECT sku FROM {orders} ORDER BY sku"
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.issue_contexts",
        lambda *args, **kwargs: "forged-token",
    )
    forged = _ok(_call(sql_world["run_sql"], sql_world["combo_secret"], sql=sql))
    assert forged["rows"] == []
    assert forged["row_count"] == 0
    assert "forged-token" not in json.dumps(forged)
    _assert_public(forged, sql_world)

    with get_entity_signer_engine().connect() as conn:
        ring = load_shared_ring(conn)
        conn.rollback()
    key = ring.current()
    expired_token = sign_payload(
        {
            "sub": sql_world["combo_id"],
            "grants": ["grant-expired"],
            "attrs": {},
            "rev": {sql_world["orders_id"]: 1},
            "exp": 1,
            "req": "",
            "kid": key.kid,
        },
        key.secret,
    )
    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.issue_contexts",
        lambda *args, **kwargs: expired_token,
    )
    expired = _ok(_call(sql_world["run_sql"], sql_world["combo_secret"], sql=sql))
    assert expired["rows"] == []
    assert expired["row_count"] == 0
    assert expired_token not in json.dumps(expired)
    assert "error" not in expired
    _assert_public(expired, sql_world)
    monkeypatch.undo()


def _catalog_profile_and_physical_names_are_refused(
    sql_world: dict[str, Any],
) -> None:
    from backend.entity.access.store import get_access_store

    orders = sql_world["orders"]
    secret = sql_world["masked_secret"]
    run_sql = sql_world["run_sql"]
    before = {
        entity_id: len(get_access_store().logs_for_entity(entity_id))
        for entity_id in (sql_world["orders_id"], sql_world["lines_id"])
    }
    view_names = [
        item.view_name
        for item in get_access_store().bindings(sql_world["orders_id"])
        if item.view_name
    ]
    assert view_names
    refused = {
        "SELECT pg_get_viewdef(0)": (
            "ENTITY_SQL_INVALID",
            "Function pg_get_viewdef is not allowed",
        ),
        "SELECT * FROM pg_catalog.pg_class": (
            "ENTITY_SQL_INVALID",
            "Schema-qualified relation pg_catalog.pg_class is not allowed",
        ),
        f"SELECT * FROM entity_data.{orders}": (
            "ENTITY_SQL_INVALID",
            f"Schema-qualified relation entity_data.{orders} is not allowed",
        ),
        f"SELECT * FROM {sql_world['orders_physical']}": (
            "ENTITY_NOT_FOUND",
            "Business Entity with table_name "
            f"'{sql_world['orders_physical']}' was not found",
        ),
        f"SELECT * FROM {view_names[0]}": (
            "ENTITY_NOT_FOUND",
            f"Business Entity with table_name '{view_names[0]}' was not found",
        ),
    }
    for sql, (code, message) in refused.items():
        payload = _call(run_sql, secret, sql=sql)
        assert payload == {"error": {"code": code, "message": message}}
    after = {
        entity_id: len(get_access_store().logs_for_entity(entity_id))
        for entity_id in (sql_world["orders_id"], sql_world["lines_id"])
    }
    assert after == before
    assert sql_world["opened"]["count"] == 0


def _timeout_truncation_and_row_cap(
    sql_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    orders = sql_world["orders"]
    run_sql = sql_world["run_sql"]
    secret = sql_world["combo_secret"]
    listed = f"SELECT sku FROM {orders} ORDER BY sku"
    one = _ok(_call(run_sql, secret, sql=listed, max_rows=1))
    assert one["max_rows"] == 1
    assert one["truncated"] is True
    assert one["row_count"] == 1
    assert one["rows"] == [["E-HIGH"]]
    clamped = _ok(_call(run_sql, secret, sql=listed, max_rows=0))
    assert clamped["max_rows"] == 1
    assert clamped["truncated"] is True
    negative = _ok(_call(run_sql, secret, sql=listed, max_rows=-4))
    assert negative["max_rows"] == 1
    wide = _ok(_call(run_sql, secret, sql=listed, max_rows=100_000))
    assert wide["max_rows"] == 1000
    assert wide["truncated"] is False
    assert wide["row_count"] == 3
    _assert_public(wide, sql_world)

    monkeypatch.setattr(
        "backend.entity.mcp.sql_run.entity_query_timeout_sec",
        lambda: 1,
    )
    request_id = uuid.uuid4().hex
    slow = (
        f"SELECT sum(g) FROM {orders} "
        "CROSS JOIN generate_series(1, 100000000) AS g"
    )
    timed = _call(run_sql, secret, request_id=request_id, sql=slow)
    assert timed["error"]["code"] == "ENTITY_SQL_TIMEOUT"
    assert "entity_access" not in timed["error"]["message"]
    assert sql_world["orders_physical"] not in timed["error"]["message"]
    logs = _sql_logs(sql_world["orders_id"], request_id)
    assert len(logs) == 1
    assert logs[0].outcome_code == "ENTITY_SQL_TIMEOUT"
    assert logs[0].row_count is None
    assert logs[0].pat_id == sql_world["combo_token"]
    assert sql_world["opened"]["count"] == 0
    monkeypatch.undo()


def _database_error_names_the_entity_not_the_view(
    sql_world: dict[str, Any],
) -> None:
    from backend.entity.access.store import get_access_store

    orders = sql_world["orders"]
    request_id = uuid.uuid4().hex
    sql = f"SELECT sku::integer FROM {orders}"
    payload = _call(
        sql_world["run_sql"],
        sql_world["combo_secret"],
        request_id=request_id,
        sql=sql,
    )
    assert payload["error"]["code"] == "ENTITY_SQL_FAILED"
    message = payload["error"]["message"]
    assert "SQLSTATE 22P02" in message
    assert "entity_access" not in message
    assert "entity_data" not in message
    assert sql_world["orders_physical"] not in message
    logs = _sql_logs(sql_world["orders_id"], request_id)
    assert len(logs) == 1
    assert logs[0].outcome_code == "ENTITY_SQL_FAILED"
    assert logs[0].row_count is None
    assert logs[0].view_name
    assert logs[0].view_name not in message
    for item in get_access_store().bindings(sql_world["orders_id"]):
        assert item.view_name not in message
    assert sql_world["opened"]["count"] == 0


def _constant_select_writes_no_access_log(sql_world: dict[str, Any]) -> None:
    from backend.entity.access.store import get_access_store

    before = {
        entity_id: [
            item.verb
            for item in get_access_store().logs_for_entity(entity_id)
        ]
        for entity_id in (sql_world["orders_id"], sql_world["lines_id"])
    }
    sql = "SELECT 1 AS n"
    payload = _ok(_call(sql_world["run_sql"], sql_world["combo_secret"], sql=sql))
    assert payload["sql"] == sql
    assert payload["entities"] == []
    assert payload["partial_columns"] == []
    assert payload["rows"] == [[1]]
    assert payload["row_count"] == 1
    assert payload["truncated"] is False
    assert payload["columns"] == [{"name": "n", "type": "int4"}]
    after = {
        entity_id: [
            item.verb
            for item in get_access_store().logs_for_entity(entity_id)
        ]
        for entity_id in (sql_world["orders_id"], sql_world["lines_id"])
    }
    assert after == before
    _assert_public(payload, sql_world)


def test_run_sql_on_postgresql(
    sql_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_users_see_different_rows_columns_and_join(sql_world)
    _withheld_cell_is_null_and_listed(sql_world)
    _aggregates_windows_and_ctes_follow_each_grant(sql_world)
    _forged_and_expired_context_return_no_rows(sql_world, monkeypatch)
    _catalog_profile_and_physical_names_are_refused(sql_world)
    _timeout_truncation_and_row_cap(sql_world, monkeypatch)
    _database_error_names_the_entity_not_the_view(sql_world)
    _constant_select_writes_no_access_log(sql_world)
