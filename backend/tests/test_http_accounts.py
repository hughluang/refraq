"""HTTP Account catalog API."""

from __future__ import annotations

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.permissions import ALL_PERMISSIONS  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, effective_permissions, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.errors import ChannelRequestInvalid  # noqa: E402
from backend.channel.http_accounts import (  # noqa: E402
    create_http_account,
    get_http_account_store,
    reset_http_account_store,
    update_http_account,
)
from backend.channel.ids import new_channel_id  # noqa: E402
from backend.channel.store import ChannelRecord, get_channel_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

TOKEN = "bearer-token-9f3a"
PASSWORD = "basic-password-9f3a"
HEADER_VALUE = "header-value-9f3a"
QUERY_VALUE = "query-value-9f3a"
QUERY_VALUE_REPEAT = "query-value-9f3a-b"
SECRETS = (TOKEN, PASSWORD, HEADER_VALUE, QUERY_VALUE, QUERY_VALUE_REPEAT)
_FORBIDDEN = (
    "authorization",
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "upgrade",
    "te",
    "trailer",
    "proxy-authorization",
    "proxy-connection",
)


@pytest.fixture()
def client() -> TestClient:
    reset_http_account_store()
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    if get_user_store().get_by_account("admin") is None:
        get_user_store().create_user(
            account="admin",
            display_name="Admin",
            password_hash=hash_password("secret"),
            role_id=admin.id,
            status="active",
        )
    with TestClient(app) as test_client:
        logged = test_client.post("/auth/login", json={"account": "admin", "password": "secret"})
        assert logged.status_code == 200, logged.text
        yield test_client


def _body(**overrides: object) -> dict:
    body: dict[str, object] = {
        "name": "  Office API  ",
        "auth": {"type": "bearer", "token": TOKEN},
        "headers": [{"name": "X-Api-Key", "value": HEADER_VALUE}],
        "query": [
            {"name": "api_key", "value": QUERY_VALUE},
            {"name": "api_key", "value": QUERY_VALUE_REPEAT},
        ],
        "allowed_origins": ["https://API.Example.com/"],
    }
    body.update(overrides)
    return body


def _create(client: TestClient, **overrides: object) -> dict:
    created = client.post("/http-accounts", json=_body(**overrides))
    assert created.status_code == 201, created.text
    return created.json()["http_account"]


