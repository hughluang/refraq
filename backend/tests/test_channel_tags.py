"""Channel Tag assignment HTTP tests against the memory store."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
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


def _create_channel(client: TestClient, **overrides: object) -> dict:
    body: dict = {"name": "Material master", "description": None}
    body.update(overrides)
    created = client.post("/channels", json=body)
    assert created.status_code == 201, created.text
    return created.json()["channel"]


def _put_tags(
    client: TestClient,
    channel_id: str,
    *,
    base_revision: int,
    tag_ids: list[str] | None = None,
    names: list[str] | None = None,
) -> object:
    return client.put(
        f"/channels/{channel_id}/tags",
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


def test_new_channel_starts_with_no_tags(client: TestClient) -> None:
    channel = _create_channel(client)
    assert channel["tags"] == []
    assert channel["tag_revision"] == 1

    listed = client.get("/channels")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["tags"] == []
    assert item["tag_revision"] == 1

    detail = client.get(f"/channels/{channel['id']}")
    assert detail.status_code == 200
    assert detail.json()["channel"]["tags"] == []
    assert detail.json()["channel"]["tag_revision"] == 1


def test_replace_orders_tags_and_counts_a_repeated_id_once(client: TestClient) -> None:
    channel = _create_channel(client)
    beta = client.post("/tags", json={"name": "beta"})
    alpha = client.post("/tags", json={"name": "Alpha"})
    assert beta.status_code == 201 and alpha.status_code == 201
    beta_id = beta.json()["tag"]["id"]
    alpha_id = alpha.json()["tag"]["id"]

    replaced = _put_tags(
        client,
        channel["id"],
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
        channel["id"],
        base_revision=2,
        tag_ids=[alpha_id, alpha_id, beta_id],
    )
    assert again.status_code == 200, again.text
    assert again.json()["tag_revision"] == 2
    assert len(_audit("tags.replace", "channel")) == 1


def test_replace_clears_the_set_and_rejects_more_than_ten(client: TestClient) -> None:
    channel = _create_channel(client)
    cleared = _put_tags(client, channel["id"], base_revision=1)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"tags": [], "tag_revision": 1}
    assert _audit("tags.replace", "channel") == []

    capped = _put_tags(
        client,
        channel["id"],
        base_revision=1,
        names=[f"cap-{index}" for index in range(11)],
    )
    problem = assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert problem["subjects"] == [{"kind": "channel", "id": channel["id"]}]
    assert client.get("/tags").json()["total"] == 0
    detail = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert detail["tags"] == []
    assert detail["tag_revision"] == 1


def test_stale_revision_leaves_the_newer_set(client: TestClient) -> None:
    channel = _create_channel(client)
    first = _put_tags(client, channel["id"], base_revision=1, names=["Ledger"])
    assert first.status_code == 200, first.text
    newer = _put_tags(client, channel["id"], base_revision=2, names=["Books"])
    assert newer.status_code == 200, newer.text
    stale = _put_tags(
        client,
        channel["id"],
        base_revision=2,
        names=["Ledger"],
        tag_ids=["tag_doesnotexist"],
    )
    assert_problem(stale, status=409, code="TAG_ASSIGNMENT_CONFLICT")
    detail = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert detail["tag_revision"] == 3
    assert [tag["name"] for tag in detail["tags"]] == ["Books"]
    assert client.get("/tags", params={"q": "Ledger"}).json()["total"] == 1


def test_assignment_errors_follow_precedence(client: TestClient) -> None:
    reader = _open_client("reader", "secret", ["console:access", "channel:read"])
    forbidden = reader.put(
        "/channels/chn_missing/tags",
        json={"names": ["x" * 257]},
    )
    assert_problem(forbidden, status=403, code="AUTH_FORBIDDEN")
    reader.__exit__(None, None, None)
    assert client.get("/tags").json()["total"] == 0

    missing = _put_tags(client, "chn_missing", base_revision=1, names=["x" * 257])
    assert_problem(missing, status=404, code="CHANNEL_NOT_FOUND")
    assert client.get("/tags").json()["total"] == 0

    channel = _create_channel(client)
    unknown_tag = _put_tags(
        client,
        channel["id"],
        base_revision=1,
        tag_ids=["tag_doesnotexist"],
        names=["x" * 257],
    )
    assert_problem(unknown_tag, status=404, code="TAG_NOT_FOUND")
    invalid = _put_tags(
        client, channel["id"], base_revision=1, names=["x" * 257, "ok-name"]
    )
    assert_problem(invalid, status=422, code="TAG_NAME_INVALID")
    assert client.get("/tags", params={"q": "ok-name"}).json()["total"] == 0
    assert client.get(f"/channels/{channel['id']}").json()["channel"]["tags"] == []


def test_create_rejects_a_bad_tag_without_leaving_a_record(client: TestClient) -> None:
    refused = client.post(
        "/channels",
        json={"name": "Material master", "description": None, "tags": {"names": ["x" * 257]}},
    )
    assert_problem(refused, status=422, code="TAG_NAME_INVALID")
    assert client.get("/channels").json()["total"] == 0
    assert client.get("/tags").json()["total"] == 0

    capped = client.post(
        "/channels",
        json={
            "name": "Capped",
            "description": None,
            "tags": {"names": [f"new-{index}" for index in range(11)]},
        },
    )
    assert_problem(capped, status=422, code="TAG_LIMIT_EXCEEDED")
    assert client.get("/channels").json()["total"] == 0
    assert client.get("/tags").json()["total"] == 0

    created = client.post(
        "/channels",
        json={"name": "Finance", "description": None, "tags": {"names": ["  finance  "]}},
    )
    assert created.status_code == 201, created.text
    channel = created.json()["channel"]
    assert channel["tag_revision"] == 2
    assert channel["tags"][0]["name"] == "finance"
    assert len(_audit("create", "tag")) == 1
    assert len(_audit("tags.replace", "channel")) == 1


def test_patch_rejects_tags_and_leaves_the_set(client: TestClient) -> None:
    created = client.post(
        "/channels",
        json={"name": "Material", "description": None, "tags": {"names": ["Ledger"]}},
    )
    channel = created.json()["channel"]
    patched = client.patch(
        f"/channels/{channel['id']}",
        json={"name": "Material", "tags": {"tag_ids": [], "names": ["Other"]}},
    )
    assert_problem(patched, status=422, code="REQUEST_INVALID")
    detail = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert detail["name"] == "Material"
    assert detail["tag_revision"] == 2
    assert [tag["name"] for tag in detail["tags"]] == ["Ledger"]


TRIGGER_GRAPH = {
    "nodes": [
        {
            "id": "nd_trigger",
            "ref": "run_manually",
            "type": "trigger.manual",
            "name": "Run manually",
            "position": {"x": 0, "y": 0},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}


def test_assignment_during_a_draft_run_leaves_the_draft_revision(
    client: TestClient,
) -> None:
    from backend.channel.channel_run import set_dispatcher

    channel = _create_channel(client)
    before = {
        "draft_revision": channel["draft_revision"],
        "draft_updated_at": channel["draft_updated_at"],
        "updated_at": channel["updated_at"],
    }
    inactive = _put_tags(client, channel["id"], base_revision=1, names=["Ledger"])
    assert inactive.status_code == 200, inactive.text
    after_inactive = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert after_inactive["active"] is False
    assert after_inactive["draft_revision"] == before["draft_revision"]
    assert after_inactive["draft_updated_at"] == before["draft_updated_at"]
    assert after_inactive["updated_at"] == before["updated_at"]
    assert after_inactive["tag_revision"] == 2

    activated = client.post(f"/channels/{channel['id']}/activate")
    assert activated.status_code == 200, activated.text
    active = activated.json()["channel"]
    assert active["active"] is True
    held = {
        "draft_revision": active["draft_revision"],
        "draft_updated_at": active["draft_updated_at"],
        "updated_at": active["updated_at"],
        "tag_revision": active["tag_revision"],
    }
    while_active = _put_tags(client, channel["id"], base_revision=2, names=["Books"])
    assert while_active.status_code == 200, while_active.text
    after_active = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert after_active["active"] is True
    assert after_active["draft_revision"] == held["draft_revision"]
    assert after_active["draft_updated_at"] == held["draft_updated_at"]
    assert after_active["updated_at"] == held["updated_at"]
    assert after_active["tag_revision"] == 3
    assert [tag["name"] for tag in after_active["tags"]] == ["Books"]

    saved = client.put(
        f"/channels/{channel['id']}/draft",
        json={"base_revision": after_active["draft_revision"], "graph": TRIGGER_GRAPH},
    )
    assert saved.status_code == 200, saved.text
    previous = set_dispatcher(lambda _job_id: None)
    try:
        started = client.post(
            f"/channels/{channel['id']}/runs", json={"target": "draft"}
        )
        assert started.status_code == 202, started.text
        assert started.json()["run"]["status"] in {"queued", "running"}
        frozen = client.get(f"/channels/{channel['id']}").json()["channel"]
        replaced = _put_tags(
            client, channel["id"], base_revision=3, names=["Ledger"]
        )
        assert replaced.status_code == 200, replaced.text
        current = client.get(f"/channels/{channel['id']}").json()["channel"]
        assert current["draft_revision"] == frozen["draft_revision"]
        assert current["draft_updated_at"] == frozen["draft_updated_at"]
        assert current["updated_at"] == frozen["updated_at"]
        assert current["tag_revision"] == 4
        assert [tag["name"] for tag in current["tags"]] == ["Ledger"]
        run = client.get(
            f"/channels/{channel['id']}/runs/{started.json()['run']['job_id']}"
        )
        assert run.status_code == 200, run.text
        assert run.json()["run"]["status"] in {"queued", "running"}
    finally:
        set_dispatcher(previous)


def test_delete_clears_assignments_and_deactivation_keeps_them(
    client: TestClient,
) -> None:
    kept = _create_channel(client, name="Kept")
    removed = _create_channel(client, name="Removed")
    tag = client.post("/tags", json={"name": "Shared"})
    assert tag.status_code == 201, tag.text
    tag_id = tag.json()["tag"]["id"]
    assert _put_tags(client, kept["id"], base_revision=1, tag_ids=[tag_id]).status_code == 200
    assert (
        _put_tags(client, removed["id"], base_revision=1, tag_ids=[tag_id]).status_code
        == 200
    )
    assert client.get(f"/tags/{tag_id}").json()["tag"]["channel_count"] == 2

    reader = _open_client("reader", "secret", ["console:access", "channel:read"])
    refused = reader.delete(f"/channels/{kept['id']}")
    assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
    reader.__exit__(None, None, None)
    missing = client.delete("/channels/chn_missing")
    assert_problem(missing, status=404, code="CHANNEL_NOT_FOUND")
    assert client.get(f"/tags/{tag_id}").json()["tag"]["channel_count"] == 2
    assert [
        tag["id"] for tag in client.get(f"/channels/{kept['id']}").json()["channel"]["tags"]
    ] == [tag_id]

    assert client.delete(f"/channels/{removed['id']}").status_code == 204
    assert client.get(f"/channels/{removed['id']}").status_code == 404
    assert client.get(f"/tags/{tag_id}").json()["tag"]["channel_count"] == 1
    in_use = client.delete(f"/tags/{tag_id}")
    problem = assert_problem(in_use, status=409, code="TAG_IN_USE")
    assert problem["channel_count"] == 1
    assert problem["entity_count"] == 0

    activated = client.post(f"/channels/{kept['id']}/activate")
    assert activated.status_code == 200, activated.text
    before = activated.json()["channel"]
    assert before["tag_revision"] == 2
    deactivated = client.post(f"/channels/{kept['id']}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    after = deactivated.json()["channel"]
    assert after["active"] is False
    assert after["tag_revision"] == before["tag_revision"]
    assert [tag["id"] for tag in after["tags"]] == [tag_id]
    assert client.get(f"/tags/{tag_id}").json()["tag"]["channel_count"] == 1


def test_ten_tags_already_held_do_not_count_twice(client: TestClient) -> None:
    channel = _create_channel(client)
    created = [
        client.post("/tags", json={"name": f"held-{index}"}).json()["tag"]["id"]
        for index in range(10)
    ]
    first = _put_tags(client, channel["id"], base_revision=1, tag_ids=created + [created[0]])
    assert first.status_code == 200, first.text
    assert first.json()["tag_revision"] == 2
    assert len(first.json()["tags"]) == 10

    overflow = _put_tags(
        client,
        channel["id"],
        base_revision=2,
        tag_ids=created,
        names=["eleventh"],
    )
    assert_problem(overflow, status=422, code="TAG_LIMIT_EXCEEDED")
    assert client.get("/tags", params={"q": "eleventh"}).json()["total"] == 0
    kept = client.get(f"/channels/{channel['id']}").json()["channel"]
    assert kept["tag_revision"] == 2
    assert len(kept["tags"]) == 10


def test_channel_writer_creates_a_tag_inline_without_tag_write(client: TestClient) -> None:
    existing = client.post("/tags", json={"name": "FINANCE"})
    assert existing.status_code == 201, existing.text
    tag_id = existing.json()["tag"]["id"]

    writer = _open_client(
        "writer", "secret", ["console:access", "channel:read", "channel:write"]
    )
    created = writer.post(
        "/channels",
        json={"name": "Writer", "description": None, "tags": {"names": ["  Inline Word  "]}},
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    assert created.json()["channel"]["tags"][0]["name"] == "Inline Word"
    folded = _put_tags(writer, channel_id, base_revision=2, names=["finance"])
    assert folded.status_code == 200, folded.text
    assert folded.json()["tags"] == [{"id": tag_id, "name": "FINANCE"}]
    assert folded.json()["tag_revision"] == 3
    writer.__exit__(None, None, None)

    stored = client.get(f"/tags/{tag_id}")
    assert stored.status_code == 200, stored.text
    assert stored.json()["tag"]["name"] == "FINANCE"
    assert stored.json()["tag"]["channel_count"] == 1
    inline_id = created.json()["channel"]["tags"][0]["id"]
    creates = _audit("create", "tag")
    assert len(creates) == 2
    assert {event.detail["name"] for event in creates} == {"FINANCE", "Inline Word"}
    replaces = _audit("tags.replace", "channel")
    assert len(replaces) == 2
    assert replaces[0].resource_type == "channel"
    assert replaces[0].resource_id == channel_id
    assert replaces[0].detail == {"tag_ids": [tag_id]}
    assert replaces[0].result == "success"

    same = client.put(
        f"/channels/{channel_id}/tags",
        json={"base_revision": 3, "tag_ids": [tag_id], "names": []},
    )
    assert same.status_code == 200, same.text
    assert same.json()["tag_revision"] == 3
    assert len(_audit("tags.replace", "channel")) == 2
    assert client.get(f"/tags/{inline_id}").json()["tag"]["name"] == "Inline Word"
