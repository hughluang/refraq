"""Entity Tag assignment HTTP tests against the memory store."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
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


def _entity_body(**overrides: object) -> dict:
    body: dict = {
        "table_name": "material",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [SKU],
    }
    body.update(overrides)
    return body


def _create_entity(client: TestClient, **overrides: object) -> dict:
    created = client.post("/entities", json=_entity_body(**overrides))
    assert created.status_code == 201, created.text
    return created.json()["entity"]


def _put_tags(
    client: TestClient,
    entity_id: str,
    *,
    base_revision: int,
    tag_ids: list[str] | None = None,
    names: list[str] | None = None,
) -> object:
    return client.put(
        f"/entities/{entity_id}/tags",
        json={
            "base_revision": base_revision,
            "tag_ids": [] if tag_ids is None else tag_ids,
            "names": [] if names is None else names,
        },
    )


def _audit(action: str, resource_type: str) -> list:
    events, _total = get_audit_store().list_events(
        action=action, resource_type=resource_type
    )
    return events


def test_new_entity_starts_with_no_tags(client: TestClient) -> None:
    entity = _create_entity(client)
    assert entity["tags"] == []
    assert entity["tag_revision"] == 1

    listed = client.get("/entities")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["tags"] == []
    assert item["tag_revision"] == 1

    detail = client.get(f"/entities/{entity['id']}")
    assert detail.status_code == 200
    assert detail.json()["entity"]["tags"] == []
    assert detail.json()["entity"]["tag_revision"] == 1


def test_replace_orders_tags_and_counts_a_repeated_id_once(client: TestClient) -> None:
    entity = _create_entity(client)
    beta = client.post("/tags", json={"name": "beta"})
    alpha = client.post("/tags", json={"name": "Alpha"})
    assert beta.status_code == 201 and alpha.status_code == 201
    beta_id = beta.json()["tag"]["id"]
    alpha_id = alpha.json()["tag"]["id"]

    replaced = _put_tags(
        client,
        entity["id"],
        base_revision=1,
        tag_ids=[beta_id, alpha_id, beta_id],
    )
    assert replaced.status_code == 200, replaced.text
    body = replaced.json()
    assert [tag["name"] for tag in body["tags"]] == ["Alpha", "beta"]
    assert [tag["id"] for tag in body["tags"]] == [alpha_id, beta_id]
    assert body["tag_revision"] == 2

    again = _put_tags(
        client,
        entity["id"],
        base_revision=2,
        tag_ids=[alpha_id, alpha_id, beta_id],
    )
    assert again.status_code == 200, again.text
    assert again.json()["tag_revision"] == 2
    assert len(_audit("tags.replace", "entity")) == 1


def test_replace_clears_the_set_and_rejects_more_than_ten(client: TestClient) -> None:
    entity = _create_entity(client)
    cleared = _put_tags(client, entity["id"], base_revision=1)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"tags": [], "tag_revision": 1}
    assert _audit("tags.replace", "entity") == []

    capped = _put_tags(
        client,
        entity["id"],
        base_revision=1,
        names=[f"cap-{index}" for index in range(11)],
    )
    problem = assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert problem["subjects"] == [{"kind": "entity", "id": entity["id"]}]
    assert client.get("/tags").json()["total"] == 0
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert detail["tags"] == []
    assert detail["tag_revision"] == 1


def test_ten_tags_already_held_do_not_count_twice(client: TestClient) -> None:
    entity = _create_entity(client)
    created = [
        client.post("/tags", json={"name": f"held-{index}"}).json()["tag"]["id"]
        for index in range(10)
    ]
    first = _put_tags(client, entity["id"], base_revision=1, tag_ids=created + [created[0]])
    assert first.status_code == 200, first.text
    assert first.json()["tag_revision"] == 2
    assert len(first.json()["tags"]) == 10

    same = _put_tags(client, entity["id"], base_revision=2, tag_ids=created)
    assert same.status_code == 200, same.text
    assert same.json()["tag_revision"] == 2

    overflow = _put_tags(
        client,
        entity["id"],
        base_revision=2,
        tag_ids=created,
        names=["eleventh"],
    )
    assert_problem(overflow, status=422, code="TAG_LIMIT_EXCEEDED")
    assert client.get("/tags", params={"q": "eleventh"}).json()["total"] == 0
    kept = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert kept["tag_revision"] == 2
    assert len(kept["tags"]) == 10


def test_stale_revision_leaves_the_newer_set(client: TestClient) -> None:
    entity = _create_entity(client)
    first = _put_tags(client, entity["id"], base_revision=1, names=["Ledger"])
    assert first.status_code == 200, first.text
    newer = _put_tags(client, entity["id"], base_revision=2, names=["Books"])
    assert newer.status_code == 200, newer.text
    stale = _put_tags(
        client,
        entity["id"],
        base_revision=2,
        names=["Ledger"],
        tag_ids=["tag_doesnotexist"],
    )
    assert_problem(stale, status=409, code="TAG_ASSIGNMENT_CONFLICT")
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert detail["tag_revision"] == 3
    assert [tag["name"] for tag in detail["tags"]] == ["Books"]


def test_single_subject_errors_follow_precedence(client: TestClient) -> None:
    reader = _open_client("reader", "secret", ["console:access", "entity:read"])
    forbidden = reader.put(
        "/entities/ent_missing/tags",
        json={"base_revision": 1, "tag_ids": [], "names": []},
    )
    assert_problem(forbidden, status=403, code="AUTH_FORBIDDEN")
    reader.__exit__(None, None, None)

    missing = _put_tags(client, "ent_missing", base_revision=1, names=["x" * 257])
    assert_problem(missing, status=404, code="ENTITY_NOT_FOUND")

    entity = _create_entity(client)
    version_id = entity["current_version"]["id"]
    assert client.post(f"/entities/{entity['id']}/versions/{version_id}/publish").status_code == 201
    assert client.post(f"/entities/{entity['id']}/deprecate").status_code == 200
    deprecated = _put_tags(
        client,
        entity["id"],
        base_revision=0,
        tag_ids=["tag_doesnotexist"],
        names=["x" * 257],
    )
    assert_problem(deprecated, status=422, code="ENTITY_DEPRECATED")
    assert client.get(f"/entities/{entity['id']}").json()["entity"]["tag_revision"] == 1

    live = _create_entity(client, table_name="live_shape", name="Live")
    unknown_tag = _put_tags(
        client,
        live["id"],
        base_revision=1,
        tag_ids=["tag_doesnotexist"],
        names=["x" * 257],
    )
    assert_problem(unknown_tag, status=404, code="TAG_NOT_FOUND")
    invalid = _put_tags(client, live["id"], base_revision=1, names=["x" * 257, "ok-name"])
    assert_problem(invalid, status=422, code="TAG_NAME_INVALID")
    assert client.get("/tags", params={"q": "ok-name"}).json()["total"] == 0
    assert client.get(f"/entities/{live['id']}").json()["entity"]["tags"] == []


def test_create_rejects_a_bad_tag_without_leaving_a_record(client: TestClient) -> None:
    refused = client.post(
        "/entities",
        json=_entity_body(tags={"names": ["x" * 257]}),
    )
    assert_problem(refused, status=422, code="TAG_NAME_INVALID")
    assert client.get("/entities").json()["total"] == 0
    assert client.get("/tags").json()["total"] == 0

    capped = client.post(
        "/entities",
        json=_entity_body(
            table_name="capped",
            tags={"names": [f"new-{index}" for index in range(11)]},
        ),
    )
    assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert client.get("/entities").json()["total"] == 0
    assert client.get("/tags").json()["total"] == 0

    created = client.post(
        "/entities",
        json=_entity_body(tags={"names": ["  finance  "]}),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    assert entity["tag_revision"] == 2
    assert entity["tags"][0]["name"] == "finance"
    assert len(_audit("create", "tag")) == 1
    assert len(_audit("tags.replace", "entity")) == 1


def test_patch_rejects_tags_and_leaves_the_set(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_entity_body(tags={"names": ["Ledger"]}),
    )
    entity = created.json()["entity"]
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"name": "Material", "tags": {"tag_ids": [], "names": ["Other"]}},
    )
    assert_problem(patched, status=422, code="REQUEST_INVALID")
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert detail["name"] == "Material"
    assert detail["tag_revision"] == 2
    assert [tag["name"] for tag in detail["tags"]] == ["Ledger"]


def test_folded_inline_name_attaches_the_existing_tag(client: TestClient) -> None:
    created = client.post("/tags", json={"name": "FINANCE"})
    tag_id = created.json()["tag"]["id"]
    entity = _create_entity(client)
    for spelling in ("finance", "  ＦＩＮＡＮＣＥ  ", "ｆｉｎａｎｃｅ"):
        replaced = _put_tags(
            client,
            entity["id"],
            base_revision=1 if spelling == "finance" else 2,
            names=[spelling],
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["tags"] == [{"id": tag_id, "name": "FINANCE"}]
    stored = client.get(f"/tags/{tag_id}")
    assert stored.json()["tag"]["name"] == "FINANCE"
    assert stored.json()["tag"]["entity_count"] == 1
    assert stored.json()["tag"]["channel_count"] == 0
    conflict = client.post("/tags", json={"name": "finance"})
    assert_problem(conflict, status=409, code="TAG_NAME_CONFLICT")
    assert client.get(f"/tags/{tag_id}").json()["tag"]["name"] == "FINANCE"


def test_overlapping_entity_creates_of_one_name_yield_one_tag(client: TestClient) -> None:
    def post(index: int) -> tuple[int, str | None]:
        with TestClient(app) as local:
            _login(local, "admin", "secret")
            response = local.post(
                "/entities",
                json=_entity_body(
                    table_name=f"overlap_{index}",
                    name=f"Overlap {index}",
                    tags={"names": ["OverlapWord"]},
                ),
            )
            tag_id = None
            if response.status_code == 201:
                tags = response.json()["entity"]["tags"]
                tag_id = tags[0]["id"] if tags else None
            return response.status_code, tag_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, (0, 1)))
    codes = [code for code, _tag_id in results]
    assert 500 not in codes
    assert codes == [201, 201]
    tag_ids = {tag_id for _code, tag_id in results}
    assert len(tag_ids) == 1
    assert client.get("/tags", params={"q": "OverlapWord"}).json()["total"] == 1


def test_published_entity_accepts_tags_without_moving_timestamps(client: TestClient) -> None:
    entity = _create_entity(client)
    version_id = entity["current_version"]["id"]
    before_entity = entity["updated_at"]
    before_version = client.get(f"/entities/{entity['id']}/versions/{version_id}").json()[
        "version"
    ]["updated_at"]
    replaced = _put_tags(client, entity["id"], base_revision=1, names=["Ledger"])
    assert replaced.status_code == 200, replaced.text
    after = client.get(f"/entities/{entity['id']}").json()["entity"]
    after_version = client.get(f"/entities/{entity['id']}/versions/{version_id}").json()[
        "version"
    ]["updated_at"]
    assert after["updated_at"] == before_entity
    assert after_version == before_version
    assert after["tag_revision"] == 2

    assert (
        client.post(f"/entities/{entity['id']}/versions/{version_id}/publish").status_code
        == 201
    )
    published = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert published["tag_revision"] == 2
    assert [tag["name"] for tag in published["tags"]] == ["Ledger"]

    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 201, opened.text
    still = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert still["tag_revision"] == 2
    assert [tag["name"] for tag in still["tags"]] == ["Ledger"]

    changed = _put_tags(client, entity["id"], base_revision=2, names=["Books"])
    assert changed.status_code == 200, changed.text

    assert client.post(f"/entities/{entity['id']}/deprecate").status_code == 200
    deprecated = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert [tag["name"] for tag in deprecated["tags"]] == ["Books"]
    refused = _put_tags(client, entity["id"], base_revision=3, names=["Nope"])
    assert_problem(refused, status=422, code="ENTITY_DEPRECATED")

    drop = client.post(f"/entities/{entity['id']}/versions/{version_id}/drop-table")
    assert drop.status_code in (200, 201), drop.text
    after_drop = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert after_drop["tag_revision"] == 3
    assert [tag["name"] for tag in after_drop["tags"]] == ["Books"]


def test_delete_clears_assignments_and_a_refused_delete_keeps_them(
    client: TestClient,
) -> None:
    kept = _create_entity(client, table_name="kept_shape", name="Kept")
    removed = _create_entity(client, table_name="removed_shape", name="Removed")
    tag = client.post("/tags", json={"name": "Shared"})
    tag_id = tag.json()["tag"]["id"]
    assert _put_tags(client, kept["id"], base_revision=1, tag_ids=[tag_id]).status_code == 200
    assert (
        _put_tags(client, removed["id"], base_revision=1, tag_ids=[tag_id]).status_code == 200
    )
    assert client.get(f"/tags/{tag_id}").json()["tag"]["entity_count"] == 2

    version_id = kept["current_version"]["id"]
    assert client.post(f"/entities/{kept['id']}/versions/{version_id}/publish").status_code == 201
    refused = client.delete(f"/entities/{kept['id']}")
    assert_problem(refused, status=409, code="ENTITY_ALREADY_PUBLISHED")
    assert [tag["id"] for tag in client.get(f"/entities/{kept['id']}").json()["entity"]["tags"]] == [
        tag_id
    ]

    assert client.delete(f"/entities/{removed['id']}").status_code == 204
    assert client.get(f"/tags/{tag_id}").json()["tag"]["entity_count"] == 1
    in_use = client.delete(f"/tags/{tag_id}")
    problem = assert_problem(in_use, status=409, code="TAG_IN_USE")
    assert problem["entity_count"] == 1
    assert problem["channel_count"] == 0
    assert client.get(f"/tags/{tag_id}").status_code == 200

    assert client.post(f"/entities/{kept['id']}/deprecate").status_code == 200
    assert client.get(f"/tags/{tag_id}").json()["tag"]["entity_count"] == 1


def test_entity_writer_can_create_a_tag_inline_without_tag_write(client: TestClient) -> None:
    writer = _open_client(
        "writer", "secret", ["console:access", "entity:read", "entity:write"]
    )
    created = writer.post("/entities", json=_entity_body(table_name="writer_shape"))
    assert created.status_code == 201, created.text
    entity_id = created.json()["entity"]["id"]
    replaced = _put_tags(writer, entity_id, base_revision=1, names=["  Inline Word  "])
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["tags"][0]["name"] == "Inline Word"
    assert replaced.json()["tag_revision"] == 2
    writer.__exit__(None, None, None)

    tag_id = replaced.json()["tags"][0]["id"]
    stored = client.get(f"/tags/{tag_id}")
    assert stored.status_code == 200, stored.text
    assert stored.json()["tag"]["name"] == "Inline Word"
    creates = _audit("create", "tag")
    assert len(creates) == 1
    assert creates[0].detail == {"name": "Inline Word"}
    replaces = _audit("tags.replace", "entity")
    assert len(replaces) == 1
    assert replaces[0].resource_type == "entity"
    assert replaces[0].resource_id == entity_id
    assert replaces[0].detail == {"tag_ids": [tag_id]}
    assert replaces[0].result == "success"

    same = client.put(
        f"/entities/{entity_id}/tags",
        json={"base_revision": 2, "tag_ids": [tag_id], "names": []},
    )
    assert same.status_code == 200, same.text
    assert same.json()["tag_revision"] == 2
    assert len(_audit("tags.replace", "entity")) == 1
    assert len(_audit("create", "tag")) == 1


def test_reader_cannot_change_tags(client: TestClient) -> None:
    entity = _create_entity(client)
    reader = _open_client("reader", "secret", ["console:access", "entity:read"])
    refused = _put_tags(reader, entity["id"], base_revision=1, names=["Nope"])
    assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
    reader.__exit__(None, None, None)
    detail = client.get(f"/entities/{entity['id']}").json()["entity"]
    assert detail["tags"] == []
    assert detail["tag_revision"] == 1
    assert client.get("/tags").json()["total"] == 0
