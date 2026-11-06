"""list_entities returns the caller's serving read grants, paged and searchable."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.subjects.service import add_member, create_group  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.entity.access.records import GrantRecord, ProfileRecord  # noqa: E402
from backend.entity.access.store import get_access_store  # noqa: E402
from backend.entity.ids import new_access_grant_id, new_access_profile_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHING  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.mcp.server import list_entities  # noqa: E402
from backend.entity.store import get_entity_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.api import replace_assignment  # noqa: E402
from backend.tags.store import reset_tag_store  # noqa: E402
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


def _publish(client: TestClient, table_name: str, name: str, description: str) -> tuple[str, str]:
    created = client.post(
        "/entities",
        json={
            "table_name": table_name,
            "name": name,
            "description": description,
            "attributes": [SKU],
        },
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    detail = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert detail.status_code == 200, detail.text
    attribute_id = detail.json()["version"]["attributes"][0]["attribute_id"]
    assert isinstance(attribute_id, str) and attribute_id
    return entity["id"], attribute_id


def _profile(entity_id: str, attribute_id: str, now: object) -> str:
    profile_id = new_access_profile_id()
    get_access_store().insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key="clear",
            name="clear",
            description=None,
            columns=[{"attribute_id": attribute_id, "level": "clear"}],
            created_at=now,  # type: ignore[arg-type]
            updated_at=now,  # type: ignore[arg-type]
        )
    )
    return profile_id


def _grant(
    entity_id: str,
    profile_id: str,
    subject_type: str,
    subject_id: str,
    now: object,
) -> None:
    get_access_store().insert_grant(
        GrantRecord(
            id=new_access_grant_id(),
            entity_id=entity_id,
            subject_type=subject_type,
            subject_id=subject_id,
            profile_id=profile_id,
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,  # type: ignore[arg-type]
            updated_at=now,  # type: ignore[arg-type]
        )
    )


def _tool(secret: str, **kwargs: Any) -> dict[str, Any]:
    with mcp_authorization(f"Bearer {secret}"):
        payload = json.loads(list_entities(**kwargs))
    assert "error" not in payload, payload
    return payload


@pytest.fixture()
def listed() -> dict[str, str]:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_tag_store()
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
    writer_role = create_role(
        roles,
        key="entity_mcp_author",
        name="Entity MCP author",
        permissions=[
            "console:access",
            "tokens:write",
            "entity:data_read",
            "entity:write",
            "entity:access_manage",
        ],
    )
    reader = get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password(PASSWORD),
        role_id=reader_role.id,
        status="active",
    )
    get_user_store().create_user(
        account="author",
        display_name="Author",
        password_hash=hash_password(PASSWORD),
        role_id=writer_role.id,
        status="active",
    )
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    group = create_group(
        key="entity_mcp_east",
        name="Entity MCP East",
        description=None,
        actor_user_id=admin.id,
        actor_token_id=None,
    )
    add_member(group.id, reader.id, actor_user_id=admin.id, actor_token_id=None)
    secrets: dict[str, str] = {}
    with TestClient(app) as client:
        login = client.post(
            "/auth/login", json={"account": "admin", "password": PASSWORD}
        )
        assert login.status_code == 200, login.text
        now = utc_now()
        specs = (
            ("ent_alpha", "Alpha Goods", "Regional supply ledger", True),
            ("ent_mid", "Midpoint", "Warehouse balance", True),
            ("ent_zebra", "Zebra", "Last stop", True),
            ("ent_role", "Role Scoped", "Role ledger", True),
            ("ent_group", "Group Scoped", "Group ledger", True),
            ("ent_hidden", "Hidden Goods", "Regional supply secret", True),
            ("ent_draft", "Draft Goods", "Regional supply draft", False),
            ("ent_old", "Old Goods", "Regional supply retired", True),
            ("ent_successor", "Successor", "Head still serving", True),
        )
        built: dict[str, tuple[str, str]] = {}
        for table_name, name, description, publish in specs:
            if publish:
                built[table_name] = _publish(client, table_name, name, description)
            else:
                created = client.post(
                    "/entities",
                    json={
                        "table_name": table_name,
                        "name": name,
                        "description": description,
                        "attributes": [SKU],
                    },
                )
                assert created.status_code == 201, created.text
                entity_id = created.json()["entity"]["id"]
                version = get_entity_store().current_version(entity_id)
                assert version is not None
                attribute_id = f"att_{table_name}"
                version.attributes = [
                    replace(version.attributes[0], attribute_id=attribute_id)
                ]
                get_entity_store().save_version(version)
                built[table_name] = (entity_id, attribute_id)

        def grant_to(table_name: str, subject_type: str, subject_id: str) -> None:
            entity_id, attribute_id = built[table_name]
            _grant(
                entity_id,
                _profile(entity_id, attribute_id, now),
                subject_type,
                subject_id,
                now,
            )

        for table_name in (
            "ent_alpha",
            "ent_mid",
            "ent_zebra",
            "ent_draft",
            "ent_old",
            "ent_successor",
        ):
            grant_to(table_name, "user", reader.id)
        grant_to("ent_role", "role", reader_role.id)
        grant_to("ent_group", "group", group.id)

        successor_id, _attribute_id = built["ent_successor"]
        opened = client.post(f"/entities/{successor_id}/versions", json={})
        assert opened.status_code == 201, opened.text
        successor_version = get_entity_store().get_version(opened.json()["version"]["id"])
        assert successor_version is not None
        successor_version.publish_status = PUBLISHING
        get_entity_store().save_version(successor_version)

        old_id, _old_attribute = built["ent_old"]
        deprecated = client.post(f"/entities/{old_id}/deprecate")
        assert deprecated.status_code == 200, deprecated.text

        assigned = replace_assignment(
            kind="entity",
            subject_id=built["ent_alpha"][0],
            base_revision=1,
            tag_ids=[],
            names=["Ledger"],
            actor_user_id=admin.id,
            actor_token_id=None,
        )
        secrets["reader"] = _pat(client, "reader")
        secrets["author"] = _pat(client, "author")
        secrets["ledger_tag_id"] = assigned.tags[0].id
        yield secrets
    reset_tag_store()


def _names(payload: dict[str, Any]) -> list[str]:
    return [item["table_name"] for item in payload["items"]]


def test_list_entities_pages_readable_serving_entities(listed: dict[str, str]) -> None:
    page = _tool(listed["reader"])
    assert _names(page) == [
        "ent_alpha",
        "ent_group",
        "ent_mid",
        "ent_role",
        "ent_successor",
        "ent_zebra",
    ]
    assert page["total"] == 6
    assert page["limit"] == 50
    assert page["offset"] == 0
    alpha = page["items"][0]
    assert set(alpha) == {"table_name", "name", "description", "tags"}
    assert alpha["name"] == "Alpha Goods"
    assert alpha["description"] == "Regional supply ledger"
    assert alpha["tags"] == [{"id": listed["ledger_tag_id"], "name": "Ledger"}]
    assert page["items"][1]["tags"] == []

    supply = _tool(listed["reader"], query_text="SUPPLY")
    assert _names(supply) == ["ent_alpha"]
    assert supply["total"] == 1

    ledgers = _tool(listed["reader"], query_text="ledger")
    assert _names(ledgers) == ["ent_alpha", "ent_group", "ent_role"]

    assert _names(_tool(listed["reader"], query_text="ent_z")) == ["ent_zebra"]
    assert _names(_tool(listed["reader"], query_text="Midpoint")) == ["ent_mid"]

    window = _tool(listed["reader"], limit=2, offset=2)
    assert _names(window) == ["ent_mid", "ent_role"]
    assert window["total"] == 6
    assert window["limit"] == 2
    assert window["offset"] == 2

    clamped = _tool(listed["reader"], limit=1000, offset=-4)
    assert clamped["limit"] == 200
    assert clamped["offset"] == 0
    assert clamped["total"] == 6
    assert len(clamped["items"]) == 6

    floor = _tool(listed["reader"], limit=0)
    assert floor["limit"] == 1
    assert _names(floor) == ["ent_alpha"]

    past = _tool(listed["reader"], offset=50)
    assert past["items"] == []
    assert past["total"] == 6
    assert past["limit"] == 50
    assert past["offset"] == 50

    author = _tool(listed["author"])
    assert author["items"] == []
    assert author["total"] == 0
    assert author["limit"] == 50
    assert author["offset"] == 0
