"""get_row and query_rows on a PostgreSQL 18 entity database."""

from __future__ import annotations

import asyncio
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


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _call(fn: Any, secret: str, **kwargs: Any) -> dict[str, Any]:
    from backend.entity.mcp.actor import mcp_authorization

    async def _run() -> dict[str, Any]:
        with mcp_authorization(f"Bearer {secret}"):
            return json.loads(await fn(**kwargs))

    return asyncio.run(_run())


@pytest.fixture()
def rows_world(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_emcp") as urls:
        yield from _serve(monkeypatch, urls)


def _serve(monkeypatch: pytest.MonkeyPatch, urls: Any):
    os.environ["REFRAQ_STORE_BACKEND"] = "memory"
    os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
    os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")

    monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
    monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
    monkeypatch.setenv("ENTITY_SIGNER_DATABASE_URL", urls.signer_url)
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")

    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role, seed_roles
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
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
    from backend.entity.access.store import get_access_store
    from backend.entity.access.views import rebuild_entity_views
    from backend.entity.data import sql as data_sql
    from backend.entity.entity_db import (
        get_entity_engine,
        get_entity_reader_engine,
        reset_entity_engine,
    )
    from backend.entity.ids import new_entity_id, new_version_id
    from backend.entity.lifecycle import PUBLISHED
    from backend.entity.mcp.rows import get_row, query_rows
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
    real_table_owner = table_port.get_entity_engine
    monkeypatch.setattr(data_sql, "require_entity_capacity", get_entity_engine)
    monkeypatch.setattr(
        data_sql, "require_entity_reader_capacity", get_entity_reader_engine
    )
    signing = get_settings().model_copy(update={"store_backend": "persistent"})
    monkeypatch.setattr(enforce, "get_settings", lambda: signing)
    bind_entity_table_port(PostgresEntityTablePort())

    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin_role.id,
        status="active",
    )

    stem = f"mat_{uuid.uuid4().hex[:10]}"
    hidden_stem = f"hid_{uuid.uuid4().hex[:10]}"
    version_id = new_version_id()
    physical, _shortened = compose_physical(stem, 1, version_id)
    attrs = [
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
    hidden = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=hidden_stem,
        name="Hidden",
        description="No grant",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    hidden_version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=hidden.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(hidden, hidden_version)

    port = PostgresEntityTablePort()
    port.create_physical_table("entity_data", physical, attrs)
    port.swap_stem_view("entity_data", stem, physical=physical, expected_target=None)
    prepare_legacy_entity(entity.id)

    opened = {"count": 0}

    def _refuse_owner() -> None:
        opened["count"] += 1
        raise AssertionError("owner engine constructed")

    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        raw = {
            "E-HIGH": "shown-note-1234",
            "E-LOW": "secret-note-9999",
            "W-HIGH": "west-secret-abcd",
        }
        seeded = [
            ("E-HIGH", 20, "east"),
            ("E-LOW", 1, "east"),
            ("W-HIGH", 30, "west"),
        ]
        row_ids: dict[str, int] = {}
        for sku, qty, region in seeded:
            created = client.post(
                f"/entities/{stem}/create",
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
            row_ids[sku] = created.json()["row"]["row_id"]

        def _reader(account: str) -> str:
            role = create_role(
                get_role_store(),
                key=account,
                name=account,
                permissions=[
                    "console:access",
                    "tokens:write",
                    "entity:data_read",
                ],
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
        ids = {
            attr.name: attr.attribute_id
            for attr in load_head(entity.id).attributes
        }
        assert all(isinstance(value, str) for value in ids.values())
        put_ladder(
            entity.id,
            ids["note"],
            [
                {"key": "clear", "mode": "clear"},
                {
                    "key": "last4",
                    "mode": {
                        "type": "partial",
                        "keep_first": 0,
                        "keep_last": 4,
                    },
                },
            ],
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        masked_profile = create_profile(
            entity.id,
            key="masked_east",
            name="Masked east",
            description=None,
            columns=[
                {"attribute_id": ids["sku"], "level": "clear"},
                {"attribute_id": ids["note"], "level": "last4"},
                {"attribute_id": ids["region"], "level": "clear"},
            ],
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        create_grant(
            entity.id,
            subject={"type": "user", "id": masked_id},
            profile_id=masked_profile["profile"]["id"],
            row_rule={"eq": {"attr": ids["region"], "value": "east"}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=masked_id,
            actor_token_id=None,
        )
        high_profile = create_profile(
            entity.id,
            key="with_note",
            name="With note",
            description=None,
            columns=[
                {"attribute_id": ids["sku"], "level": "clear"},
                {"attribute_id": ids["qty"], "level": "clear"},
                {"attribute_id": ids["note"], "level": "clear"},
                {"attribute_id": ids["region"], "level": "clear"},
            ],
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        create_grant(
            entity.id,
            subject={"type": "user", "id": combo_id},
            profile_id=high_profile["profile"]["id"],
            row_rule={"gte": {"attr": ids["qty"], "value": 10}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        low_profile = create_profile(
            entity.id,
            key="without_note",
            name="Without note",
            description=None,
            columns=[
                {"attribute_id": ids["sku"], "level": "clear"},
                {"attribute_id": ids["qty"], "level": "clear"},
                {"attribute_id": ids["region"], "level": "clear"},
            ],
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        create_grant(
            entity.id,
            subject={"type": "user", "id": combo_id},
            profile_id=low_profile["profile"]["id"],
            row_rule={"lt": {"attr": ids["qty"], "value": 10}},
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=combo_id,
            actor_token_id=None,
        )
        rebuild_entity_views(entity.id)

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
        monkeypatch.setenv("REFRAQ_PROCESS_ROLE", "entity_mcp")
        set_process_role("entity_mcp")
        reset_runtime_capacity()
        assert current_process_role() == "entity_mcp"
        monkeypatch.setattr(entity_db, "get_entity_engine", _refuse_owner)
        monkeypatch.setattr(enforce, "get_entity_engine", _refuse_owner)
        monkeypatch.setattr(data_sql, "get_entity_engine", _refuse_owner)
        monkeypatch.setattr(data_sql, "require_entity_capacity", _refuse_owner)
        monkeypatch.setattr(table_port, "get_entity_engine", _refuse_owner)
        reset_signing_ring()
        yield {
            "stem": stem,
            "hidden": hidden_stem,
            "hidden_id": hidden.id,
            "entity_id": entity.id,
            "row_ids": row_ids,
            "raw": raw,
            "masked_id": masked_id,
            "masked_secret": masked_secret,
            "masked_token": masked_token,
            "combo_id": combo_id,
            "combo_secret": combo_secret,
            "combo_token": combo_token,
            "opened": opened,
            "get_row": get_row,
            "query_rows": query_rows,
        }
    finally:
        entity_db.get_entity_engine = real_owner
        enforce.get_entity_engine = real_owner
        data_sql.get_entity_engine = real_owner
        data_sql.require_entity_capacity = real_require
        table_port.get_entity_engine = real_table_owner
        os.environ.pop("REFRAQ_PROCESS_ROLE", None)
        set_process_role("api")
        reset_runtime_capacity()
        reset_signing_ring()
        reset_entity_engine()
        reset_settings_cache()


def test_two_users_see_different_rows_columns_masks_and_withheld_cells(
    rows_world: dict[str, Any],
) -> None:
    stem = rows_world["stem"]
    raw = rows_world["raw"]
    row_ids = rows_world["row_ids"]
    get_row = rows_world["get_row"]
    query_rows = rows_world["query_rows"]
    masked_secret = rows_world["masked_secret"]
    combo_secret = rows_world["combo_secret"]

    masked_high = _call(
        get_row, masked_secret, table_name=stem, row_id=row_ids["E-HIGH"]
    )
    assert "error" not in masked_high, masked_high
    high_row = masked_high["row"]
    assert high_row["sku"] == "E-HIGH"
    assert high_row["region"] == "east"
    assert "qty" not in high_row
    assert "__withheld" not in high_row
    assert high_row["note"] != raw["E-HIGH"]
    assert high_row["note"].endswith("1234")
    assert raw["E-HIGH"] not in json.dumps(masked_high)

    by_key = _call(
        get_row, masked_secret, table_name=stem, business_key="E-LOW"
    )
    assert "error" not in by_key, by_key
    assert by_key["row"]["row_id"] == row_ids["E-LOW"]
    assert by_key["row"]["note"] != raw["E-LOW"]
    assert by_key["row"]["note"].endswith("9999")
    assert raw["E-LOW"] not in json.dumps(by_key)

    masked_page = _call(query_rows, masked_secret, table_name=stem)
    assert set(masked_page) == {"items", "total", "limit", "offset"}
    assert masked_page["limit"] == 50
    assert masked_page["offset"] == 0
    assert masked_page["total"] == 2
    masked_by_sku = {item["sku"]: item for item in masked_page["items"]}
    assert set(masked_by_sku) == {"E-HIGH", "E-LOW"}
    assert "W-HIGH" not in masked_by_sku
    assert raw["W-HIGH"] not in json.dumps(masked_page)

    west = _call(
        get_row, masked_secret, table_name=stem, row_id=row_ids["W-HIGH"]
    )
    assert west["error"]["code"] == "ENTITY_ROW_NOT_FOUND"

    combo_high = _call(
        get_row, combo_secret, table_name=stem, row_id=row_ids["E-HIGH"]
    )
    assert "error" not in combo_high, combo_high
    assert combo_high["row"]["note"] == raw["E-HIGH"]
    assert combo_high["row"]["qty"] == 20
    assert combo_high["row"]["__withheld"] == []

    combo_low = _call(
        get_row, combo_secret, table_name=stem, row_id=row_ids["E-LOW"]
    )
    assert "error" not in combo_low, combo_low
    assert combo_low["row"]["note"] is None
    assert combo_low["row"]["qty"] == 1
    assert combo_low["row"]["__withheld"] == ["note"]
    assert raw["E-LOW"] not in json.dumps(combo_low)

    combo_page = _call(query_rows, combo_secret, table_name=stem)
    assert combo_page["total"] == 3
    combo_by_sku = {item["sku"]: item for item in combo_page["items"]}
    assert set(combo_by_sku) == {"E-HIGH", "E-LOW", "W-HIGH"}
    assert combo_by_sku["W-HIGH"]["note"] == raw["W-HIGH"]
    assert combo_by_sku["W-HIGH"]["__withheld"] == []
    assert combo_by_sku["E-LOW"]["note"] is None
    assert combo_by_sku["E-LOW"]["__withheld"] == ["note"]

    subset = _call(query_rows, combo_secret, table_name=stem, fields=["sku"])
    subset_by_sku = {item["sku"]: item for item in subset["items"]}
    assert set(subset_by_sku["E-HIGH"]) == {"sku", "__withheld"}
    assert subset_by_sku["E-HIGH"]["__withheld"] == []
    assert subset_by_sku["E-LOW"]["__withheld"] == ["note"]

    keyset = _call(query_rows, combo_secret, table_name=stem, after_row_id=None)
    assert set(keyset) == {"items", "limit", "next_after_row_id"}
    assert keyset["limit"] == 50
    assert {item["sku"] for item in keyset["items"]} == {
        "E-HIGH",
        "E-LOW",
        "W-HIGH",
    }

    over_limit = _call(query_rows, masked_secret, table_name=stem, limit=201)
    assert over_limit == {
        "error": {"code": "REQUEST_INVALID", "message": "limit must be <= 200"}
    }

    from backend.entity.access.store import get_access_store

    hidden = rows_world["hidden"]
    unknown = _call(get_row, masked_secret, table_name="no_such_entity", row_id=1)
    invisible = _call(get_row, masked_secret, table_name=hidden, row_id=1)
    invisible_query = _call(query_rows, masked_secret, table_name=hidden)
    assert unknown == {
        "error": {
            "code": "ENTITY_NOT_FOUND",
            "message": "Business Entity with table_name 'no_such_entity' was not found",
        }
    }
    assert invisible == {
        "error": {
            "code": "ENTITY_NOT_FOUND",
            "message": (
                f"Business Entity with table_name '{hidden}' was not found"
            ),
        }
    }
    assert invisible_query["error"]["code"] == "ENTITY_NOT_FOUND"
    assert get_access_store().logs_for_entity(rows_world["hidden_id"]) == []

    logs = get_access_store().logs_for_entity(rows_world["entity_id"])
    masked_gets = [
        item
        for item in logs
        if item.verb == "get"
        and item.user_id == rows_world["masked_id"]
        and item.outcome_code == "ok"
    ]
    combo_queries = [
        item
        for item in logs
        if item.verb == "query"
        and item.user_id == rows_world["combo_id"]
        and item.outcome_code == "ok"
    ]
    invalid_limits = [
        item
        for item in logs
        if item.verb == "query"
        and item.user_id == rows_world["masked_id"]
        and item.outcome_code == "REQUEST_INVALID"
    ]
    assert masked_gets
    assert combo_queries
    assert invalid_limits
    assert {item.pat_id for item in masked_gets} == {rows_world["masked_token"]}
    assert {item.pat_id for item in combo_queries} == {rows_world["combo_token"]}
    assert {item.pat_id for item in invalid_limits} == {rows_world["masked_token"]}
    assert masked_gets[0].sql_sha256 is None
    assert masked_gets[0].statement_summary is None
    assert rows_world["opened"]["count"] == 0
