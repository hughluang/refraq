"""Tag vocabulary HTTP tests against the memory store."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.core.time import FixedClock, set_clock  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.store import _is_name_dup, reset_tag_store  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

_TAG_ID = re.compile(r"^tag_[0-9a-f]{12}$")


@pytest.fixture(autouse=True)
def _reset_tags() -> None:
    reset_tag_store()
    yield
    reset_tag_store()


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


def _open_client(account: str, password: str, permissions: list[str] | None) -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    if permissions is None:
        role = roles.get_by_key("super_admin")
        assert role is not None
    else:
        role = create_role(
            roles,
            key=account,
            name=account,
            permissions=permissions,
        )
    get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password(password),
        role_id=role.id,
        status="active",
    )
    client = TestClient(app)
    client.__enter__()
    _login(client, account, password)
    return client


@pytest.fixture()
def client() -> TestClient:
    test_client = _open_client("admin", "secret", None)
    try:
        yield test_client
    finally:
        test_client.__exit__(None, None, None)


def _events(client: TestClient, action: str | None = None) -> list[dict]:
    params: dict[str, str] = {"resource_type": "tag"}
    if action is not None:
        params["action"] = action
    response = client.get("/audit/events", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_create_stores_precis_display_name(client: TestClient) -> None:
    created = client.post("/tags", json={"name": "ＦＩＮＡＮＣＥ"})
    assert created.status_code == 201, created.text
    tag = created.json()["tag"]
    assert _TAG_ID.match(tag["id"])
    assert tag["name"] == "FINANCE"
    assert tag["description"] is None
    assert tag["entity_count"] == 0
    assert tag["channel_count"] == 0
    assert tag["created_at"] == tag["updated_at"]
    events = _events(client, "create")
    assert len(events) == 1
    assert events[0]["resource_type"] == "tag"
    assert events[0]["resource_id"] == tag["id"]
    assert events[0]["action"] == "create"
    assert events[0]["result"] == "success"


def test_same_comparison_form_conflicts_and_keeps_stored_spelling(
    client: TestClient,
) -> None:
    first = client.post("/tags", json={"name": "FINANCE"})
    assert first.status_code == 201, first.text
    tag_id = first.json()["tag"]["id"]
    for spelling in ("finance", "ＦＩＮＡＮＣＥ", "ｆｉｎａｎｃｅ"):
        again = client.post("/tags", json={"name": spelling})
        assert_problem(again, status=409, code="TAG_NAME_CONFLICT")
    stored = client.get(f"/tags/{tag_id}")
    assert stored.status_code == 200, stored.text
    assert stored.json()["tag"]["name"] == "FINANCE"
    assert len(_events(client, "create")) == 1

    renamed = client.patch(f"/tags/{tag_id}", json={"name": "finance"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["tag"]["name"] == "finance"
    loser = client.post("/tags", json={"name": "FINANCE"})
    assert_problem(loser, status=409, code="TAG_NAME_CONFLICT")
    assert client.get(f"/tags/{tag_id}").json()["tag"]["name"] == "finance"


def test_spaced_spellings_of_one_form_conflict(client: TestClient) -> None:
    first = client.post("/tags", json={"name": "finance  team"})
    assert first.status_code == 201, first.text
    assert first.json()["tag"]["name"] == "finance team"
    again = client.post("/tags", json={"name": "Finance Team"})
    assert_problem(again, status=409, code="TAG_NAME_CONFLICT")
    assert client.get(f"/tags/{first.json()['tag']['id']}").json()["tag"]["name"] == (
        "finance team"
    )


def test_profile_keeps_strasse_and_strasse_uppercase_distinct(
    client: TestClient,
) -> None:
    lower = client.post("/tags", json={"name": "Straße"})
    upper = client.post("/tags", json={"name": "STRASSE"})
    assert lower.status_code == 201, lower.text
    assert upper.status_code == 201, upper.text
    assert lower.json()["tag"]["name"] == "Straße"
    assert upper.json()["tag"]["name"] == "STRASSE"
    assert lower.json()["tag"]["id"] != upper.json()["tag"]["id"]


def test_accepted_names_store_the_preserved_spelling(client: TestClient) -> None:
    samples = {
        "\u8d22\u52a1": "\u8d22\u52a1",
        "\u8d22\u52a1-A 1": "\u8d22\u52a1-A 1",
        "foo-bar": "foo-bar",
        "foo bar": "foo bar",
        "ok😀": "ok😀",
        "  spaced  ": "spaced",
    }
    for raw, stored in samples.items():
        created = client.post("/tags", json={"name": raw})
        assert created.status_code == 201, created.text
        assert created.json()["tag"]["name"] == stored


def test_invalid_names_create_nothing(client: TestClient) -> None:
    rejected = [
        "",
        "   ",
        "a\nb",
        "❤️",
        "a" * 65,
        "a" * 257,
    ]
    for raw in rejected:
        response = client.post("/tags", json={"name": raw, "description": "kept out"})
        assert_problem(response, status=422, code="TAG_NAME_INVALID")
    listed = client.get("/tags")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 0
    assert _events(client, "create") == []


def test_unknown_field_is_rejected(client: TestClient) -> None:
    response = client.post("/tags", json={"name": "Ok", "color": "red"})
    assert_problem(response, status=422, code="REQUEST_INVALID")
    assert client.get("/tags").json()["total"] == 0


def test_description_trims_clears_and_rejects(client: TestClient) -> None:
    clock = FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc))
    set_clock(clock)
    created = client.post(
        "/tags", json={"name": "Ledger", "description": "  month end  "}
    )
    assert created.status_code == 201, created.text
    tag_id = created.json()["tag"]["id"]
    assert created.json()["tag"]["description"] == "month end"
    other = client.post("/tags", json={"name": "Other", "description": "month end"})
    assert other.status_code == 201, other.text
    assert other.json()["tag"]["description"] == "month end"

    clock.advance(timedelta(seconds=5))
    cleared = client.patch(f"/tags/{tag_id}", json={"description": "   "})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["tag"]["description"] is None
    assert cleared.json()["tag"]["updated_at"] != created.json()["tag"]["updated_at"]
    assert cleared.json()["tag"]["name"] == "Ledger"

    clock.advance(timedelta(seconds=5))
    nulled = client.patch(f"/tags/{tag_id}", json={"description": None})
    assert nulled.status_code == 200, nulled.text
    assert nulled.json()["tag"]["description"] is None
    assert nulled.json()["tag"]["updated_at"] == cleared.json()["tag"]["updated_at"]
    assert _events(client, "update")
    before = len(_events(client))
    clock.advance(timedelta(seconds=5))
    noop = client.patch(f"/tags/{tag_id}", json={})
    assert noop.status_code == 200, noop.text
    assert noop.json()["tag"]["updated_at"] == cleared.json()["tag"]["updated_at"]
    assert len(_events(client)) == before

    for raw in ("a" * 201, "a" * 257, "line\nbreak"):
        rejected = client.patch(f"/tags/{tag_id}", json={"description": raw})
        assert_problem(rejected, status=422, code="TAG_DESCRIPTION_INVALID")
    assert client.get(f"/tags/{tag_id}").json()["tag"]["description"] is None


def test_list_is_newest_first_and_search_is_a_literal_substring(
    client: TestClient,
) -> None:
    clock = FixedClock(datetime(2026, 3, 1, tzinfo=timezone.utc))
    set_clock(clock)
    first = client.post("/tags", json={"name": "100%"})
    clock.advance(timedelta(seconds=1))
    second = client.post("/tags", json={"name": "a_b"})
    clock.advance(timedelta(seconds=1))
    third = client.post("/tags", json={"name": "Finance"})
    assert first.status_code == second.status_code == third.status_code == 201

    page = client.get("/tags")
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] == 3
    assert [item["name"] for item in body["items"]] == ["Finance", "a_b", "100%"]
    assert "entity_count" not in body["items"][0]
    assert "channel_count" not in body["items"][0]
    keys = [(item["created_at"], item["id"]) for item in body["items"]]
    assert keys == sorted(keys, reverse=True)

    blank = client.get("/tags", params={"q": "   "})
    assert [item["id"] for item in blank.json()["items"]] == [
        item["id"] for item in body["items"]
    ]
    found = client.get("/tags", params={"q": "fin"})
    assert [item["name"] for item in found.json()["items"]] == ["Finance"]
    percent = client.get("/tags", params={"q": "%"})
    assert [item["name"] for item in percent.json()["items"]] == ["100%"]
    underscore = client.get("/tags", params={"q": "_"})
    assert [item["name"] for item in underscore.json()["items"]] == ["a_b"]
    not_wildcard = client.get("/tags", params={"q": "100X"})
    assert not_wildcard.json()["items"] == []

    capped = client.get("/tags", params={"limit": 200})
    assert capped.json()["limit"] == 200
    too_big = client.get("/tags", params={"limit": 201})
    assert_problem(too_big, status=422, code="REQUEST_INVALID")
    middle = client.get("/tags", params={"limit": 1, "offset": 1})
    assert middle.json()["items"][0]["name"] == "a_b"
    assert middle.json()["total"] == 3


def test_detail_counts_are_zero_and_unused_delete_returns_204(
    client: TestClient,
) -> None:
    created = client.post("/tags", json={"name": "Spare"})
    tag_id = created.json()["tag"]["id"]
    detail = client.get(f"/tags/{tag_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["tag"]["entity_count"] == 0
    assert detail.json()["tag"]["channel_count"] == 0
    missing = client.get("/tags/tag_doesnotexist")
    assert_problem(missing, status=404, code="TAG_NOT_FOUND")

    deleted = client.delete(f"/tags/{tag_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert_problem(client.get(f"/tags/{tag_id}"), status=404, code="TAG_NOT_FOUND")
    assert_problem(
        client.delete(f"/tags/{tag_id}"), status=404, code="TAG_NOT_FOUND"
    )
    assert client.get("/tags").json()["total"] == 0
    deleted_events = _events(client, "delete")
    assert len(deleted_events) == 1
    assert deleted_events[0]["result"] == "success"
    assert deleted_events[0]["resource_id"] == tag_id


def test_rename_and_description_edit_write_one_audit_each(client: TestClient) -> None:
    created = client.post("/tags", json={"name": "Ledger", "description": "old"})
    tag_id = created.json()["tag"]["id"]
    renamed = client.patch(f"/tags/{tag_id}", json={"name": "Books"})
    assert renamed.status_code == 200, renamed.text
    described = client.patch(f"/tags/{tag_id}", json={"description": "year"})
    assert described.status_code == 200, described.text
    updates = _events(client, "update")
    assert len(updates) == 2
    assert {item["action"] for item in updates} == {"update"}
    assert {item["result"] for item in updates} == {"success"}
    same = client.patch(f"/tags/{tag_id}", json={"name": "Books", "description": "year"})
    assert same.status_code == 200, same.text
    assert len(_events(client, "update")) == 2


def test_overlapping_creates_of_one_name_yield_one_tag(client: TestClient) -> None:
    spellings = ["FINANCE", "finance", "ＦＩＮＡＮＣＥ", "ｆｉｎａｎｃｅ"] * 2

    def post(name: str) -> int:
        with TestClient(app) as local:
            _login(local, "admin", "secret")
            return local.post("/tags", json={"name": name}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(post, spellings))
    assert 500 not in codes
    assert codes.count(201) == 1
    assert codes.count(409) == len(spellings) - 1
    listed = client.get("/tags", params={"q": "finance"})
    assert listed.json()["total"] == 1


def test_list_permission_is_tag_or_entity_or_channel_read(client: TestClient) -> None:
    created = client.post("/tags", json={"name": "Shared"})
    tag_id = created.json()["tag"]["id"]
    checks = [
        (["console:access", "entity:read"], 200),
        (["console:access", "channel:read"], 200),
        (["console:access", "tag:read"], 200),
        (["console:access", "dashboard:read"], 403),
    ]
    for index, (permissions, status_code) in enumerate(checks):
        reader = _open_client(f"reader{index}", "secret", permissions)
        try:
            listed = reader.get("/tags")
            assert listed.status_code == status_code, listed.text
            if status_code == 403:
                assert listed.json()["code"] == "AUTH_FORBIDDEN"
        finally:
            reader.__exit__(None, None, None)
    writer = _open_client("writer", "secret", ["console:access", "tag:write"])
    try:
        assert writer.get("/tags").status_code == 403
        assert writer.get(f"/tags/{tag_id}").status_code == 403
        made = writer.post("/tags", json={"name": "Writer"})
        assert made.status_code == 201, made.text
    finally:
        writer.__exit__(None, None, None)
    reader = _open_client("entityonly", "secret", ["console:access", "entity:read"])
    try:
        assert reader.get("/tags").status_code == 200
        denied = reader.get(f"/tags/{tag_id}")
        assert_problem(denied, status=403, code="AUTH_FORBIDDEN")
        denied_write = reader.post("/tags", json={"name": "Nope"})
        assert_problem(denied_write, status=403, code="AUTH_FORBIDDEN")
    finally:
        reader.__exit__(None, None, None)
    assert client.get("/tags").json()["total"] == 2


def test_catalog_grants_super_admin_and_not_operator_or_custom_roles(
    client: TestClient,
) -> None:
    catalog = {
        item["key"]: item["description"]
        for item in client.get("/permissions").json()["items"]
    }
    assert catalog["tag:read"] == "List and view Tags"
    assert catalog["tag:write"] == "Create, rename, describe, and delete Tags"
    roles = {
        item["key"]: item["permissions"] for item in client.get("/roles").json()["items"]
    }
    assert "tag:read" in roles["super_admin"]
    assert "tag:write" in roles["super_admin"]
    assert roles["operator"] == ["console:access", "dashboard:read"]
    created = client.post(
        "/roles",
        json={
            "key": "catalog_only",
            "name": "Catalog only",
            "permissions": ["console:access", "metadata:read"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"]["permissions"] == [
        "console:access",
        "metadata:read",
    ]


def test_name_conflict_is_only_the_name_key_unique_violation() -> None:
    def integrity(sqlstate: str, constraint: str | None) -> IntegrityError:
        orig = SimpleNamespace(
            sqlstate=sqlstate,
            diag=SimpleNamespace(constraint_name=constraint),
        )
        return IntegrityError("insert", {}, orig)

    assert _is_name_dup(integrity("23505", "uq_tags_name_key"))
    assert not _is_name_dup(integrity("23505", "tags_pkey"))
    assert not _is_name_dup(integrity("23505", None))
    assert not _is_name_dup(integrity("23502", "uq_tags_name_key"))
