"""User Groups, Subject Attributes, and effective values (docs/api-contracts-users.md §8–§9)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.role_store import RoleRecord, get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.subjects import (  # noqa: E402
    effective_subject_values,
    existing_group_ids,
    existing_user_ids,
    user_group_ids,
)
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.dictionaries.records import (  # noqa: E402
    DictionaryEntryRecord,
    DictionaryRecord,
)
from backend.entity.dictionaries.store import get_dictionary_store  # noqa: E402
from backend.main import app  # noqa: E402


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    operator = roles.get_by_key("operator")
    assert super_admin is not None and operator is not None
    roles.insert(
        RoleRecord(
            id="role_reader",
            key="user_reader",
            name="User reader",
            permissions=["console:access", "users:read"],
        )
    )
    users = get_user_store()
    users.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
        status="active",
    )
    users.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator.id,
        status="active",
    )
    users.create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("read-pass"),
        role_id="role_reader",
        status="active",
    )
    now = utc_now()
    get_dictionary_store().create(
        DictionaryRecord(
            id="dct_regions",
            name="regions",
            display_name="Regions",
            description=None,
            revision=1,
            deprecated_at=None,
            entries=(
                DictionaryEntryRecord(code="EAST", label="East", active=True, position=0),
                DictionaryEntryRecord(code="NORTH", label="North", active=True, position=1),
                DictionaryEntryRecord(code="WEST", label="West", active=False, position=2),
            ),
            created_at=now,
            updated_at=now,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def _root(client: TestClient) -> str:
    _login(client, "root", "s3cret")
    me = client.get("/auth/me")
    assert me.status_code == 200, me.text
    return me.json()["user"]["id"]


def test_operator_cannot_list_groups(client: TestClient) -> None:
    _login(client, "op", "op-pass")
    response = client.get("/user-groups")
    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"


def test_reader_can_list_but_not_create(client: TestClient) -> None:
    _login(client, "reader", "read-pass")
    assert client.get("/user-groups").status_code == 200
    denied = client.post(
        "/user-groups", json={"key": "east", "name": "East"}
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH_FORBIDDEN"


def test_group_membership_and_effective_values(client: TestClient) -> None:
    _root(client)
    created = client.post(
        "/user-groups",
        json={"key": "east_sales", "name": "East sales", "description": "  "},
    )
    assert created.status_code == 201, created.text
    group = created.json()["group"]
    assert group["key"] == "east_sales"
    assert group["description"] is None
    assert group["member_count"] == 0
    duplicate = client.post(
        "/user-groups", json={"key": "east_sales", "name": "Again"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "USER_GROUP_KEY_DUPLICATE"
    immutable = client.patch(
        f"/user-groups/{group['id']}", json={"key": "other", "name": "East"}
    )
    assert immutable.status_code == 422
    assert immutable.json()["code"] == "USER_GROUP_INVALID"

    ada = get_user_store().create_user(
        account="ada",
        display_name="Ada",
        password_hash=hash_password("ada-pass"),
        role_id="role_reader",
        status="disabled",
    )
    added = client.put(f"/user-groups/{group['id']}/members/{ada.id}")
    assert added.status_code == 204
    again = client.put(f"/user-groups/{group['id']}/members/{ada.id}")
    assert again.status_code == 204
    missing_user = client.put(f"/user-groups/{group['id']}/members/user_missing")
    assert missing_user.status_code == 404
    assert missing_user.json()["code"] == "USER_NOT_FOUND"
    listed = client.get(f"/user-groups/{group['id']}/members")
    assert listed.status_code == 200
    assert [item["account"] for item in listed.json()["items"]] == ["ada"]
    assert listed.json()["total"] == 1

    definition = client.post(
        "/subject-attributes",
        json={
            "key": "regions",
            "name": "Regions",
            "value_type": "dictionary",
            "dictionary_id": "dct_regions",
            "multi_value": True,
        },
    )
    assert definition.status_code == 201, definition.text
    owner = client.post(
        "/subject-attributes",
        json={"key": "manager", "name": "Manager", "value_type": "user"},
    )
    assert owner.status_code == 201, owner.text
    bad_code = client.put(
        f"/users/{ada.id}/subject-attributes",
        json={"values": {"regions": ["WEST"]}},
    )
    assert bad_code.status_code == 422
    assert bad_code.json()["code"] == "SUBJECT_ATTRIBUTE_INVALID"
    unknown_user = client.put(
        f"/users/{ada.id}/subject-attributes",
        json={"values": {"manager": ["user_missing"]}},
    )
    assert unknown_user.status_code == 422
    own = client.put(
        f"/users/{ada.id}/subject-attributes",
        json={"values": {"regions": ["EAST"], "manager": [ada.id]}},
    )
    assert own.status_code == 200, own.text
    assert own.json()["values"]["regions"] == ["EAST"]
    assert own.json()["values"]["manager"] == [ada.id]
    south = client.put(
        f"/user-groups/{group['id']}/subject-attributes",
        json={"values": {"regions": ["SOUTH"]}},
    )
    assert south.status_code == 422
    grouped = client.put(
        f"/user-groups/{group['id']}/subject-attributes",
        json={"values": {"regions": ["NORTH"]}},
    )
    assert grouped.status_code == 200, grouped.text

    effective = client.get(f"/users/{ada.id}/subject-attributes")
    assert effective.status_code == 200, effective.text
    assert effective.json()["effective"]["regions"] == ["EAST", "NORTH"]
    assert effective.json()["effective"]["manager"] == [ada.id]
    # A previously stored code stays valid after it is deactivated.
    get_dictionary_store().modify(
        "dct_regions",
        lambda current: DictionaryRecord(
            id=current.id,
            name=current.name,
            display_name=current.display_name,
            description=current.description,
            revision=current.revision,
            deprecated_at=current.deprecated_at,
            entries=tuple(
                DictionaryEntryRecord(
                    code=entry.code,
                    label=entry.label,
                    active=entry.code != "EAST",
                    position=entry.position,
                )
                for entry in current.entries
            ),
            created_at=current.created_at,
            updated_at=current.updated_at,
        ),
    )
    kept = client.put(
        f"/users/{ada.id}/subject-attributes",
        json={"values": {"regions": ["EAST"], "manager": [ada.id]}},
    )
    assert kept.status_code == 200, kept.text
    not_kept = client.put(
        f"/user-groups/{group['id']}/subject-attributes",
        json={"values": {"regions": ["EAST"]}},
    )
    assert not_kept.status_code == 422
    assert user_group_ids(ada.id) == (group["id"],)
    assert effective_subject_values(ada.id)["regions"] == ("EAST", "NORTH")
    assert existing_user_ids([ada.id, "user_missing"]) == frozenset({ada.id})
    assert existing_group_ids([group["id"], "grp_missing"]) == frozenset({group["id"]})

    narrowed = client.patch(
        f"/subject-attributes/{owner.json()['subject_attribute']['id']}",
        json={"multi_value": False},
    )
    assert narrowed.status_code == 200
    back = client.patch(
        f"/subject-attributes/{definition.json()['subject_attribute']['id']}",
        json={"multi_value": False},
    )
    assert back.status_code == 422
    assert back.json()["code"] == "SUBJECT_ATTRIBUTE_INVALID"

    replaced = client.put(
        f"/users/{ada.id}/groups", json={"group_ids": []}
    )
    assert replaced.status_code == 200
    assert replaced.json()["groups"] == []
    after = client.get(f"/users/{ada.id}/subject-attributes")
    assert after.json()["effective"]["regions"] == ["EAST"]
    assert "NORTH" not in after.json()["effective"]["regions"]

    deleted = client.delete(f"/user-groups/{group['id']}")
    assert deleted.status_code == 204
    missing = client.get(f"/user-groups/{group['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "USER_GROUP_NOT_FOUND"
    events, _cursor = get_audit_store().list_events(resource_type="user_group")
    assert any(event.action == "create" for event in events)
    assert any(event.action == "delete" for event in events)


def test_subject_attribute_rejects_unknown_dictionary_and_extra_id(
    client: TestClient,
) -> None:
    _root(client)
    missing = client.post(
        "/subject-attributes",
        json={
            "key": "zones",
            "name": "Zones",
            "value_type": "dictionary",
            "dictionary_id": "dct_missing",
        },
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "SUBJECT_ATTRIBUTE_INVALID"
    extra = client.post(
        "/subject-attributes",
        json={
            "key": "title",
            "name": "Title",
            "value_type": "string",
            "dictionary_id": "dct_regions",
        },
    )
    assert extra.status_code == 422
    single = client.post(
        "/subject-attributes",
        json={"key": "title", "name": "Title", "value_type": "string"},
    )
    assert single.status_code == 201, single.text
    too_many = client.put(
        f"/users/{_user_id(client, 'root')}/subject-attributes",
        json={"values": {"title": ["a", "b"]}},
    )
    assert too_many.status_code == 422
    unknown_key = client.put(
        f"/users/{_user_id(client, 'root')}/subject-attributes",
        json={"values": {"nope": ["a"]}},
    )
    assert unknown_key.status_code == 422
    assert unknown_key.json()["code"] == "SUBJECT_ATTRIBUTE_INVALID"


def _user_id(client: TestClient, account: str) -> str:
    page = client.get("/users?limit=200")
    assert page.status_code == 200, page.text
    for item in page.json()["items"]:
        if item["account"] == account:
            return item["id"]
    raise AssertionError(account)
