"""Bulk Tag add and remove on Entity and Channel lists."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.store import reset_tag_store  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

SKU = {
    "name": "sku",
    "type": "string",
    "required": True,
    "unique": True,
    "indexed": False,
    "description": "SKU code",
    "config": {"max_length": 32},
}


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


def _create_entity(client: TestClient, **overrides: object) -> dict:
    body: dict = {
        "table_name": "material",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [SKU],
    }
    body.update(overrides)
    created = client.post("/entities", json=body)
    assert created.status_code == 201, created.text
    return created.json()["entity"]


def _create_channel(client: TestClient, **overrides: object) -> dict:
    body: dict = {"name": "Material master", "description": None}
    body.update(overrides)
    created = client.post("/channels", json=body)
    assert created.status_code == 201, created.text
    return created.json()["channel"]


def _tag(client: TestClient, name: str) -> str:
    created = client.post("/tags", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["tag"]["id"]


def _replace_entity(
    client: TestClient, entity_id: str, *, base_revision: int, tag_ids: list[str]
) -> None:
    replaced = client.put(
        f"/entities/{entity_id}/tags",
        json={"base_revision": base_revision, "tag_ids": tag_ids, "names": []},
    )
    assert replaced.status_code == 200, replaced.text


def _replace_channel(
    client: TestClient, channel_id: str, *, base_revision: int, tag_ids: list[str]
) -> None:
    replaced = client.put(
        f"/channels/{channel_id}/tags",
        json={"base_revision": base_revision, "tag_ids": tag_ids, "names": []},
    )
    assert replaced.status_code == 200, replaced.text


def _bulk(
    client: TestClient,
    resource: str,
    verb: str,
    subject_ids: list[str],
    tag_ids: list[str],
) -> object:
    key = "entity_ids" if resource == "entities" else "channel_ids"
    return client.post(
        f"/{resource}/tags/{verb}",
        json={key: subject_ids, "tag_ids": tag_ids},
    )


def _audit(action: str, resource_type: str) -> list:
    events, _cursor = get_audit_store().list_events(
        action=action, resource_type=resource_type, limit=200
    )
    return events


def _deprecate(client: TestClient, entity: dict) -> None:
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    deprecated = client.post(f"/entities/{entity['id']}/deprecate")
    assert deprecated.status_code == 200, deprecated.text


def _refs(kind: str, ids: list[str]) -> list[dict[str, str]]:
    return [{"kind": kind, "id": item} for item in ids]


def test_bulk_shape_errors_write_nothing(client: TestClient) -> None:
    entity = _create_entity(client)
    channel = _create_channel(client)
    tag_id = _tag(client, "Ledger")
    before_add_entity = _audit("tags.add", "entity")
    before_remove_entity = _audit("tags.remove", "entity")
    before_add_channel = _audit("tags.add", "channel")
    before_remove_channel = _audit("tags.remove", "channel")

    cases = (
        ("entities", entity["id"], []),
        ("entities", entity["id"], [f"tag_{index:03d}" for index in range(11)]),
        ("channels", channel["id"], []),
        ("channels", channel["id"], [f"tag_{index:03d}" for index in range(11)]),
    )
    for resource, subject_id, tag_ids in cases:
        for verb in ("add", "remove"):
            refused = _bulk(client, resource, verb, [subject_id], tag_ids)
            assert_problem(refused, status=422, code="REQUEST_INVALID")
            empty = _bulk(client, resource, verb, [], [tag_id])
            assert_problem(empty, status=422, code="REQUEST_INVALID")
        too_many = _bulk(
            client,
            resource,
            "add",
            [f"sub_{index:03d}" for index in range(201)],
            [tag_id],
        )
        assert_problem(too_many, status=422, code="REQUEST_INVALID")

    entity_detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert entity_detail["tags"] == []
    assert entity_detail["tag_revision"] == 1
    channel_detail = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert channel_detail["tags"] == []
    assert channel_detail["tag_revision"] == 1
    assert client.get("/tags").json()["total"] == 1
    assert _audit("tags.add", "entity") == before_add_entity
    assert _audit("tags.remove", "entity") == before_remove_entity
    assert _audit("tags.add", "channel") == before_add_channel
    assert _audit("tags.remove", "channel") == before_remove_channel


def test_duplicate_ids_collapse_before_the_limits(client: TestClient) -> None:
    entity = _create_entity(client)
    tag_id = _tag(client, "Ledger")
    added = _bulk(client, "entities", "add", [entity["id"]] * 201, [tag_id] * 11)
    assert added.status_code == 200, added.text
    subjects = added.json()["subjects"]
    assert [item["id"] for item in subjects] == [entity["id"]]
    assert subjects[0]["tag_revision"] == 2
    assert subjects[0]["tags"] == [{"id": tag_id, "name": "Ledger"}]
    assert len(_audit("tags.add", "entity")) == 1


def test_reader_is_forbidden_before_a_missing_id_is_resolved(client: TestClient) -> None:
    tag_id = _tag(client, "Ledger")
    entity_reader = _open_client("entity_reader", "secret", ["console:access", "entity:read"])
    channel_reader = _open_client(
        "channel_reader", "secret", ["console:access", "channel:read"]
    )
    try:
        for verb in ("add", "remove"):
            refused_entity = _bulk(
                entity_reader, "entities", verb, ["ent_missing"], [tag_id]
            )
            assert_problem(refused_entity, status=403, code="AUTH_FORBIDDEN")
            refused_channel = _bulk(
                channel_reader, "channels", verb, ["chn_missing"], [tag_id]
            )
            assert_problem(refused_channel, status=403, code="AUTH_FORBIDDEN")
    finally:
        entity_reader.__exit__(None, None, None)
        channel_reader.__exit__(None, None, None)
    assert _audit("tags.add", "entity") == []
    assert _audit("tags.add", "channel") == []
    assert client.get("/tags").json()["total"] == 1


def test_bulk_add_returns_every_subject_and_audits_only_changes(
    client: TestClient,
) -> None:
    held = _create_entity(client, table_name="held", name="Held")
    fresh = _create_entity(client, table_name="fresh", name="Fresh")
    alpha = _tag(client, "Alpha")
    beta = _tag(client, "beta")
    _replace_entity(client, held["id"], base_revision=1, tag_ids=[alpha])
    held_before = client.get(f"/entities/{held['id']}").json()["entity"]
    fresh_before = client.get(f"/entities/{fresh['id']}").json()["entity"]

    added = _bulk(
        client,
        "entities",
        "add",
        [held["id"], fresh["id"], held["id"]],
        [beta, alpha, beta],
    )
    assert added.status_code == 200, added.text
    subjects = added.json()["subjects"]
    assert [item["id"] for item in subjects] == [held["id"], fresh["id"]]
    assert subjects[0]["tags"] == [
        {"id": alpha, "name": "Alpha"},
        {"id": beta, "name": "beta"},
    ]
    assert subjects[0]["tag_revision"] == 3
    assert subjects[1]["tags"] == subjects[0]["tags"]
    assert subjects[1]["tag_revision"] == 2

    held_after = client.get(f"/entities/{held['id']}").json()["entity"]
    fresh_after = client.get(f"/entities/{fresh['id']}").json()["entity"]
    assert held_after["updated_at"] == held_before["updated_at"]
    assert fresh_after["updated_at"] == fresh_before["updated_at"]
    assert held_after["tags"] == subjects[0]["tags"]
    assert fresh_after["tag_revision"] == 2

    events = _audit("tags.add", "entity")
    assert {event.resource_id for event in events} == {held["id"], fresh["id"]}
    assert len(events) == 2
    by_id = {event.resource_id: event for event in events}
    assert by_id[held["id"]].action == "tags.add"
    assert by_id[held["id"]].detail["tag_ids"] == [alpha, beta]
    assert by_id[fresh["id"]].detail["tag_ids"] == [alpha, beta]

    again = _bulk(client, "entities", "add", [held["id"], fresh["id"]], [alpha, beta])
    assert again.status_code == 200, again.text
    assert [item["tag_revision"] for item in again.json()["subjects"]] == [3, 2]
    assert len(_audit("tags.add", "entity")) == 2


def test_bulk_add_that_exceeds_ten_writes_nothing_and_names_every_row(
    client: TestClient,
) -> None:
    full = _create_entity(client, table_name="full", name="Full")
    also = _create_entity(client, table_name="also_full", name="Also")
    room = _create_entity(client, table_name="room", name="Room")
    held = [_tag(client, f"held-{index}") for index in range(10)]
    extra = _tag(client, "extra")
    _replace_entity(client, full["id"], base_revision=1, tag_ids=held)
    _replace_entity(client, also["id"], base_revision=1, tag_ids=held)
    before = _audit("tags.add", "entity")

    refused = _bulk(
        client, "entities", "add", [room["id"], full["id"], also["id"]], [extra]
    )
    problem = assert_problem(refused, status=422, code="TAG_LIMIT_EXCEEDED")
    assert problem["subjects"] == _refs("entity", [full["id"], also["id"]])

    assert client.get(f"/entities/{room['id']}").json()["entity"]["tags"] == []
    assert client.get(f"/entities/{room['id']}").json()["entity"]["tag_revision"] == 1
    for entity_id in (full["id"], also["id"]):
        detail = client.get(f"/entities/{entity_id}").json()["entity"]
        assert detail["tag_revision"] == 2
        assert len(detail["tags"]) == 10
        assert extra not in {tag["id"] for tag in detail["tags"]}
    assert _audit("tags.add", "entity") == before


def test_bulk_add_does_not_count_a_held_tag_twice(client: TestClient) -> None:
    entity = _create_entity(client)
    held = [_tag(client, f"held-{index}") for index in range(10)]
    _replace_entity(client, entity["id"], base_revision=1, tag_ids=held)
    before = _audit("tags.add", "entity")

    added = _bulk(client, "entities", "add", [entity["id"]], [held[0], held[0]])
    assert added.status_code == 200, added.text
    assert added.json()["subjects"][0]["tag_revision"] == 2
    assert len(added.json()["subjects"][0]["tags"]) == 10
    assert _audit("tags.add", "entity") == before


def test_entity_bulk_errors_follow_precedence(client: TestClient) -> None:
    live = _create_entity(client, table_name="live", name="Live")
    retired = _create_entity(client, table_name="retired", name="Retired")
    _deprecate(client, retired)
    full = _create_entity(client, table_name="capped", name="Capped")
    held = [_tag(client, f"held-{index}") for index in range(10)]
    known = _tag(client, "known")
    _replace_entity(client, full["id"], base_revision=1, tag_ids=held)
    before = _audit("tags.add", "entity")

    missing = _bulk(
        client,
        "entities",
        "add",
        ["ent_missing", retired["id"], "ent_missing", live["id"]],
        ["tag_missing", known],
    )
    problem = assert_problem(missing, status=404, code="ENTITY_NOT_FOUND")
    assert problem["subjects"] == _refs("entity", ["ent_missing"])
    assert client.get(f"/entities/{live['id']}").json()["entity"]["tags"] == []
    assert client.get(f"/entities/{live['id']}").json()["entity"]["tag_revision"] == 1

    deprecated = _bulk(
        client,
        "entities",
        "add",
        [retired["id"], full["id"], live["id"]],
        ["tag_missing"],
    )
    problem = assert_problem(deprecated, status=422, code="ENTITY_DEPRECATED")
    assert problem["subjects"] == _refs("entity", [retired["id"]])

    unknown_tag = _bulk(
        client,
        "entities",
        "add",
        [full["id"], live["id"]],
        [known, "tag_missing"],
    )
    problem = assert_problem(unknown_tag, status=404, code="TAG_NOT_FOUND")
    assert "subjects" not in problem
    assert client.get(f"/entities/{live['id']}").json()["entity"]["tag_revision"] == 1
    assert client.get(f"/entities/{full['id']}").json()["entity"]["tag_revision"] == 2
    assert client.get("/tags", params={"q": "tag_missing"}).json()["total"] == 0

    capped = _bulk(client, "entities", "add", [live["id"], full["id"]], [known])
    problem = assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert problem["subjects"] == _refs("entity", [full["id"]])
    assert client.get(f"/entities/{live['id']}").json()["entity"]["tags"] == []
    assert _audit("tags.add", "entity") == before

    removed = _bulk(
        client,
        "entities",
        "remove",
        ["ent_gone", retired["id"]],
        ["tag_not_live"],
    )
    problem = assert_problem(removed, status=404, code="ENTITY_NOT_FOUND")
    assert problem["subjects"] == _refs("entity", ["ent_gone"])
    removed_deprecated = _bulk(
        client, "entities", "remove", [retired["id"], live["id"]], ["tag_not_live"]
    )
    problem = assert_problem(removed_deprecated, status=422, code="ENTITY_DEPRECATED")
    assert problem["subjects"] == _refs("entity", [retired["id"]])
    assert _audit("tags.remove", "entity") == []


def test_bulk_remove_ignores_tags_the_subject_does_not_have(client: TestClient) -> None:
    holding = _create_entity(client, table_name="holding", name="Holding")
    empty = _create_entity(client, table_name="empty_row", name="Empty")
    alpha = _tag(client, "Alpha")
    beta = _tag(client, "beta")
    _replace_entity(client, holding["id"], base_revision=1, tag_ids=[alpha, beta])

    removed = _bulk(
        client,
        "entities",
        "remove",
        [holding["id"], empty["id"]],
        [alpha, "tag_not_live"],
    )
    assert removed.status_code == 200, removed.text
    subjects = removed.json()["subjects"]
    assert [item["id"] for item in subjects] == [holding["id"], empty["id"]]
    assert subjects[0]["tags"] == [{"id": beta, "name": "beta"}]
    assert subjects[0]["tag_revision"] == 3
    assert subjects[1]["tags"] == []
    assert subjects[1]["tag_revision"] == 1
    events = _audit("tags.remove", "entity")
    assert len(events) == 1
    assert events[0].resource_id == holding["id"]
    assert events[0].action == "tags.remove"
    assert events[0].detail["tag_ids"] == [beta]

    again = _bulk(
        client, "entities", "remove", [holding["id"], empty["id"]], ["tag_not_live"]
    )
    assert again.status_code == 200, again.text
    assert [item["tag_revision"] for item in again.json()["subjects"]] == [3, 1]
    assert len(_audit("tags.remove", "entity")) == 1
    assert client.get("/tags").json()["total"] == 2


def test_bulk_rejects_a_name_and_does_not_create_a_tag(client: TestClient) -> None:
    entity = _create_entity(client)
    tag_id = _tag(client, "Ledger")
    refused = client.post(
        "/entities/tags/add",
        json={"entity_ids": [entity["id"]], "tag_ids": [tag_id], "names": ["Nope"]},
    )
    assert_problem(refused, status=422, code="REQUEST_INVALID")
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert detail["tags"] == []
    assert detail["tag_revision"] == 1
    assert client.get("/tags", params={"q": "Nope"}).json()["total"] == 0
    assert _audit("tags.add", "entity") == []
    assert len(_audit("create", "tag")) == 1


def test_channel_bulk_add_and_remove(client: TestClient) -> None:
    quiet = _create_channel(client, name="Quiet")
    other = _create_channel(client, name="Other")
    alpha = _tag(client, "Alpha")
    beta = _tag(client, "beta")
    assert quiet["active"] is False
    before_updated = quiet["updated_at"]
    before_draft = quiet["draft_revision"]
    before_draft_at = quiet["draft_updated_at"]

    added = _bulk(client, "channels", "add", [quiet["id"], other["id"]], [beta, alpha])
    assert added.status_code == 200, added.text
    subjects = added.json()["subjects"]
    assert [item["id"] for item in subjects] == [quiet["id"], other["id"]]
    assert subjects[0]["tags"] == [
        {"id": alpha, "name": "Alpha"},
        {"id": beta, "name": "beta"},
    ]
    assert subjects[0]["tag_revision"] == 2
    assert subjects[1]["tag_revision"] == 2
    stored = client.get(f"/channels/{quiet['id']}").json()["channel"]
    assert stored["active"] is False
    assert stored["updated_at"] == before_updated
    assert stored["draft_revision"] == before_draft
    assert stored["draft_updated_at"] == before_draft_at
    assert len(_audit("tags.add", "channel")) == 2

    same = _bulk(client, "channels", "add", [quiet["id"]], [alpha])
    assert same.status_code == 200, same.text
    assert same.json()["subjects"][0]["tag_revision"] == 2
    assert len(_audit("tags.add", "channel")) == 2

    removed = _bulk(
        client, "channels", "remove", [quiet["id"], other["id"]], [alpha, "tag_not_live"]
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["subjects"][0]["tags"] == [{"id": beta, "name": "beta"}]
    assert removed.json()["subjects"][0]["tag_revision"] == 3
    assert removed.json()["subjects"][1]["tag_revision"] == 3
    events = _audit("tags.remove", "channel")
    assert len(events) == 2
    assert [event.detail["tag_ids"] for event in events] == [[beta], [beta]]


def test_channel_bulk_errors_follow_precedence(client: TestClient) -> None:
    live = _create_channel(client, name="Live")
    full = _create_channel(client, name="Full")
    held = [_tag(client, f"held-{index}") for index in range(10)]
    known = _tag(client, "known")
    _replace_channel(client, full["id"], base_revision=1, tag_ids=held)
    before = _audit("tags.add", "channel")

    missing = _bulk(
        client,
        "channels",
        "add",
        ["chn_missing", "chn_other", live["id"]],
        [known, "tag_missing"],
    )
    problem = assert_problem(missing, status=404, code="CHANNEL_NOT_FOUND")
    assert problem["subjects"] == _refs("channel", ["chn_missing", "chn_other"])
    assert client.get(f"/channels/{live['id']}").json()["channel"]["tag_revision"] == 1

    unknown = _bulk(
        client, "channels", "add", [full["id"], live["id"]], ["tag_missing", known]
    )
    problem = assert_problem(unknown, status=404, code="TAG_NOT_FOUND")
    assert "subjects" not in problem

    capped = _bulk(client, "channels", "add", [live["id"], full["id"]], [known])
    problem = assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert problem["subjects"] == _refs("channel", [full["id"]])
    assert client.get(f"/channels/{live['id']}").json()["channel"]["tags"] == []
    assert client.get(f"/channels/{full['id']}").json()["channel"]["tag_revision"] == 2
    assert _audit("tags.add", "channel") == before


def test_writer_without_tag_write_can_bulk_add_an_existing_tag(client: TestClient) -> None:
    tag_id = _tag(client, "Ledger")
    entity = _create_entity(client)
    channel = _create_channel(client)
    entity_writer = _open_client(
        "entity_writer", "secret", ["console:access", "entity:read", "entity:write"]
    )
    channel_writer = _open_client(
        "channel_writer",
        "secret",
        ["console:access", "channel:read", "channel:write"],
    )
    try:
        added_entity = _bulk(entity_writer, "entities", "add", [entity["id"]], [tag_id])
        assert added_entity.status_code == 200, added_entity.text
        assert added_entity.json()["subjects"][0]["tags"] == [
            {"id": tag_id, "name": "Ledger"}
        ]
        added_channel = _bulk(
            channel_writer, "channels", "add", [channel["id"]], [tag_id]
        )
        assert added_channel.status_code == 200, added_channel.text
        assert added_channel.json()["subjects"][0]["tag_revision"] == 2
    finally:
        entity_writer.__exit__(None, None, None)
        channel_writer.__exit__(None, None, None)
    assert client.get("/tags", params={"q": "Ledger"}).json()["total"] == 1
    assert len(_audit("create", "tag")) == 1


def test_concurrent_bulk_adds_stop_at_ten(client: TestClient) -> None:
    entity = _create_entity(client)
    held = [_tag(client, f"held-{index}") for index in range(9)]
    extra_a = _tag(client, "extra-a")
    extra_b = _tag(client, "extra-b")
    _replace_entity(client, entity["id"], base_revision=1, tag_ids=held)

    def add(tag_id: str) -> int:
        with TestClient(app) as local:
            _login(local, "admin", "secret")
            response = _bulk(local, "entities", "add", [entity["id"]], [tag_id])
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(add, (extra_a, extra_b)))
    assert 500 not in codes
    assert sorted(codes) == [200, 422]
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    final_ids = {tag["id"] for tag in detail["tags"]}
    assert set(held) <= final_ids
    assert len(final_ids) == 10
    assert len(final_ids & {extra_a, extra_b}) == 1
    assert len(_audit("tags.add", "entity")) == 1
