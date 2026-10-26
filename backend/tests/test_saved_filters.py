"""Saved Filter HTTP tests against the memory store."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.tests.problem import assert_problem

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.saved_filter_store import reset_saved_filter_store  # noqa: E402

_FILTER_ID = re.compile(r"^sf_[0-9a-f]{12}$")

_ENTITY_QUERY = {
    "q": "ledger",
    "status": ["serving"],
    "tag_ids": ["tag_gone"],
}


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


def _open_client(
    account: str, password: str, permissions: list[str] | None
) -> TestClient:
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


def _audit_ids(client: TestClient) -> list[str]:
    found: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {"limit": "200"}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/audit/events", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        found.extend(item["id"] for item in body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            return found


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_saved_filters() -> None:
    reset_saved_filter_store()
    yield
    reset_saved_filter_store()


@pytest.fixture()
def client() -> TestClient:
    test_client = _open_client("admin", "secret", None)
    try:
        yield test_client
    finally:
        test_client.__exit__(None, None, None)


def test_create_stores_the_query_and_writes_no_audit(client: TestClient) -> None:
    before = _audit_ids(client)
    created = client.post(
        "/saved-filters",
        json={"list": "entities", "name": "Open books", "query": _ENTITY_QUERY},
    )
    assert created.status_code == 201, created.text
    body = created.json()["saved_filter"]
    assert _FILTER_ID.match(body["id"])
    assert body["list"] == "entities"
    assert body["name"] == "Open books"
    assert body["query"] == _ENTITY_QUERY
    assert "offset" not in body["query"]
    assert body["created_at"] == body["updated_at"]
    assert _audit_ids(client) == before


def test_another_users_id_is_not_found(client: TestClient) -> None:
    created = client.post(
        "/saved-filters",
        json={"list": "entities", "name": "Open books", "query": _ENTITY_QUERY},
    )
    assert created.status_code == 201, created.text
    filter_id = created.json()["saved_filter"]["id"]
    other = _open_client("other", "secret", ["console:access", "entity:read"])
    try:
        stolen = other.patch(
            f"/saved-filters/{filter_id}", json={"name": "Stolen"}
        )
        assert_problem(stolen, status=404, code="SAVED_FILTER_NOT_FOUND")
        removed = other.delete(f"/saved-filters/{filter_id}")
        assert_problem(removed, status=404, code="SAVED_FILTER_NOT_FOUND")
    finally:
        other.__exit__(None, None, None)
    absent = client.delete("/saved-filters/sf_000000000000")
    assert_problem(absent, status=404, code="SAVED_FILTER_NOT_FOUND")
    kept = client.get("/saved-filters", params={"list": "entities"})
    assert kept.status_code == 200, kept.text
    assert [item["id"] for item in kept.json()["items"]] == [filter_id]


def _entity_query(
    *,
    q: str = "",
    status: list[str] | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    return {
        "q": q,
        "status": ["not_serving", "serving"] if status is None else status,
        "tag_ids": [] if tag_ids is None else tag_ids,
    }


def _channel_query(
    *,
    q: str = "",
    active: bool | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    return {
        "q": q,
        "active": active,
        "tag_ids": [] if tag_ids is None else tag_ids,
    }


def _create(client: TestClient, *, name: str, list_name: str = "entities", query: dict | None = None):
    body = {
        "list": list_name,
        "name": name,
        "query": query if query is not None else _entity_query(),
    }
    if list_name == "channels" and query is None:
        body["query"] = _channel_query()
    return client.post("/saved-filters", json=body)


def test_name_uses_the_tag_rule_and_is_unique_per_user_and_list(
    client: TestClient,
) -> None:
    created = _create(client, name="ＦＩＮＡＮＣＥ")
    assert created.status_code == 201, created.text
    filter_id = created.json()["saved_filter"]["id"]
    assert created.json()["saved_filter"]["name"] == "FINANCE"
    conflict = _create(client, name="finance")
    assert_problem(conflict, status=409, code="SAVED_FILTER_NAME_CONFLICT")
    stored = client.get("/saved-filters", params={"list": "entities"})
    assert stored.json()["total"] == 1
    assert stored.json()["items"][0]["name"] == "FINANCE"

    renamed = client.patch(f"/saved-filters/{filter_id}", json={"name": "finance"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["saved_filter"]["name"] == "finance"
    again = _create(client, name="FINANCE")
    assert_problem(again, status=409, code="SAVED_FILTER_NAME_CONFLICT")

    other_list = _create(client, name="finance", list_name="channels")
    assert other_list.status_code == 201, other_list.text
    other_user = _open_client("namer", "secret", ["console:access", "entity:read"])
    try:
        theirs = _create(other_user, name="finance")
        assert theirs.status_code == 201, theirs.text
    finally:
        other_user.__exit__(None, None, None)

    for bad in ("", " ", "x" * 257):
        rejected = _create(client, name=bad, list_name="channels")
        assert_problem(rejected, status=422, code="SAVED_FILTER_NAME_INVALID")
    listed = client.get("/saved-filters", params={"list": "channels"})
    assert listed.json()["total"] == 1


def test_twenty_first_filter_is_rejected_and_a_race_cannot_leave_twenty_one(
    client: TestClient,
) -> None:
    ids: list[str] = []
    for index in range(20):
        created = _create(client, name=f"View {index}")
        assert created.status_code == 201, created.text
        ids.append(created.json()["saved_filter"]["id"])
    extra = _create(client, name="View 20")
    assert_problem(extra, status=422, code="SAVED_FILTER_LIMIT")
    listed = client.get("/saved-filters", params={"list": "entities"})
    assert listed.json()["total"] == 20
    updated = client.patch(
        f"/saved-filters/{ids[0]}",
        json={"query": _entity_query(q="kept")},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["saved_filter"]["query"]["q"] == "kept"
    channel = _create(client, name="View 0", list_name="channels")
    assert channel.status_code == 201, channel.text

    racer = _open_client("racer", "secret", ["console:access", "channel:read"])
    try:
        def post(index: int) -> int:
            with TestClient(app) as local:
                _login(local, "racer", "secret")
                response = local.post(
                    "/saved-filters",
                    json={
                        "list": "channels",
                        "name": f"Race {index}",
                        "query": _channel_query(),
                    },
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(post, range(21)))
        assert 500 not in codes
        assert codes.count(201) == 20
        assert codes.count(422) == 1
        raced = racer.get("/saved-filters", params={"list": "channels"})
        assert raced.json()["total"] == 20
    finally:
        racer.__exit__(None, None, None)


def test_list_is_the_callers_rows_ordered_by_comparison_form_then_id(
    client: TestClient,
) -> None:
    third = _create(client, name="zeta")
    first = _create(client, name="alpha")
    second = _create(client, name="mid")
    assert first.status_code == 201 and second.status_code == 201
    hidden = _open_client("hidden", "secret", ["console:access", "entity:read"])
    try:
        private = _create(hidden, name="alpha")
        assert private.status_code == 201, private.text
        theirs = hidden.get("/saved-filters", params={"list": "entities"})
        assert [item["id"] for item in theirs.json()["items"]] == [
            private.json()["saved_filter"]["id"]
        ]
    finally:
        hidden.__exit__(None, None, None)
    listed = client.get("/saved-filters", params={"list": "entities"})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["name"] for item in body["items"]] == ["alpha", "mid", "zeta"]
    assert [item["id"] for item in body["items"]] == [
        first.json()["saved_filter"]["id"],
        second.json()["saved_filter"]["id"],
        third.json()["saved_filter"]["id"],
    ]
    too_big = client.get("/saved-filters", params={"list": "entities", "limit": 51})
    assert_problem(too_big, status=422, code="REQUEST_INVALID")


def test_query_shape_is_stored_and_not_executed(client: TestClient) -> None:
    created = _create(
        client,
        name="Collapsed",
        query={
            "q": "ledger",
            "status": ["serving", "serving", "deprecated"],
            "tag_ids": ["tag_gone", "tag_gone", "tag_live"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["saved_filter"]["query"] == {
        "q": "ledger",
        "status": ["serving", "deprecated"],
        "tag_ids": ["tag_gone", "tag_live"],
    }
    empty = _create(
        client,
        name="Nothing selected",
        query={"q": "", "status": [], "tag_ids": []},
    )
    assert empty.status_code == 201, empty.text
    assert empty.json()["saved_filter"]["query"]["status"] == []
    channel = _create(
        client,
        name="Inactive",
        list_name="channels",
        query={"q": "", "active": None, "tag_ids": ["tag_gone"]},
    )
    assert channel.status_code == 201, channel.text
    assert channel.json()["saved_filter"]["query"] == {
        "q": "",
        "active": None,
        "tag_ids": ["tag_gone"],
    }
    assert "offset" not in channel.json()["saved_filter"]["query"]
    unknown = _create(
        client,
        name="Paged",
        query={**_entity_query(), "offset": 50},
    )
    assert_problem(unknown, status=422, code="REQUEST_INVALID")
    long_q = _create(client, name="Long", query=_entity_query(q="a" * 201))
    assert_problem(long_q, status=422, code="REQUEST_INVALID")
    long_id = _create(
        client,
        name="Long id",
        query=_entity_query(tag_ids=["t" * 33]),
    )
    assert_problem(long_id, status=422, code="REQUEST_INVALID")
    too_many = _create(
        client,
        name="Many",
        query=_entity_query(tag_ids=[f"tag_{index:02d}" for index in range(51)]),
    )
    assert_problem(too_many, status=422, code="REQUEST_INVALID")
    listed = client.get("/saved-filters", params={"list": "entities"})
    assert listed.json()["total"] == 2


def test_deleting_the_remembered_filter_clears_it_and_writes_no_audit(
    client: TestClient,
) -> None:
    before = _audit_ids(client)
    created = _create(client, name="Morning")
    filter_id = created.json()["saved_filter"]["id"]
    other = _create(client, name="Evening", list_name="channels")
    other_id = other.json()["saved_filter"]["id"]
    empty = client.get("/saved-filters/default", params={"list": "entities"})
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"list": "entities", "saved_filter_id": None}

    remembered = client.put(
        "/saved-filters/default",
        json={"list": "entities", "saved_filter_id": filter_id},
    )
    assert remembered.status_code == 200, remembered.text
    assert remembered.json()["saved_filter_id"] == filter_id
    crossed = client.put(
        "/saved-filters/default",
        json={"list": "entities", "saved_filter_id": other_id},
    )
    assert_problem(crossed, status=422, code="REQUEST_INVALID")
    still = client.get("/saved-filters/default", params={"list": "entities"})
    assert still.json()["saved_filter_id"] == filter_id

    stranger = _open_client("stranger", "secret", ["console:access", "entity:read"])
    try:
        stolen = stranger.put(
            "/saved-filters/default",
            json={"list": "entities", "saved_filter_id": filter_id},
        )
        assert_problem(stolen, status=404, code="SAVED_FILTER_NOT_FOUND")
    finally:
        stranger.__exit__(None, None, None)

    removed = client.delete(f"/saved-filters/{filter_id}")
    assert removed.status_code == 204, removed.text
    cleared = client.get("/saved-filters/default", params={"list": "entities"})
    assert cleared.json() == {"list": "entities", "saved_filter_id": None}
    gone = client.delete(f"/saved-filters/{filter_id}")
    assert_problem(gone, status=404, code="SAVED_FILTER_NOT_FOUND")
    assert _audit_ids(client) == before

    explicit = client.put(
        "/saved-filters/default",
        json={"list": "channels", "saved_filter_id": other_id},
    )
    assert explicit.status_code == 200, explicit.text
    blank = client.put(
        "/saved-filters/default",
        json={"list": "channels", "saved_filter_id": None},
    )
    assert blank.status_code == 200, blank.text
    assert blank.json()["saved_filter_id"] is None


def test_permission_is_the_list_read_and_not_write(client: TestClient) -> None:
    entity_reader = _open_client(
        "entityreader", "secret", ["console:access", "entity:read"]
    )
    channel_reader = _open_client(
        "channelreader", "secret", ["console:access", "channel:read"]
    )
    writer = _open_client(
        "entitywriter", "secret", ["console:access", "entity:write"]
    )
    try:
        made = _create(entity_reader, name="Mine")
        assert made.status_code == 201, made.text
        denied = _create(entity_reader, name="Channels", list_name="channels")
        assert_problem(denied, status=403, code="AUTH_FORBIDDEN")
        made_channel = _create(channel_reader, name="Mine", list_name="channels")
        assert made_channel.status_code == 201, made_channel.text
        denied_entity = _create(channel_reader, name="Entities")
        assert_problem(denied_entity, status=403, code="AUTH_FORBIDDEN")
        denied_write = _create(writer, name="Writer")
        assert_problem(denied_write, status=403, code="AUTH_FORBIDDEN")
    finally:
        entity_reader.__exit__(None, None, None)
        channel_reader.__exit__(None, None, None)
        writer.__exit__(None, None, None)


def test_patch_rejects_a_new_list_and_keeps_an_invalid_query(
    client: TestClient,
) -> None:
    created = _create(client, name="Stable", query=_entity_query(q="before"))
    filter_id = created.json()["saved_filter"]["id"]
    rejected = client.patch(
        f"/saved-filters/{filter_id}",
        json={"list": "channels"},
    )
    assert_problem(rejected, status=422, code="REQUEST_INVALID")
    bad_query = client.patch(
        f"/saved-filters/{filter_id}",
        json={"query": {"q": "after", "status": ["nope"], "tag_ids": []}},
    )
    assert_problem(bad_query, status=422, code="REQUEST_INVALID")
    stored = client.get("/saved-filters", params={"list": "entities"})
    assert stored.json()["items"][0]["list"] == "entities"
    assert stored.json()["items"][0]["query"]["q"] == "before"
    assert stored.json()["items"][0]["name"] == "Stable"
