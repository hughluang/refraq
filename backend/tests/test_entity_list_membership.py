"""List membership matches definition visibility and does not compile views."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.admin.roles import create_role, seed_roles
from backend.admin.role_store import get_role_store
from backend.admin.security import hash_password
from backend.admin.subjects.service import add_member, create_group
from backend.admin.user_store import get_user_store
from backend.core.time import utc_now
from backend.entity.access import plan as access_plan
from backend.entity import service as entity_service
from backend.entity.access.membership import person_of, readable_entity_ids
from backend.entity.access.records import GrantRecord, ProfileRecord, RestrictionRecord
from backend.entity.access.store import get_access_store
from backend.entity.ids import (
    new_access_grant_id,
    new_access_profile_id,
    new_access_restriction_id,
)
from backend.entity.service import _definition
from backend.main import app

SKU = {
    "name": "sku",
    "type": "string",
    "required": True,
    "unique": True,
    "indexed": False,
    "description": "SKU code",
    "config": {"max_length": 32},
}


@pytest.fixture()
def client() -> TestClient:
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
        assert login.status_code == 200, login.text
        yield test_client


def _publish(client: TestClient, table_name: str, name: str) -> tuple[str, str]:
    created = client.post(
        "/entities",
        json={
            "table_name": table_name,
            "name": name,
            "description": "A listed entity.",
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
    print("VERSION", detail.json()["version"])
    attribute_id = detail.json()["version"]["attributes"][0]["attribute_id"]
    assert isinstance(attribute_id, str) and attribute_id
    return entity["id"], attribute_id


def _profile(entity_id: str, key: str, attribute_id: str, now: datetime) -> str:
    profile_id = new_access_profile_id()
    get_access_store().insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key=key,
            name=key,
            description=None,
            columns=[{"attribute_id": attribute_id, "level": "clear"}],
            created_at=now,
            updated_at=now,
        )
    )
    return profile_id


def _grant(
    entity_id: str,
    profile_id: str,
    subject_type: str,
    subject_id: str,
    now: datetime,
    *,
    valid_until: datetime | None = None,
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
            valid_until=valid_until,
            created_at=now,
            updated_at=now,
        )
    )


def test_readable_entity_ids_matches_definition(client: TestClient) -> None:
    roles = get_role_store()
    reader_role = create_role(
        roles,
        key="membership_reader",
        name="Membership reader",
        permissions=["console:access", "entity:read"],
    )
    reader = get_user_store().create_user(
        account="membership-reader",
        display_name="Membership reader",
        password_hash=hash_password("secret"),
        role_id=reader_role.id,
        status="active",
    )
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    group = create_group(
        key="membership_east",
        name="Membership East",
        description=None,
        actor_user_id=admin.id,
        actor_token_id=None,
    )
    add_member(group.id, reader.id, actor_user_id=admin.id, actor_token_id=None)
    now = utc_now()
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)

    cases: dict[str, str] = {}
    for table_name in (
        "mem_user",
        "mem_role",
        "mem_group",
        "mem_none",
        "mem_expired",
        "mem_broken",
        "mem_hidden",
        "mem_two",
    ):
        entity_id, attribute_id = _publish(client, table_name, table_name)
        cases[table_name] = entity_id
        if table_name == "mem_none":
            continue
        if table_name == "mem_broken":
            profile_id = _profile(entity_id, "broken", "att_missing", now)
            _grant(entity_id, profile_id, "user", reader.id, now)
            continue
        if table_name == "mem_two":
            first = _profile(entity_id, "sales", attribute_id, now)
            second = _profile(entity_id, "finance", attribute_id, now)
            _grant(entity_id, first, "user", reader.id, now)
            _grant(entity_id, second, "user", reader.id, now)
            continue
        profile_id = _profile(entity_id, "clear", attribute_id, now)
        if table_name == "mem_user":
            _grant(entity_id, profile_id, "user", reader.id, now)
        elif table_name == "mem_role":
            _grant(entity_id, profile_id, "role", reader_role.id, now)
        elif table_name == "mem_group":
            _grant(entity_id, profile_id, "group", group.id, now)
        elif table_name == "mem_expired":
            _grant(entity_id, profile_id, "user", reader.id, now, valid_until=past)
        elif table_name == "mem_hidden":
            _grant(entity_id, profile_id, "user", reader.id, now)
            get_access_store().insert_restriction(
                RestrictionRecord(
                    id=new_access_restriction_id(),
                    entity_id=entity_id,
                    applies_to={"mode": "all", "subjects": []},
                    row_rule=None,
                    deny_columns=["att_missing"],
                    ceilings=[],
                    actions=["read"],
                    created_at=now,
                    updated_at=now,
                )
            )

    ids = list(cases.values())
    readable = readable_entity_ids(ids, person_of(reader))
    for entity_id in ids:
        assert (entity_id in readable) == _definition(reader, entity_id)[0]
    assert readable == {
        cases["mem_user"],
        cases["mem_role"],
        cases["mem_group"],
        cases["mem_two"],
    }


def test_narrow_list_does_not_compile_views(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    roles = get_role_store()
    reader_role = create_role(
        roles,
        key="list_reader",
        name="List reader",
        permissions=["console:access", "entity:read"],
    )
    reader = get_user_store().create_user(
        account="list-reader",
        display_name="List reader",
        password_hash=hash_password("secret"),
        role_id=reader_role.id,
        status="active",
    )
    now = utc_now()
    for index in range(3):
        entity_id, attribute_id = _publish(client, f"page_{index}", f"Page {index}")
        profile_id = _profile(entity_id, "clear", attribute_id, now)
        _grant(entity_id, profile_id, "user", reader.id, now)

    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login", json={"account": "list-reader", "password": "secret"}
    )
    assert logged_in.status_code == 200, logged_in.text

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("view compilation is not list membership")

    monkeypatch.setattr(access_plan, "load_policy", _forbidden)
    monkeypatch.setattr(access_plan, "_population", _forbidden)
    monkeypatch.setattr(entity_service, "load_policy", _forbidden)

    first = client.get("/entities", params={"limit": 1, "offset": 0})
    second = client.get("/entities", params={"limit": 1, "offset": 1})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_body = first.json()
    second_body = second.json()
    assert first_body["total"] == 3
    assert second_body["total"] == 3
    assert first_body["items"][0]["id"] != second_body["items"][0]["id"]
    assert first_body["items"][0]["current_version"]["table_name"] is None
    assert second_body["items"][0]["current_version"]["table_name"] is None
