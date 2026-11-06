"""validate_sql checks a statement and resolves access without running it."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server import MCPServer

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import UserRecord, get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.access.compiler import compile_policy  # noqa: E402
from backend.entity.access.plan import load_head, load_policy  # noqa: E402
from backend.entity.access.records import GrantRecord, ProfileRecord  # noqa: E402
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.access.views import persist_ready  # noqa: E402
from backend.entity.ids import new_access_grant_id, new_access_profile_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED, PUBLISHING  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.mcp.catalog import MCP_TOOLS  # noqa: E402
from backend.entity.mcp.guidance import TOOL_DESCRIPTIONS  # noqa: E402
from backend.entity.mcp.server import mcp  # noqa: E402
from backend.entity.mcp.sql_prepare import prepare_entity_sql  # noqa: E402
from backend.entity.mcp.sql_tools import validate_sql  # noqa: E402
from backend.entity.store import get_entity_store  # noqa: E402
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
NOTE = {
    "name": "note",
    "type": "string",
    "required": False,
    "unique": False,
    "indexed": False,
    "description": "Note",
    "config": {"max_length": 64},
}


def _pat(client: TestClient, account: str) -> str:
    login = client.post(
        "/auth/login", json={"account": account, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    expires = format_instant(utc_now() + timedelta(days=7))
    created = client.post(
        "/tokens",
        json={"name": f"{account}-pat", "expires_at": expires},
    )
    assert created.status_code == 201, created.text
    return created.json()["secret"]


def _publish(
    client: TestClient,
    table_name: str,
    name: str,
    attributes: list[dict[str, Any]],
) -> tuple[str, dict[str, str]]:
    created = client.post(
        "/entities",
        json={
            "table_name": table_name,
            "name": name,
            "description": name,
            "attributes": attributes,
        },
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    detail = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert detail.status_code == 200, detail.text
    attribute_ids = {
        item["name"]: item["attribute_id"]
        for item in detail.json()["version"]["attributes"]
    }
    assert all(isinstance(value, str) and value for value in attribute_ids.values())
    return entity["id"], attribute_ids


def _profile(entity_id: str, columns: list[dict[str, str]], key: str, now: object) -> str:
    profile_id = new_access_profile_id()
    get_access_store().insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key=key,
            name=key,
            description=None,
            columns=columns,
            created_at=now,  # type: ignore[arg-type]
            updated_at=now,  # type: ignore[arg-type]
        )
    )
    return profile_id


def _grant(entity_id: str, profile_id: str, user_id: str, now: object) -> None:
    get_access_store().insert_grant(
        GrantRecord(
            id=new_access_grant_id(),
            entity_id=entity_id,
            subject_type="user",
            subject_id=user_id,
            profile_id=profile_id,
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,  # type: ignore[arg-type]
            updated_at=now,  # type: ignore[arg-type]
        )
    )


def _mark_views_ready(entity_id: str) -> None:
    head = load_head(entity_id)
    revision = get_access_store().revision(entity_id)
    persist_ready(head, compile_policy(load_policy(head, revision)), revision)


def _call(secret: str, sql: str) -> dict[str, Any]:
    with mcp_authorization(f"Bearer {secret}"):
        return json.loads(validate_sql(sql=sql))


def _ok(secret: str, sql: str) -> dict[str, Any]:
    payload = _call(secret, sql)
    assert "error" not in payload, payload
    return payload


def _error(secret: str, sql: str) -> dict[str, Any]:
    payload = _call(secret, sql)
    assert set(payload) == {"error"}, payload
    assert set(payload["error"]) == {"code", "message"}
    return payload


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


def _refuse_entity_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    def opened() -> None:
        raise AssertionError("entity pool opened")

    monkeypatch.setattr("backend.entity.entity_db.get_entity_engine", opened)
    monkeypatch.setattr("backend.entity.access.enforce.get_entity_engine", opened)
    monkeypatch.setattr("backend.entity.table_port.get_entity_engine", opened)


@pytest.fixture()
def world() -> dict[str, Any]:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
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
        key="entity_mcp_reader",
        name="Entity MCP reader",
        permissions=["console:access", "tokens:write", "entity:data_read"],
    )
    noread_role = create_role(
        roles,
        key="entity_mcp_noread",
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
    ids: dict[str, str] = {}
    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        now = utc_now()
        specs = (
            ("ent_alpha", "Alpha", [SKU]),
            ("ent_beta", "Beta", [SKU]),
            ("ent_hidden", "Hidden", [SKU]),
            ("ent_old", "Old", [SKU]),
            ("ent_gap", "Gap", [SKU]),
            ("ent_wait", "Wait", [SKU]),
            ("ent_next", "Next", [SKU]),
            ("ent_mask", "Mask", [SKU, NOTE]),
        )
        attributes: dict[str, dict[str, str]] = {}
        for table_name, name, columns in specs:
            entity_id, attribute_ids = _publish(client, table_name, name, columns)
            ids[table_name] = entity_id
            attributes[table_name] = attribute_ids

        def grant(table_name: str, columns: list[dict[str, str]], key: str) -> None:
            _grant(
                ids[table_name],
                _profile(ids[table_name], columns, key, now),
                reader.id,
                now,
            )

        for table_name in ("ent_alpha", "ent_beta", "ent_old", "ent_gap", "ent_wait", "ent_next"):
            sku = attributes[table_name]["sku"]
            grant(table_name, [{"attribute_id": sku, "level": "clear"}], "clear")
        mask_sku = attributes["ent_mask"]["sku"]
        mask_note = attributes["ent_mask"]["note"]
        grant(
            "ent_mask",
            [
                {"attribute_id": mask_sku, "level": "clear"},
                {"attribute_id": mask_note, "level": "clear"},
            ],
            "full",
        )
        grant(
            "ent_mask",
            [{"attribute_id": mask_sku, "level": "clear"}],
            "sku_only",
        )
        for table_name in ("ent_alpha", "ent_beta", "ent_old", "ent_next", "ent_mask"):
            _mark_views_ready(ids[table_name])

        gap = next(
            version
            for version in get_entity_store().list_all_versions(ids["ent_gap"])
            if version.publish_status == PUBLISHED
        )
        get_entity_store().save_version(replace(gap, materialized_attributes=[]))

        deprecated = client.post(f"/entities/{ids['ent_old']}/deprecate")
        assert deprecated.status_code == 200, deprecated.text

        opened = client.post(f"/entities/{ids['ent_next']}/versions", json={})
        assert opened.status_code == 201, opened.text
        successor = get_entity_store().get_version(opened.json()["version"]["id"])
        assert successor is not None
        successor.publish_status = PUBLISHING
        get_entity_store().save_version(successor)

        secrets = {
            "reader": _pat(client, "reader"),
            "noread": _pat(client, "noread"),
        }
    reader_user = get_user_store().get_by_account("reader")
    assert reader_user is not None
    return {"secrets": secrets, "ids": ids, "reader": reader_user}


def test_validate_sql_returns_one_entity(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_entity_pool(monkeypatch)
    payload = _ok(world["secrets"]["reader"], "SELECT sku FROM ent_alpha")
    assert payload == {"entities": ["ent_alpha"], "partial_columns": []}
    _assert_no_logs(world["ids"]["ent_alpha"])


def test_validate_sql_returns_a_join_and_row_varying_columns(
    world: dict[str, Any],
) -> None:
    joined = _ok(
        world["secrets"]["reader"],
        "SELECT ent_alpha.sku FROM ent_alpha JOIN ent_beta "
        "ON ent_alpha.sku = ent_beta.sku",
    )
    assert joined == {
        "entities": ["ent_alpha", "ent_beta"],
        "partial_columns": [],
    }
    named = _ok(world["secrets"]["reader"], "SELECT note FROM ent_mask")
    assert named == {
        "entities": ["ent_mask"],
        "partial_columns": [{"table_name": "ent_mask", "column": "note"}],
    }
    starred = _ok(world["secrets"]["reader"], "SELECT * FROM ent_mask")
    assert starred["entities"] == ["ent_mask"]
    assert starred["partial_columns"] == [{"table_name": "ent_mask", "column": "note"}]
    clear = _ok(world["secrets"]["reader"], "SELECT sku FROM ent_mask")
    assert clear["partial_columns"] == []
    _assert_no_logs(world["ids"]["ent_alpha"], world["ids"]["ent_beta"], world["ids"]["ent_mask"])


def test_validate_sql_maps_gate_rejections(world: dict[str, Any]) -> None:
    rejected = _error(world["secrets"]["reader"], "INSERT INTO ent_alpha VALUES (1)")
    assert rejected == {
        "error": {"code": "ENTITY_SQL_INVALID", "message": "INSERT is not allowed"}
    }
    multi = _error(world["secrets"]["reader"], "SELECT 1 FROM ent_alpha; SELECT 2")
    assert multi == {
        "error": {
            "code": "ENTITY_SQL_INVALID",
            "message": "Multiple statements are not allowed",
        }
    }
    gate_first = _error(
        world["secrets"]["reader"], "INSERT INTO no_such_entity VALUES (1)"
    )
    assert gate_first["error"]["code"] == "ENTITY_SQL_INVALID"
    _assert_no_logs(world["ids"]["ent_alpha"])


def test_unknown_and_invisible_names_share_not_found(world: dict[str, Any]) -> None:
    unknown = _error(world["secrets"]["reader"], "SELECT sku FROM no_such_entity")
    hidden = _error(world["secrets"]["reader"], "SELECT sku FROM ent_hidden")
    folded = _error(world["secrets"]["reader"], "SELECT sku FROM ENT_HIDDEN")
    assert unknown == _not_found("no_such_entity")
    assert hidden == _not_found("ent_hidden")
    assert folded == _not_found("ENT_HIDDEN")
    assert unknown["error"]["code"] == hidden["error"]["code"]
    _assert_no_logs(world["ids"]["ent_hidden"])


def test_validate_sql_uses_data_api_lifecycle_codes(world: dict[str, Any]) -> None:
    deprecated = _error(world["secrets"]["reader"], "SELECT sku FROM ent_old")
    assert deprecated == {
        "error": {
            "code": "ENTITY_DEPRECATED",
            "message": "A deprecated Business Entity is closed",
        }
    }
    missing_table = _error(
        world["secrets"]["reader"],
        "SELECT sku FROM ent_gap JOIN ent_old ON ent_gap.sku = ent_old.sku",
    )
    assert missing_table == {
        "error": {
            "code": "ENTITY_NOT_SERVING",
            "message": "Business Entity has no serving head table",
        }
    }
    pending = _error(world["secrets"]["reader"], "SELECT sku FROM ent_wait")
    assert pending == {
        "error": {
            "code": "ENTITY_ACCESS_PENDING",
            "message": "access configuration generating",
        }
    }
    serving = _ok(world["secrets"]["reader"], "SELECT sku FROM ent_next")
    assert serving == {"entities": ["ent_next"], "partial_columns": []}
    _assert_no_logs(
        world["ids"]["ent_old"],
        world["ids"]["ent_gap"],
        world["ids"]["ent_wait"],
        world["ids"]["ent_next"],
    )


def test_prepare_returns_bound_sql_and_per_entity_access(world: dict[str, Any]) -> None:
    user: UserRecord = world["reader"]
    sql = "SELECT sku FROM ent_alpha"
    prepared = prepare_entity_sql(sql, user)
    assert prepared.submitted_sql == sql
    assert prepared.entities == ("ent_alpha",)
    assert prepared.partial_columns == ()
    assert len(prepared.decisions) == 1
    access = prepared.decisions[0]
    assert access.action == "read"
    assert access.target.entity.table_name == "ent_alpha"
    assert access.outcome.grant_ids
    assert access.outcome.shape is not None
    view_name = access.outcome.shape.view_name
    assert prepared.views == {view_name: "ent_alpha"}
    assert view_name in prepared.bound_sql
    assert "entity_access" in prepared.bound_sql
    assert access.target.physical_table not in prepared.bound_sql
    assert access.target.read_relation
    assert "entity_data" not in prepared.bound_sql
    with mcp_authorization(f"Bearer {world['secrets']['reader']}"):
        text = validate_sql(sql=sql)
    assert view_name not in text
    assert access.target.physical_table not in text
    assert "entity_access" not in text
    assert "entity_data" not in text
    assert prepared.bound_sql not in text
    _assert_no_logs(world["ids"]["ent_alpha"])


def test_validate_sql_is_in_the_catalog_and_tools_list(world: dict[str, Any]) -> None:
    specs = [spec for spec in MCP_TOOLS if spec.name == "validate_sql"]
    assert len(specs) == 1
    assert specs[0].permission == "entity:data_read"
    assert specs[0].description == TOOL_DESCRIPTIONS["validate_sql"]
    registered = list(asyncio.run(MCPServer.list_tools(mcp)))
    tool = next(item for item in registered if item.name == "validate_sql")
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    with mcp_authorization(f"Bearer {world['secrets']['reader']}"):
        offered = [item.name for item in asyncio.run(mcp.list_tools())]
    assert "validate_sql" in offered
    with mcp_authorization(f"Bearer {world['secrets']['noread']}"):
        hidden = [item.name for item in asyncio.run(mcp.list_tools())]
    assert "validate_sql" not in hidden


def test_validate_sql_requires_the_actor_permission(world: dict[str, Any]) -> None:
    bare = json.loads(validate_sql(sql="SELECT 1"))
    assert bare == {
        "error": {
            "code": "AUTH_UNAUTHENTICATED",
            "message": "Not signed in or session expired",
        }
    }
    forbidden = _error(world["secrets"]["noread"], "SELECT sku FROM ent_alpha")
    assert forbidden == {
        "error": {
            "code": "AUTH_FORBIDDEN",
            "message": "Missing permission entity:data_read",
        }
    }