def _assert_secrets_absent(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


def _events(action: str, resource_id: str | None = None) -> list:
    events, _cursor = get_audit_store().list_events(
        resource_type="http_account", action=action, limit=50
    )
    if resource_id is None:
        return events
    return [event for event in events if event.resource_id == resource_id]


def _assert_audit(action: str, resource_id: str, name: str) -> None:
    events = _events(action, resource_id)
    assert len(events) == 1
    event = events[0]
    assert event.resource_type == "http_account"
    assert event.result == "success"
    assert event.detail["name"] == name
    _assert_secrets_absent(json.dumps(event.detail))


def test_permissions_are_catalog_keys_and_not_operator_defaults() -> None:
    assert "http_account:read" in ALL_PERMISSIONS
    assert "http_account:write" in ALL_PERMISSIONS
    roles = get_role_store()
    seed_roles(roles)
    operator = roles.get_by_key("operator")
    assert operator is not None
    assert "http_account:read" not in effective_permissions(operator)
    assert "http_account:write" not in effective_permissions(operator)


def test_create_hides_secrets_and_normalizes_the_account(client: TestClient) -> None:
    created = client.post("/http-accounts", json=_body())
    assert created.status_code == 201, created.text
    _assert_secrets_absent(created.text)
    account = created.json()["http_account"]
    assert re.fullmatch(r"hac_[0-9a-f]{12}", account["id"])
    assert account["name"] == "Office API"
    assert account["auth"] == {"type": "bearer"}
    assert "token" not in account["auth"]
    assert "password" not in account["auth"]
    assert "username" not in account["auth"]
    assert account["headers"] == [{"name": "X-Api-Key"}]
    assert account["query"] == [{"name": "api_key"}, {"name": "api_key"}]
    assert account["allowed_origins"] == ["https://api.example.com:443"]
    assert "secret" not in account
    assert "value" not in created.text
    stored = get_http_account_store().get(account["id"])
    assert stored is not None
    assert stored.secret == TOKEN
    assert stored.headers == [("X-Api-Key", HEADER_VALUE)]
    assert stored.query == [("api_key", QUERY_VALUE), ("api_key", QUERY_VALUE_REPEAT)]
    _assert_audit("http_account.create", account["id"], "Office API")

    listed = client.get("/http-accounts", params={"q": "office"})
    assert listed.status_code == 200, listed.text
    _assert_secrets_absent(listed.text)
    body = listed.json()
    assert body["limit"] == 50
    assert {item["id"] for item in body["items"]} == {account["id"]}
    assert "http_account" not in body["items"][0]

    fetched = client.get(f"/http-accounts/{account['id']}")
    assert fetched.status_code == 200, fetched.text
    _assert_secrets_absent(fetched.text)
    assert fetched.json()["http_account"]["auth"] == {"type": "bearer"}


def test_omitted_auth_headers_and_origins_default_empty(client: TestClient) -> None:
    created = client.post("/http-accounts", json={"name": "Plain"})
    assert created.status_code == 201, created.text
    account = created.json()["http_account"]
    assert account["auth"] == {"type": "none"}
    assert account["headers"] == []
    assert account["query"] == []
    assert account["allowed_origins"] == []
    stored = get_http_account_store().get(account["id"])
    assert stored is not None
    assert stored.secret is None
    assert stored.auth_type == "none"


def test_basic_auth_returns_the_username_only(client: TestClient) -> None:
    created = client.post(
        "/http-accounts",
        json={
            "name": "Basic",
            "auth": {"type": "basic", "username": "alice", "password": PASSWORD},
        },
    )
    assert created.status_code == 201, created.text
    _assert_secrets_absent(created.text)
    assert created.json()["http_account"]["auth"] == {"type": "basic", "username": "alice"}
    stored = get_http_account_store().get(created.json()["http_account"]["id"])
    assert stored is not None
    assert stored.username == "alice"
    assert stored.secret == PASSWORD


def test_private_loopback_and_link_local_origins_are_kept(client: TestClient) -> None:
    created = client.post(
        "/http-accounts",
        json={
            "name": "Internal",
            "allowed_origins": [
                "http://10.1.2.3/",
                "http://127.0.0.1:8080",
                "http://[fe80::1]/",
                "https://api.example.com:8443",
            ],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["http_account"]["allowed_origins"] == [
        "http://10.1.2.3:80",
        "http://127.0.0.1:8080",
        "http://[fe80::1]:80",
        "https://api.example.com:8443",
    ]


def test_illegal_accounts_are_refused(client: TestClient) -> None:
    long_token = "t" * 4097
    long_password = "p" * 1025
    long_header = "h" * 4097
    long_query = "q" * 2049
    headers = [{"name": f"X-{index}", "value": "v"} for index in range(33)]
    refused_bodies = [
        _body(name=" "),
        _body(name="x" * 201),
        _body(auth={"type": "bearer"}),
        _body(auth={"type": "bearer", "token": ""}),
        _body(auth={"type": "bearer", "token": long_token}),
        _body(auth={"type": "bearer", "token": TOKEN, "password": PASSWORD}),
        _body(auth={"type": "basic", "username": "a:b", "password": PASSWORD}),
        _body(auth={"type": "basic", "username": "alice\n", "password": PASSWORD}),
        _body(auth={"type": "basic", "username": "", "password": PASSWORD}),
        _body(auth={"type": "basic", "username": "alice", "password": ""}),
        _body(auth={"type": "basic", "username": "alice", "password": long_password}),
        _body(auth={"type": "none", "token": TOKEN}),
        _body(headers=[{"name": "Not A Token", "value": HEADER_VALUE}]),
        _body(headers=[{"name": "X-Api-Key", "value": "line\nbreak"}]),
        _body(headers=[{"name": "X-Api-Key", "value": "line\rbreak"}]),
        _body(headers=[{"name": "X-Api-Key", "value": "nul\x00here"}]),
        _body(headers=[{"name": "X-Api-Key", "value": long_header}]),
        _body(headers=headers),
        _body(query=[{"name": "api_key", "value": long_query}]),
        _body(query=[{"name": long_query, "value": "v"}]),
        _body(allowed_origins=["https://api.example.com/v1"]),
        _body(allowed_origins=["https://api.example.com/?q=1"]),
        _body(allowed_origins=["https://user:secret@api.example.com/"]),
        _body(allowed_origins=["https://api.example.com/#frag"]),
        _body(allowed_origins=["ftp://api.example.com/"]),
        {"name": "Office", "url": "https://api.example.com/"},
    ]
    for name in _FORBIDDEN:
        refused_bodies.append(_body(headers=[{"name": name.upper(), "value": HEADER_VALUE}]))
    for body in refused_bodies:
        response = client.post("/http-accounts", json=body)
        assert_problem(response, status=422, code="REQUEST_INVALID")
        _assert_secrets_absent(response.text)
    assert _events("http_account.create") == []


def test_blank_secret_is_refused_and_an_omitted_secret_stays(client: TestClient) -> None:
    with pytest.raises(ChannelRequestInvalid):
        create_http_account(
            name="Empty",
            auth={"type": "bearer", "token": ""},
            headers=None,
            query=None,
            allowed_origins=None,
            actor_user_id="usr_test",
            actor_token_id=None,
        )
    account = _create(client, name="Keep me")
    stored_before = get_http_account_store().get(account["id"])
    assert stored_before is not None
    assert stored_before.secret == TOKEN
    assert stored_before.headers == [("X-Api-Key", HEADER_VALUE)]

    blank = client.patch(
        f"/http-accounts/{account['id']}",
        json={"auth": {"type": "bearer", "token": ""}},
    )
    assert_problem(blank, status=422, code="REQUEST_INVALID")
    with pytest.raises(ChannelRequestInvalid):
        update_http_account(
            account_id=account["id"],
            name=None,
            auth={"type": "bearer", "token": ""},
            auth_set=True,
            headers=None,
            headers_set=False,
            query=None,
            query_set=False,
            allowed_origins=None,
            origins_set=False,
            actor_user_id="usr_test",
            actor_token_id=None,
        )
    omitted = client.patch(f"/http-accounts/{account['id']}", json={"name": "Renamed"})
    assert omitted.status_code == 200, omitted.text
    _assert_secrets_absent(omitted.text)
    assert omitted.json()["http_account"]["name"] == "Renamed"
    assert omitted.json()["http_account"]["headers"] == [{"name": "X-Api-Key"}]
    assert omitted.json()["http_account"]["query"] == [
        {"name": "api_key"},
        {"name": "api_key"},
    ]
    assert omitted.json()["http_account"]["allowed_origins"] == ["https://api.example.com:443"]
    stored = get_http_account_store().get(account["id"])
    assert stored is not None
    assert stored.secret == TOKEN
    assert stored.headers == [("X-Api-Key", HEADER_VALUE)]
    assert stored.query == [("api_key", QUERY_VALUE), ("api_key", QUERY_VALUE_REPEAT)]
    _assert_audit("http_account.update", account["id"], "Renamed")

    cleared = client.patch(
        f"/http-accounts/{account['id']}",
        json={"auth": {"type": "none"}},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["http_account"]["auth"] == {"type": "none"}
    _assert_secrets_absent(cleared.text)
    stored_cleared = get_http_account_store().get(account["id"])
    assert stored_cleared is not None
    assert stored_cleared.secret is None
    assert stored_cleared.auth_type == "none"

    replaced = client.patch(
        f"/http-accounts/{account['id']}",
        json={
            "auth": {"type": "basic", "username": "bob", "password": PASSWORD},
            "headers": [{"name": "X-Tenant", "value": HEADER_VALUE}],
            "query": [],
            "allowed_origins": [],
        },
    )
    assert replaced.status_code == 200, replaced.text
    _assert_secrets_absent(replaced.text)
    body = replaced.json()["http_account"]
    assert body["auth"] == {"type": "basic", "username": "bob"}
    assert body["headers"] == [{"name": "X-Tenant"}]
    assert body["query"] == []
    assert body["allowed_origins"] == []
    stored_replaced = get_http_account_store().get(account["id"])
    assert stored_replaced is not None
    assert stored_replaced.secret == PASSWORD
    assert stored_replaced.headers == [("X-Tenant", HEADER_VALUE)]
    assert stored_replaced.query == []


def test_partial_update_rejects_a_bad_list_without_wiping_secrets(client: TestClient) -> None:
    account = _create(client)
    refused = client.patch(
        f"/http-accounts/{account['id']}",
        json={"headers": [{"name": "X-Api-Key", "value": "bad\nvalue"}]},
    )
    assert_problem(refused, status=422, code="REQUEST_INVALID")
    origin = client.patch(
        f"/http-accounts/{account['id']}",
        json={"allowed_origins": ["https://api.example.com/v1"]},
    )
    assert_problem(origin, status=422, code="REQUEST_INVALID")
    stored = get_http_account_store().get(account["id"])
    assert stored is not None
    assert stored.secret == TOKEN
    assert stored.headers == [("X-Api-Key", HEADER_VALUE)]
    assert stored.allowed_origins == ["https://api.example.com:443"]


def test_missing_account_is_not_found_and_writes_no_audit(client: TestClient) -> None:
    missing = client.get("/http-accounts/hac_missing0001")
    assert_problem(missing, status=404, code="HTTP_ACCOUNT_NOT_FOUND")
    before = _events("http_account.delete")
    deleted = client.delete("/http-accounts/hac_missing0001")
    assert_problem(deleted, status=404, code="HTTP_ACCOUNT_NOT_FOUND")
    assert _events("http_account.delete") == before
    probed = client.post("/http-accounts/hac_missing0001/test", json={})
    assert probed.status_code >= 400
    assert _events("http_account.test") == []


def test_delete_conflicts_for_a_draft_and_for_a_published_version(client: TestClient) -> None:
    draft_account = _create(client, name="Draft use")
    _plant(draft_account["id"], publish=False)
    before = _events("http_account.delete", draft_account["id"])
    refused = client.delete(f"/http-accounts/{draft_account['id']}")
    assert_problem(refused, status=409, code="HTTP_ACCOUNT_IN_USE")
    assert set(refused.json()) <= {"type", "status", "detail", "code", "request_id"}
    assert _events("http_account.delete", draft_account["id"]) == before
    assert client.get(f"/http-accounts/{draft_account['id']}").status_code == 200

    published_account = _create(client, name="Published use")
    channel_id = _plant(published_account["id"], publish=True)
    published_refused = client.delete(f"/http-accounts/{published_account['id']}")
    assert_problem(published_refused, status=409, code="HTTP_ACCOUNT_IN_USE")
    assert _events("http_account.delete", published_account["id"]) == []
    get_channel_store().delete(channel_id)
    deleted = client.delete(f"/http-accounts/{published_account['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    _assert_audit("http_account.delete", published_account["id"], "Published use")
    assert_problem(
        client.get(f"/http-accounts/{published_account['id']}"),
        status=404,
        code="HTTP_ACCOUNT_NOT_FOUND",
    )

    decoy = _create(client, name="Decoy")
    now = utc_now()
    get_channel_store().create(
        ChannelRecord(
            id=new_channel_id(),
            name="Other nodes",
            description=None,
            active=False,
            draft_graph={
                "nodes": [
                    {
                        "id": "nd_mail",
                        "type": "action.email",
                        "config": {"http_account_id": decoy["id"]},
                    },
                    {
                        "id": "nd_other",
                        "type": "action.http",
                        "config": {"http_account_id": "hac_someoneelse"},
                    },
                ],
                "edges": [],
                "settings": {},
            },
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    removed = client.delete(f"/http-accounts/{decoy['id']}")
    assert removed.status_code == 204


def test_list_orders_by_newest_name_search(client: TestClient) -> None:
    first = _create(client, name="order-batch one", auth={"type": "none"}, headers=[], query=[], allowed_origins=[])
    second = _create(client, name="order-batch two", auth={"type": "none"}, headers=[], query=[], allowed_origins=[])

    def _order_key(account_id: str) -> tuple[object, str]:
        stored = get_http_account_store().get(account_id)
        assert stored is not None
        return (stored.created_at, stored.id)

    newest, older = sorted((first, second), key=lambda item: _order_key(item["id"]), reverse=True)
    listed = client.get("/http-accounts", params={"q": "ORDER-batch", "limit": 1})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [newest["id"]]
    page = client.get("/http-accounts", params={"q": "order-batch", "limit": 10, "offset": 1})
    assert [item["id"] for item in page.json()["items"]] == [older["id"]]
    too_wide = client.get("/http-accounts", params={"limit": 201})
    assert_problem(too_wide, status=422, code="REQUEST_INVALID")


def test_channel_write_and_operator_cannot_use_the_catalog(client: TestClient) -> None:
    roles = get_role_store()
    operator = roles.get_by_key("operator")
    assert operator is not None
    author = create_role(
        roles,
        key="channel_author",
        name="Channel author",
        permissions=["console:access", "channel:write"],
    )
    reader = create_role(
        roles,
        key="http_reader",
        name="HTTP reader",
        permissions=["console:access", "http_account:read"],
    )
    get_user_store().create_user(
        account="http-op",
        display_name="HTTP Op",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    get_user_store().create_user(
        account="http-author",
        display_name="HTTP Author",
        password_hash=hash_password("secret"),
        role_id=author.id,
        status="active",
    )
    get_user_store().create_user(
        account="http-reader",
        display_name="HTTP Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )
    account = _create(client, name="Visible")

    logged = client.post("/auth/login", json={"account": "http-op", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/http-accounts").status_code == 403

    logged = client.post("/auth/login", json={"account": "http-author", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/http-accounts").status_code == 403
    assert client.post("/http-accounts", json={"name": "Nope"}).status_code == 403

    logged = client.post("/auth/login", json={"account": "http-reader", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/http-accounts").status_code == 200
    assert client.post("/http-accounts", json={"name": "Nope"}).status_code == 403
    assert client.patch(f"/http-accounts/{account['id']}", json={"name": "Nope"}).status_code == 403
    assert client.delete(f"/http-accounts/{account['id']}").status_code == 403


def _plant(account_id: str, *, publish: bool) -> str:
    now = utc_now()
    graph = {
        "nodes": [
            {
                "id": "nd_http",
                "type": "action.http",
                "config": {"http_account_id": account_id},
            }
        ],
        "edges": [],
        "settings": {},
    }
    channel = get_channel_store().create(
        ChannelRecord(
            id=new_channel_id(),
            name="Uses http",
            description=None,
            active=False,
            draft_graph=graph,
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    if publish:
        get_channel_store().publish_version(
            channel.id,
            draft_revision=1,
            published_at=now,
            published_by_user_id="usr_test",
        )
        get_channel_store().replace_draft(
            channel.id,
            base_revision=1,
            graph={"nodes": [], "edges": [], "settings": {}},
            now=now,
        )
    return channel.id
