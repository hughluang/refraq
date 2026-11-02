"""Source Membership HTTP: management permission, audit, and effective access."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.roles import seed_roles
from backend.admin.security import hash_password
from backend.admin.user_store import UserRecord, get_user_store
from backend.core.time import utc_now
from backend.main import app
from backend.metadata.source_access import reset_source_access_store
from backend.metadata.sources.store import SourceRecord, get_source_store, new_source_id

_ANALYST_PERMISSIONS = [
    "console:access",
    "sources:read",
    "sources:write",
    "metadata:read",
    "metadata:write",
    "catalog:sample",
    "query:run",
    "jobs:run",
]


@dataclass
class World:
    client: TestClient
    admin: UserRecord
    manager: UserRecord
    ada: UserRecord
    ben: UserRecord
    cy: UserRecord
    dee: UserRecord
    reader: UserRecord


@pytest.fixture
def world() -> Iterator[World]:
    reset_source_access_store()
    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    roles.insert(
        RoleRecord(
            id="role_access",
            key="access_manager",
            name="Access manager",
            permissions=["console:access", "sources:access_manage"],
        )
    )
    roles.insert(
        RoleRecord(
            id="role_analyst",
            key="analyst",
            name="Analyst",
            permissions=list(_ANALYST_PERMISSIONS),
        )
    )
    roles.insert(
        RoleRecord(
            id="role_reader",
            key="directory_reader",
            name="Directory reader",
            permissions=["console:access", "users:read"],
        )
    )
    users = get_user_store()

    def make(account: str, display_name: str, role_id: str) -> UserRecord:
        return users.create_user(
            account=account,
            display_name=display_name,
            password_hash=hash_password("secret"),
            role_id=role_id,
            status="active",
        )

    built = World(
        client=None,  # type: ignore[arg-type]
        admin=make("admin", "Admin", admin_role.id),
        manager=make("manager", "Manager", "role_access"),
        ada=make("ada", "Ada", "role_analyst"),
        ben=make("ben", "Ben", "role_analyst"),
        cy=make("cy", "Cy", "role_analyst"),
        dee=make("dee", "Dee", "role_analyst"),
        reader=make("reader", "Reader", "role_reader"),
    )
    with TestClient(app) as test_client:
        built.client = test_client
        yield built
    reset_source_access_store()


def _login(client: TestClient, account: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": "secret"}
    )
    assert response.status_code == 200, response.text


def _source(key: str, name: str) -> str:
    now = utc_now()
    record = get_source_store().create_source(
        SourceRecord(
            id=new_source_id(),
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=name,
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    return record.id


def _membership_events(client: TestClient) -> list[dict]:
    response = client.get(
        "/audit/events",
        params={"resource_type": "source_membership", "limit": 200},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _subject(user_id: str, level: str) -> dict[str, object]:
    return {"subject": {"type": "user", "id": user_id}, "level": level}


def test_membership_routes_require_a_session(world: World) -> None:
    client = world.client
    listing = client.get("/sources/src_missing/memberships")
    assert listing.status_code == 401
    assert listing.json()["code"] == "AUTH_UNAUTHENTICATED"
    every = client.get("/source-memberships")
    assert every.status_code == 401
    assert every.json()["code"] == "AUTH_UNAUTHENTICATED"
    read = client.get("/users/user_missing/source-access")
    assert read.status_code == 401
    assert read.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_source_list_follows_maintainer_or_access_manage(world: World) -> None:
    source_id = _source("billing", "Billing")
    other_id = _source("ledger", "Ledger")
    client = world.client
    _login(client, "manager")
    for account, level in (
        ("ada", "maintainer"),
        ("ben", "steward"),
        ("cy", "viewer"),
    ):
        user = getattr(world, account)
        created = client.post(
            f"/sources/{source_id}/memberships",
            json=_subject(user.id, level),
        )
        assert created.status_code == 201, created.text

    _login(client, "ada")
    listed = client.get(f"/sources/{source_id}/memberships")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert {item["subject"]["id"] for item in items} == {
        world.ada.id,
        world.ben.id,
        world.cy.id,
    }
    ada_row = next(item for item in items if item["subject"]["id"] == world.ada.id)
    assert ada_row["subject"]["display_name"] == "Ada"
    assert ada_row["subject"]["missing"] is False
    assert ada_row["level"] == "maintainer"
    assert ada_row["target"] == source_id
    ben_id = next(item["id"] for item in items if item["subject"]["id"] == world.ben.id)
    refused_create = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.dee.id, "viewer"),
    )
    assert refused_create.status_code == 403
    assert refused_create.json()["code"] == "AUTH_FORBIDDEN"
    refused_change = client.patch(
        f"/sources/{source_id}/memberships/{ben_id}",
        json={"level": "maintainer"},
    )
    assert refused_change.status_code == 403
    assert refused_change.json()["code"] == "AUTH_FORBIDDEN"
    refused_delete = client.delete(f"/sources/{source_id}/memberships/{ben_id}")
    assert refused_delete.status_code == 403
    assert refused_delete.json()["code"] == "AUTH_FORBIDDEN"
    again = client.get(f"/sources/{source_id}/memberships")
    assert len(again.json()["items"]) == 3
    other = client.get(f"/sources/{other_id}/memberships")
    assert other.status_code == 404
    assert other.json()["code"] == "SOURCE_NOT_FOUND"

    _login(client, "ben")
    steward = client.get(f"/sources/{source_id}/memberships")
    assert steward.status_code == 403
    assert steward.json()["code"] == "AUTH_FORBIDDEN"
    _login(client, "cy")
    viewer = client.get(f"/sources/{source_id}/memberships")
    assert viewer.status_code == 403
    assert viewer.json()["code"] == "AUTH_FORBIDDEN"

    _login(client, "dee")
    absent = client.get(f"/sources/{source_id}/memberships")
    assert absent.status_code == 404
    assert absent.json()["code"] == "SOURCE_NOT_FOUND"
    unknown = client.get("/sources/src_missing/memberships")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "SOURCE_NOT_FOUND"

    _login(client, "manager")
    managed = client.get(f"/sources/{source_id}/memberships")
    assert managed.status_code == 200
    assert len(managed.json()["items"]) == 3
    managed_other = client.get(f"/sources/{other_id}/memberships")
    assert managed_other.status_code == 200
    assert managed_other.json()["items"] == []
    missing = client.get("/sources/src_missing/memberships")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SOURCE_NOT_FOUND"

    _login(client, "admin")
    events = _membership_events(client)
    assert len(events) == 3
    assert {item["action"] for item in events} == {"source_membership.create"}


def test_source_membership_change_and_delete_write_audit(world: World) -> None:
    source_id = _source("billing", "Billing warehouse")
    other_id = _source("ledger", "Ledger")
    client = world.client
    _login(client, "manager")
    created = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.ada.id, "viewer"),
    )
    assert created.status_code == 201, created.text
    membership = created.json()["membership"]
    membership_id = membership["id"]
    assert set(membership) == {
        "id",
        "subject",
        "target",
        "level",
        "created_at",
        "updated_at",
    }
    assert set(membership["subject"]) == {"type", "id", "display_name", "missing"}
    assert membership["created_at"].endswith("Z")
    assert membership["subject"] == {
        "type": "user",
        "id": world.ada.id,
        "display_name": "Ada",
        "missing": False,
    }

    extra = client.patch(
        f"/sources/{source_id}/memberships/{membership_id}",
        json={"level": "steward", "role": "maintainer"},
    )
    assert extra.status_code == 422
    assert extra.json()["code"] == "REQUEST_INVALID"
    changed = client.patch(
        f"/sources/{source_id}/memberships/{membership_id}",
        json={"level": "steward"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["membership"]["level"] == "steward"

    crossed = client.patch(
        f"/sources/{other_id}/memberships/{membership_id}",
        json={"level": "maintainer"},
    )
    assert crossed.status_code == 404
    assert crossed.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"
    every_patch = client.patch(
        f"/source-memberships/{membership_id}",
        json={"level": "maintainer"},
    )
    assert every_patch.status_code == 404
    assert every_patch.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"
    listed = client.get(f"/sources/{source_id}/memberships")
    assert listed.json()["items"][0]["level"] == "steward"

    removed = client.delete(f"/sources/{source_id}/memberships/{membership_id}")
    assert removed.status_code == 204
    assert removed.content == b""
    assert client.get(f"/sources/{source_id}/memberships").json()["items"] == []
    missing = client.delete(f"/sources/{source_id}/memberships/{membership_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"
    missing_patch = client.patch(
        f"/sources/{source_id}/memberships/{membership_id}",
        json={"level": "viewer"},
    )
    assert missing_patch.status_code == 404
    assert missing_patch.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"

    _login(client, "admin")
    events = _membership_events(client)
    assert len(events) == 3
    by_action = {item["action"]: item for item in events}
    assert by_action["source_membership.create"]["resource_type"] == "source_membership"
    assert by_action["source_membership.create"]["resource_id"] == membership_id
    assert by_action["source_membership.create"]["result"] == "success"
    assert by_action["source_membership.create"]["actor_user_id"] == world.manager.id
    assert by_action["source_membership.create"]["detail"] == {
        "subject": {"type": "user", "id": world.ada.id},
        "target": source_id,
        "old_level": None,
        "new_level": "viewer",
    }
    assert by_action["source_membership.update"]["detail"] == {
        "subject": {"type": "user", "id": world.ada.id},
        "target": source_id,
        "old_level": "viewer",
        "new_level": "steward",
    }
    assert by_action["source_membership.delete"]["detail"] == {
        "subject": {"type": "user", "id": world.ada.id},
        "target": source_id,
        "old_level": "steward",
        "new_level": None,
    }


def test_every_source_memberships_are_a_separate_collection(world: World) -> None:
    source_id = _source("billing", "Billing")
    client = world.client
    get_role_store().insert(
        RoleRecord(
            id="role_warehouse",
            key="warehouse",
            name="Warehouse",
            permissions=["console:access"],
        )
    )
    _login(client, "manager")
    source_row = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.ada.id, "viewer"),
    )
    assert source_row.status_code == 201, source_row.text
    every = client.post(
        "/source-memberships",
        json={"subject": {"type": "role", "id": "role_warehouse"}, "level": "viewer"},
    )
    assert every.status_code == 201, every.text
    membership = every.json()["membership"]
    assert membership["target"] == "*"
    assert membership["subject"] == {
        "type": "role",
        "id": "role_warehouse",
        "display_name": "Warehouse",
        "missing": False,
    }
    source_items = client.get(f"/sources/{source_id}/memberships").json()["items"]
    every_items = client.get("/source-memberships").json()["items"]
    assert [item["id"] for item in source_items] == [
        source_row.json()["membership"]["id"]
    ]
    assert [item["id"] for item in every_items] == [membership["id"]]

    _login(client, "ada")
    denied_list = client.get("/source-memberships")
    assert denied_list.status_code == 403
    assert denied_list.json()["code"] == "AUTH_FORBIDDEN"
    denied_create = client.post(
        "/source-memberships",
        json=_subject(world.ben.id, "viewer"),
    )
    assert denied_create.status_code == 403
    denied_change = client.patch(
        f"/source-memberships/{membership['id']}",
        json={"level": "steward"},
    )
    assert denied_change.status_code == 403
    denied_delete = client.delete(f"/source-memberships/{membership['id']}")
    assert denied_delete.status_code == 403

    _login(client, "manager")
    changed = client.patch(
        f"/source-memberships/{membership['id']}",
        json={"level": "maintainer"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["membership"]["level"] == "maintainer"
    missed = client.patch(
        f"/sources/{source_id}/memberships/{membership['id']}",
        json={"level": "viewer"},
    )
    assert missed.status_code == 404
    assert missed.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"
    removed = client.delete(f"/source-memberships/{membership['id']}")
    assert removed.status_code == 204
    assert client.get("/source-memberships").json()["items"] == []
    gone = client.delete(f"/source-memberships/{membership['id']}")
    assert gone.status_code == 404
    assert gone.json()["code"] == "SOURCE_MEMBERSHIP_NOT_FOUND"

    _login(client, "admin")
    events = [
        item
        for item in _membership_events(client)
        if item["resource_id"] == membership["id"]
    ]
    by_action = {item["action"]: item for item in events}
    assert set(by_action) == {
        "source_membership.create",
        "source_membership.update",
        "source_membership.delete",
    }
    assert by_action["source_membership.create"]["detail"] == {
        "subject": {"type": "role", "id": "role_warehouse"},
        "target": "*",
        "old_level": None,
        "new_level": "viewer",
    }
    assert by_action["source_membership.update"]["detail"]["old_level"] == "viewer"
    assert by_action["source_membership.update"]["detail"]["new_level"] == "maintainer"
    assert by_action["source_membership.update"]["detail"]["target"] == "*"
    assert by_action["source_membership.delete"]["detail"]["old_level"] == "maintainer"
    assert by_action["source_membership.delete"]["detail"]["new_level"] is None


def test_rejected_membership_writes_leave_no_audit(world: World) -> None:
    source_id = _source("billing", "Billing")
    client = world.client
    _login(client, "manager")
    created = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.ada.id, "viewer"),
    )
    assert created.status_code == 201, created.text
    membership_id = created.json()["membership"]["id"]
    _login(client, "admin")
    before = {item["id"] for item in _membership_events(client)}

    _login(client, "manager")
    duplicate = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.ada.id, "steward"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "SOURCE_MEMBERSHIP_DUPLICATE"
    unknown_subject = client.post(
        f"/sources/{source_id}/memberships",
        json={"subject": {"type": "user", "id": "user_missing"}, "level": "viewer"},
    )
    assert unknown_subject.status_code == 422
    assert unknown_subject.json()["code"] == "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"
    unknown_type = client.post(
        f"/sources/{source_id}/memberships",
        json={"subject": {"type": "team", "id": world.ada.id}, "level": "viewer"},
    )
    assert unknown_type.status_code == 422
    assert unknown_type.json()["code"] == "SOURCE_MEMBERSHIP_SUBJECT_UNKNOWN"
    unknown_level = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.ben.id, "owner"),
    )
    assert unknown_level.status_code == 422
    assert unknown_level.json()["code"] == "SOURCE_MEMBERSHIP_LEVEL_UNKNOWN"
    bad_change = client.patch(
        f"/sources/{source_id}/memberships/{membership_id}",
        json={"level": "owner"},
    )
    assert bad_change.status_code == 422
    assert bad_change.json()["code"] == "SOURCE_MEMBERSHIP_LEVEL_UNKNOWN"
    still = client.get(f"/sources/{source_id}/memberships")
    assert still.json()["items"][0]["level"] == "viewer"
    assert {item["subject"]["id"] for item in still.json()["items"]} == {world.ada.id}
    missing_source = client.post(
        "/sources/src_missing/memberships",
        json=_subject(world.ben.id, "viewer"),
    )
    assert missing_source.status_code == 404
    assert missing_source.json()["code"] == "SOURCE_NOT_FOUND"

    every_duplicate_setup = client.post(
        "/source-memberships",
        json=_subject(world.ben.id, "viewer"),
    )
    assert every_duplicate_setup.status_code == 201, every_duplicate_setup.text
    every_duplicate = client.post(
        "/source-memberships",
        json=_subject(world.ben.id, "maintainer"),
    )
    assert every_duplicate.status_code == 409
    assert every_duplicate.json()["code"] == "SOURCE_MEMBERSHIP_DUPLICATE"

    _login(client, "admin")
    events = _membership_events(client)
    new_events = [item for item in events if item["id"] not in before]
    assert len(new_events) == 1
    assert new_events[0]["action"] == "source_membership.create"
    assert new_events[0]["detail"]["target"] == "*"
    assert new_events[0]["detail"]["subject"]["id"] == world.ben.id


def test_missing_subject_is_listed_and_omitted_from_source_access(
    world: World,
) -> None:
    shared = _source("shared", "Shared")
    owned = _source("owned", "Owned")
    client = world.client
    _login(client, "admin")
    created = client.post(
        "/user-groups", json={"key": "east_sales", "name": "East sales"}
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group"]["id"]
    added = client.put(f"/user-groups/{group_id}/members/{world.ada.id}")
    assert added.status_code == 204, added.text

    _login(client, "manager")
    group_row = client.post(
        f"/sources/{shared}/memberships",
        json={"subject": {"type": "group", "id": group_id}, "level": "viewer"},
    )
    assert group_row.status_code == 201, group_row.text
    direct = client.post(
        f"/sources/{owned}/memberships",
        json=_subject(world.ada.id, "maintainer"),
    )
    assert direct.status_code == 201, direct.text
    also = client.post(
        f"/sources/{owned}/memberships",
        json={"subject": {"type": "group", "id": group_id}, "level": "viewer"},
    )
    assert also.status_code == 201, also.text

    _login(client, "reader")
    access = client.get(f"/users/{world.ada.id}/source-access")
    assert access.status_code == 200, access.text
    by_id = {item["source_id"]: item for item in access.json()["items"]}
    assert set(by_id) == {shared, owned}
    assert by_id[shared]["key"] == "shared"
    assert by_id[shared]["name"] == "Shared"
    assert by_id[shared]["level"] == "viewer"
    assert by_id[shared]["contributions"] == [
        {"kind": "group", "subject_name": "East sales"}
    ]
    assert by_id[owned]["key"] == "owned"
    assert by_id[owned]["name"] == "Owned"
    assert by_id[owned]["level"] == "maintainer"
    assert {
        (item["kind"], item["subject_name"]) for item in by_id[owned]["contributions"]
    } == {("direct", "Ada"), ("group", "East sales")}

    _login(client, "admin")
    removed = client.delete(f"/user-groups/{group_id}")
    assert removed.status_code == 204, removed.text

    _login(client, "manager")
    shared_items = client.get(f"/sources/{shared}/memberships").json()["items"]
    assert len(shared_items) == 1
    assert shared_items[0]["subject"]["type"] == "group"
    assert shared_items[0]["subject"]["id"] == group_id
    assert shared_items[0]["subject"]["missing"] is True
    assert shared_items[0]["subject"]["display_name"] is None
    owned_items = client.get(f"/sources/{owned}/memberships").json()["items"]
    owned_group = next(
        item for item in owned_items if item["subject"]["id"] == group_id
    )
    assert owned_group["subject"]["missing"] is True
    assert owned_group["subject"]["display_name"] is None

    _login(client, "reader")
    after = client.get(f"/users/{world.ada.id}/source-access")
    assert after.status_code == 200, after.text
    after_by_id = {item["source_id"]: item for item in after.json()["items"]}
    assert set(after_by_id) == {owned}
    assert after_by_id[owned]["level"] == "maintainer"
    assert after_by_id[owned]["contributions"] == [
        {"kind": "direct", "subject_name": "Ada"}
    ]


def test_user_source_access_reports_super_admin_without_a_membership(
    world: World,
) -> None:
    billing = _source("billing", "Billing warehouse")
    ledger = _source("ledger", "Ledger")
    client = world.client
    _login(client, "dee")
    denied = client.get(f"/users/{world.admin.id}/source-access")
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH_FORBIDDEN"

    _login(client, "reader")
    missing = client.get("/users/user_missing/source-access")
    assert missing.status_code == 404
    assert missing.json()["code"] == "USER_NOT_FOUND"
    empty = client.get(f"/users/{world.dee.id}/source-access")
    assert empty.status_code == 200
    assert empty.json() == {"items": []}
    found = client.get(f"/users/{world.admin.id}/source-access")
    assert found.status_code == 200, found.text
    by_id = {item["source_id"]: item for item in found.json()["items"]}
    assert set(by_id) == {billing, ledger}
    assert by_id[billing]["key"] == "billing"
    assert by_id[billing]["name"] == "Billing warehouse"
    assert by_id[ledger]["key"] == "ledger"
    assert by_id[ledger]["name"] == "Ledger"
    for item in by_id.values():
        assert set(item) == {"source_id", "key", "name", "level", "contributions"}
        assert item["level"] == "maintainer"
        assert item["contributions"] == [
            {"kind": "identity", "subject_name": "Super Admin"}
        ]

    _login(client, "manager")
    assert client.get(f"/sources/{billing}/memberships").json()["items"] == []
    assert client.get(f"/sources/{ledger}/memberships").json()["items"] == []
    assert client.get("/source-memberships").json()["items"] == []


def test_access_manage_cannot_read_catalog_query_or_decrypted_access(
    world: World,
) -> None:
    source_id = _source("billing", "Billing")
    client = world.client
    _login(client, "manager")
    created = client.post(
        f"/sources/{source_id}/memberships",
        json=_subject(world.dee.id, "viewer"),
    )
    assert created.status_code == 201, created.text

    catalog = client.get("/objects/obj_missing")
    assert catalog.status_code == 403
    assert catalog.json()["code"] == "AUTH_FORBIDDEN"
    query = client.post(f"/sources/{source_id}/query", json={"sql": "SELECT 1"})
    assert query.status_code == 403
    assert query.json()["code"] == "AUTH_FORBIDDEN"
    secret = client.get(f"/sources/{source_id}/access")
    assert secret.status_code == 403
    assert secret.json()["code"] == "AUTH_FORBIDDEN"
