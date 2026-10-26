"""Channel list Tag and activation filters over HTTP."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tags.store import reset_tag_store  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_tags() -> None:
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


def _assign_tags(client: TestClient, channel: dict, tag_ids: list[str]) -> None:
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


def test_list_channels_filters_by_any_selected_tag_and_activation(
    client: TestClient,
) -> None:
    ledger = client.post("/tags", json={"name": "Ledger"}).json()["tag"]["id"]
    tax = client.post("/tags", json={"name": "Tax"}).json()["tag"]["id"]

    def create(name: str) -> dict:
        created = client.post("/channels", json={"name": name, "description": None})
        assert created.status_code == 201, created.text
        return created.json()["channel"]

    alpha = create("Alpha")
    beta = create("Beta")
    both = create("Both")
    plain = create("Plain")
    _assign_tags(client, alpha, [ledger])
    _assign_tags(client, beta, [tax])
    _assign_tags(client, both, [ledger, tax])
    assert client.post(f"/channels/{beta['id']}/activate").status_code == 200
    assert client.post(f"/channels/{plain['id']}/activate").status_code == 200

    everything, total, body = _listed(client.get("/channels"))
    assert total == 4
    assert everything == {alpha["id"], beta["id"], both["id"], plain["id"]}
    tags_by_id = {item["id"]: item["tags"] for item in body["items"]}
    assert tags_by_id[alpha["id"]] == [{"id": ledger, "name": "Ledger"}]
    assert tags_by_id[plain["id"]] == []

    one, one_total, _ = _listed(client.get("/channels", params=[("tag_id", ledger)]))
    assert one_total == 2
    assert one == {alpha["id"], both["id"]}

    either, either_total, _ = _listed(
        client.get("/channels", params=[("tag_id", ledger), ("tag_id", tax)])
    )
    assert either_total == 3
    assert either == {alpha["id"], beta["id"], both["id"]}

    named, named_total, _ = _listed(
        client.get(
            "/channels",
            params=[
                ("q", "Alpha"),
                ("active", "false"),
                ("tag_id", ledger),
            ],
        )
    )
    assert named_total == 1
    assert named == {alpha["id"]}

    missed, missed_total, _ = _listed(
        client.get(
            "/channels",
            params=[("q", "Alpha"), ("active", "true"), ("tag_id", ledger)],
        )
    )
    assert missed_total == 0
    assert missed == set()

    active_only, active_total, _ = _listed(
        client.get("/channels", params={"active": "true"})
    )
    assert active_total == 2
    assert active_only == {beta["id"], plain["id"]}

    inactive_only, inactive_total, _ = _listed(
        client.get("/channels", params={"active": "false"})
    )
    assert inactive_total == 2
    assert inactive_only == {alpha["id"], both["id"]}


def test_list_channels_unknown_tag_matches_no_row(client: TestClient) -> None:
    kept = client.post("/tags", json={"name": "Kept"}).json()["tag"]["id"]
    gone = client.post("/tags", json={"name": "Gone"})
    assert gone.status_code == 201, gone.text
    gone_id = gone.json()["tag"]["id"]
    assert client.delete(f"/tags/{gone_id}").status_code == 204

    created = client.post(
        "/channels", json={"name": "Kept row", "description": None}
    )
    assert created.status_code == 201, created.text
    channel = created.json()["channel"]
    _assign_tags(client, channel, [kept])

    missing, missing_total, _ = _listed(
        client.get("/channels", params=[("tag_id", "tag_not_live")])
    )
    assert missing_total == 0
    assert missing == set()

    deleted, deleted_total, _ = _listed(
        client.get("/channels", params=[("tag_id", gone_id)])
    )
    assert deleted_total == 0
    assert deleted == set()

    mixed, mixed_total, _ = _listed(
        client.get(
            "/channels",
            params=[
                ("tag_id", "tag_not_live"),
                ("tag_id", gone_id),
                ("tag_id", kept),
            ],
        )
    )
    assert mixed_total == 1
    assert mixed == {channel["id"]}


def test_list_channels_tag_page_matches_the_filtered_total(
    client: TestClient,
) -> None:
    mark = client.post("/tags", json={"name": "PageMark"}).json()["tag"]["id"]
    tagged: list[str] = []
    for index in range(3):
        created = client.post(
            "/channels",
            json={"name": f"Tagged {index}", "description": None},
        )
        assert created.status_code == 201, created.text
        channel = created.json()["channel"]
        _assign_tags(client, channel, [mark])
        tagged.append(channel["id"])
    live = client.post(
        "/channels", json={"name": "Tagged live", "description": None}
    )
    assert live.status_code == 201, live.text
    live_channel = live.json()["channel"]
    _assign_tags(client, live_channel, [mark])
    assert client.post(f"/channels/{live_channel['id']}/activate").status_code == 200
    for index in range(2):
        extra = client.post(
            "/channels",
            json={"name": f"Plain {index}", "description": None},
        )
        assert extra.status_code == 201, extra.text

    seen: list[str] = []
    for offset in (0, 1, 2):
        _ids, total, body = _listed(
            client.get(
                "/channels",
                params=[
                    ("q", "Tagged"),
                    ("active", "false"),
                    ("tag_id", mark),
                    ("limit", "1"),
                    ("offset", str(offset)),
                ],
            )
        )
        assert total == 3
        assert body["limit"] == 1
        assert body["offset"] == offset
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
    assert set(seen) == set(tagged)
    assert len(set(seen)) == 3

    beyond_ids, beyond_total, beyond = _listed(
        client.get(
            "/channels",
            params=[
                ("q", "Tagged"),
                ("active", "false"),
                ("tag_id", mark),
                ("limit", "1"),
                ("offset", "3"),
            ],
        )
    )
    assert beyond_total == 3
    assert beyond["offset"] == 3
    assert beyond_ids == set()
    assert beyond["items"] == []
