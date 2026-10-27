"""Tag usage over HTTP: global counts versus the lists a caller can open."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.store import reset_tag_store  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402
from backend.worker.app import celery_app  # noqa: E402

# The app reads CELERY_TASK_ALWAYS_EAGER only while it is constructed.
# A file collected earlier can import it first, so set the live config too.
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

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
def _eager_publish() -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    reset_tag_store()
    yield
    reset_tag_store()


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


def _entity_body(**overrides: object) -> dict:
    body: dict = {
        "table_name": "material",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [SKU],
    }
    body.update(overrides)
    return body


def _assign_entity_tags(client: TestClient, entity: dict, tag_ids: list[str]) -> None:
    replaced = client.put(
        f"/entities/{entity['id']}/tags",
        json={
            "base_revision": entity["tag_revision"],
            "tag_ids": tag_ids,
            "names": [],
        },
    )
    assert replaced.status_code == 200, replaced.text


def _assign_channel_tags(client: TestClient, channel: dict, tag_ids: list[str]) -> None:
    replaced = client.put(
        f"/channels/{channel['id']}/tags",
        json={
            "base_revision": channel["tag_revision"],
            "tag_ids": tag_ids,
            "names": [],
        },
    )
    assert replaced.status_code == 200, replaced.text


def _listed(response):
    assert response.status_code == 200, response.text
    body = response.json()
    return {item["id"] for item in body["items"]}, body["total"], body


def _create_entity(client: TestClient, table_name: str, name: str) -> dict:
    created = client.post("/entities", json=_entity_body(table_name=table_name, name=name))
    assert created.status_code == 201, created.text
    return created.json()["entity"]


def _publish(client: TestClient, entity: dict) -> None:
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text


def test_hidden_entity_stays_off_the_list_and_inside_the_counts(
    client: TestClient,
) -> None:
    from backend.tests.entity_access_oracle import seed_entity_entitlements

    roles = get_role_store()
    reader_role = create_role(
        roles,
        key="tag_usage_reader",
        name="Tag usage reader",
        permissions=[
            "console:access",
            "tag:read",
            "tag:write",
            "entity:read",
            "entity:data_read",
        ],
    )
    get_user_store().create_user(
        account="tagusage",
        display_name="Tag usage",
        password_hash=hash_password("secret"),
        role_id=reader_role.id,
        status="active",
    )
    tag_id = client.post("/tags", json={"name": "UsageMark"}).json()["tag"]["id"]
    shown = _create_entity(client, "usage_shown", "Shown")
    hidden = _create_entity(client, "usage_hidden", "Hidden")
    _assign_entity_tags(client, shown, [tag_id])
    _assign_entity_tags(client, hidden, [tag_id])
    _publish(client, shown)
    _publish(client, hidden)
    assert seed_entity_entitlements(shown["id"]) is True

    admin_ids, admin_total, _ = _listed(
        client.get("/entities", params=[("tag_id", tag_id)])
    )
    assert admin_total == 2
    assert admin_ids == {shown["id"], hidden["id"]}

    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login", json={"account": "tagusage", "password": "secret"}
    )
    assert logged_in.status_code == 200, logged_in.text

    visible_ids, visible_total, _ = _listed(
        client.get("/entities", params=[("tag_id", tag_id)])
    )
    assert visible_total == 1
    assert visible_ids == {shown["id"]}
    assert hidden["id"] not in visible_ids

    detail = client.get(f"/tags/{tag_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["tag"]["entity_count"] == 2
    assert detail.json()["tag"]["channel_count"] == 0

    refused = client.delete(f"/tags/{tag_id}")
    problem = assert_problem(refused, status=409, code="TAG_IN_USE")
    assert problem["entity_count"] == 2
    assert problem["channel_count"] == 0
    still = client.get(f"/tags/{tag_id}")
    assert still.status_code == 200, still.text
    assert still.json()["tag"]["entity_count"] == 2


def test_omitted_status_lists_a_deprecated_entity_that_carries_the_tag(
    client: TestClient,
) -> None:
    tag_id = client.post("/tags", json={"name": "RetiredMark"}).json()["tag"]["id"]
    draft = _create_entity(client, "usage_draft", "Draft")
    retired = _create_entity(client, "usage_retired", "Retired")
    _assign_entity_tags(client, draft, [tag_id])
    _assign_entity_tags(client, retired, [tag_id])
    _publish(client, retired)
    deprecated = client.post(f"/entities/{retired['id']}/deprecate")
    assert deprecated.status_code == 200, deprecated.text

    ids, total, body = _listed(client.get("/entities", params=[("tag_id", tag_id)]))
    assert total == 2
    assert ids == {draft["id"], retired["id"]}
    retired_row = next(item for item in body["items"] if item["id"] == retired["id"])
    assert retired_row["deprecated_at"] is not None


def test_omitted_active_lists_an_inactive_channel_that_carries_the_tag(
    client: TestClient,
) -> None:
    tag_id = client.post("/tags", json={"name": "QuietMark"}).json()["tag"]["id"]

    def create(name: str) -> dict:
        created = client.post("/channels", json={"name": name, "description": None})
        assert created.status_code == 201, created.text
        return created.json()["channel"]

    quiet = create("Quiet")
    live = create("Live")
    assert quiet["active"] is False
    _assign_channel_tags(client, quiet, [tag_id])
    _assign_channel_tags(client, live, [tag_id])
    assert client.post(f"/channels/{live['id']}/activate").status_code == 200

    ids, total, body = _listed(client.get("/channels", params=[("tag_id", tag_id)]))
    assert total == 2
    assert ids == {quiet["id"], live["id"]}
    quiet_row = next(item for item in body["items"] if item["id"] == quiet["id"])
    assert quiet_row["active"] is False


def _subjects(client: TestClient, tag_id: str, **params: int):
    response = client.get(f"/tags/{tag_id}/subjects", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    return body["items"], body["total"], body


def test_subjects_page_orders_entities_then_channels(client: TestClient) -> None:
    tag_id = client.post("/tags", json={"name": "PageMark"}).json()["tag"]["id"]
    first = _create_entity(client, "usage_first", "First")
    second = _create_entity(client, "usage_second", "Second")
    created = client.post("/channels", json={"name": "Live", "description": None})
    assert created.status_code == 201, created.text
    channel = created.json()["channel"]
    _assign_entity_tags(client, second, [tag_id])
    _assign_entity_tags(client, first, [tag_id])
    _assign_channel_tags(client, channel, [tag_id])

    page, total, _ = _subjects(client, tag_id, limit=2, offset=0)
    assert total == 3
    assert [item["kind"] for item in page] == ["entity", "entity"]
    assert [item["id"] for item in page] == sorted([first["id"], second["id"]])
    assert page[0]["table_name"] in {"usage_first", "usage_second"}

    rest, rest_total, _ = _subjects(client, tag_id, limit=2, offset=2)
    assert rest_total == 3
    assert rest == [
        {
            "kind": "channel",
            "id": channel["id"],
            "name": "Live",
            "active": False,
        }
    ]


def test_subjects_drop_a_hidden_entity_and_a_missing_subject(client: TestClient) -> None:
    from backend.tags.api import KIND_ENTITY, add_tags
    from backend.tests.entity_access_oracle import seed_entity_entitlements

    roles = get_role_store()
    reader_role = create_role(
        roles,
        key="tag_subject_reader",
        name="Tag subject reader",
        permissions=[
            "console:access",
            "tag:read",
            "entity:read",
            "entity:data_read",
        ],
    )
    get_user_store().create_user(
        account="tagsubject",
        display_name="Tag subject",
        password_hash=hash_password("secret"),
        role_id=reader_role.id,
        status="active",
    )
    tag_id = client.post("/tags", json={"name": "VisibleMark"}).json()["tag"]["id"]
    shown = _create_entity(client, "subject_shown", "Shown")
    hidden = _create_entity(client, "subject_hidden", "Hidden")
    _assign_entity_tags(client, shown, [tag_id])
    _assign_entity_tags(client, hidden, [tag_id])
    _publish(client, shown)
    _publish(client, hidden)
    assert seed_entity_entitlements(shown["id"]) is True
    add_tags(
        kind=KIND_ENTITY,
        subject_id="ent_gone",
        tag_ids=[tag_id],
        actor_user_id=None,
        actor_token_id=None,
    )

    detail = client.get(f"/tags/{tag_id}")
    assert detail.json()["tag"]["entity_count"] == 3

    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login", json={"account": "tagsubject", "password": "secret"}
    )
    assert logged_in.status_code == 200, logged_in.text
    items, total, _ = _subjects(client, tag_id)
    assert total == 1
    assert items[0]["id"] == shown["id"]
    assert items[0]["ever_published"] is True
    assert "ent_gone" not in {item["id"] for item in items}
    assert hidden["id"] not in {item["id"] for item in items}


def test_subjects_keep_deprecated_entities_and_inactive_channels(
    client: TestClient,
) -> None:
    tag_id = client.post("/tags", json={"name": "StayMark"}).json()["tag"]["id"]
    draft = _create_entity(client, "subject_draft", "Draft")
    retired = _create_entity(client, "subject_retired", "Retired")
    _assign_entity_tags(client, draft, [tag_id])
    _assign_entity_tags(client, retired, [tag_id])
    _publish(client, retired)
    assert client.post(f"/entities/{retired['id']}/deprecate").status_code == 200
    created = client.post("/channels", json={"name": "Quiet", "description": None})
    channel = created.json()["channel"]
    _assign_channel_tags(client, channel, [tag_id])

    items, total, _ = _subjects(client, tag_id)
    assert total == 3
    by_id = {item["id"]: item for item in items}
    assert by_id[draft["id"]]["ever_published"] is False
    assert by_id[retired["id"]]["deprecated_at"] is not None
    assert by_id[channel["id"]]["active"] is False


def test_subjects_omit_a_side_without_list_permission(client: TestClient) -> None:
    roles = get_role_store()
    channel_only = create_role(
        roles,
        key="tag_channel_only",
        name="Tag channel only",
        permissions=["console:access", "tag:read", "channel:read"],
    )
    get_user_store().create_user(
        account="tagchannel",
        display_name="Tag channel",
        password_hash=hash_password("secret"),
        role_id=channel_only.id,
        status="active",
    )
    tag_id = client.post("/tags", json={"name": "SideMark"}).json()["tag"]["id"]
    entity = _create_entity(client, "subject_side", "Side")
    _assign_entity_tags(client, entity, [tag_id])
    created = client.post("/channels", json={"name": "Side channel", "description": None})
    channel = created.json()["channel"]
    _assign_channel_tags(client, channel, [tag_id])

    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login", json={"account": "tagchannel", "password": "secret"}
    )
    assert logged_in.status_code == 200, logged_in.text
    items, total, _ = _subjects(client, tag_id)
    assert total == 1
    assert items[0]["kind"] == "channel"
    assert items[0]["id"] == channel["id"]


def test_subjects_require_tag_read_and_a_live_tag(client: TestClient) -> None:
    roles = get_role_store()
    entity_only = create_role(
        roles,
        key="tag_entity_only",
        name="Tag entity only",
        permissions=["console:access", "entity:read"],
    )
    get_user_store().create_user(
        account="tagentity",
        display_name="Tag entity",
        password_hash=hash_password("secret"),
        role_id=entity_only.id,
        status="active",
    )
    client.post("/auth/logout")
    logged_in = client.post(
        "/auth/login", json={"account": "tagentity", "password": "secret"}
    )
    assert logged_in.status_code == 200, logged_in.text
    missing_permission = client.get("/tags/tag_0123456789ab/subjects")
    assert_problem(missing_permission, status=403, code="AUTH_FORBIDDEN")

    client.post("/auth/logout")
    admin = client.post("/auth/login", json={"account": "admin", "password": "secret"})
    assert admin.status_code == 200, admin.text
    missing = client.get("/tags/tag_0123456789ab/subjects")
    assert_problem(missing, status=404, code="TAG_NOT_FOUND")
