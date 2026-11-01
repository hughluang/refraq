"""Inbound Credential catalog API."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.permissions import ALL_PERMISSIONS  # noqa: E402
from backend.admin.roles import create_role, effective_permissions, seed_roles  # noqa: E402
from backend.channel.ids import new_channel_id  # noqa: E402
from backend.channel.inbound_credentials import (  # noqa: E402
    get_inbound_credential_store,
    reset_inbound_credential_store,
)
from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.store import ChannelRecord, get_channel_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402

TOKEN_SECRET = "token-secret-9f3a"
HMAC_SECRET = "hmac-secret-9f3a"
SECRETS = (TOKEN_SECRET, HMAC_SECRET)


@pytest.fixture()
def client() -> TestClient:
    reset_inbound_credential_store()
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


def _assert_secret_hidden(payload: object, text: str) -> None:
    for secret in SECRETS:
        assert secret not in text
    _assert_no_secret_fields(payload)


def _events(action: str, resource_id: str | None = None) -> list:
    events, _cursor = get_audit_store().list_events(
        resource_type="inbound_credential", action=action, limit=50
    )
    if resource_id is None:
        return events
    return [event for event in events if event.resource_id == resource_id]


def _assert_audit(action: str, resource_id: str, name: str, credential_type: str) -> dict:
    events = _events(action, resource_id)
    assert len(events) == 1
    event = events[0]
    assert event.resource_type == "inbound_credential"
    assert event.result == "success"
    assert event.detail["name"] == name
    assert event.detail["type"] == credential_type
    _assert_no_secret_fields(event.detail)
    for secret in SECRETS:
        assert secret not in json.dumps(event.detail)
    return event.detail


def _assert_no_secret_fields(payload: object) -> None:
    if isinstance(payload, dict):
        assert "secret" not in payload
        assert "value" not in payload
        for child in payload.values():
            _assert_no_secret_fields(child)
    elif isinstance(payload, list):
        for child in payload:
            _assert_no_secret_fields(child)


def test_create_token_and_hmac_hides_the_secret(client: TestClient) -> None:
    created = client.post(
        "/inbound-credentials",
        json={
            "name": "  Partner hook  ",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "header", "name": "X-Hook-Token"},
        },
    )
    assert created.status_code == 201, created.text
    _assert_secret_hidden(created.json(), created.text)
    credential = created.json()["inbound_credential"]
    assert re.fullmatch(r"icr_[0-9a-f]{12}", credential["id"])
    assert credential["name"] == "Partner hook"
    assert credential["type"] == "token"
    assert credential["config"] == {"location": "header", "name": "X-Hook-Token"}
    stored = get_inbound_credential_store().get(credential["id"])
    assert stored is not None
    assert stored.secret == TOKEN_SECRET

    query_token = client.post(
        "/inbound-credentials",
        json={
            "name": "Query token",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "query", "name": "access_token"},
        },
    )
    assert query_token.status_code == 201, query_token.text
    _assert_secret_hidden(query_token.json(), query_token.text)
    assert query_token.json()["inbound_credential"]["config"] == {
        "location": "query",
        "name": "access_token",
    }

    signed = client.post(
        "/inbound-credentials",
        json={
            "name": "Signed hook",
            "type": "hmac_sha256",
            "secret": HMAC_SECRET,
            "config": {
                "signature_header": "X-Hub-Signature-256",
                "encoding": "hex",
                "prefix": "sha256=",
                "timestamp_header": "X-Timestamp",
            },
        },
    )
    assert signed.status_code == 201, signed.text
    _assert_secret_hidden(signed.json(), signed.text)
    hmac = signed.json()["inbound_credential"]
    assert re.fullmatch(r"icr_[0-9a-f]{12}", hmac["id"])
    assert hmac["type"] == "hmac_sha256"
    assert hmac["config"] == {
        "signature_header": "X-Hub-Signature-256",
        "encoding": "hex",
        "prefix": "sha256=",
        "timestamp_header": "X-Timestamp",
    }
    stored_hmac = get_inbound_credential_store().get(hmac["id"])
    assert stored_hmac is not None
    assert stored_hmac.secret == HMAC_SECRET

    plain = client.post(
        "/inbound-credentials",
        json={
            "name": "Plain signature",
            "type": "hmac_sha256",
            "secret": HMAC_SECRET,
            "config": {"signature_header": "X-Signature", "encoding": "base64"},
        },
    )
    assert plain.status_code == 201, plain.text
    _assert_secret_hidden(plain.json(), plain.text)
    assert plain.json()["inbound_credential"]["config"] == {
        "signature_header": "X-Signature",
        "encoding": "base64",
    }
    optional_null = client.post(
        "/inbound-credentials",
        json={
            "name": "Null optionals",
            "type": "hmac_sha256",
            "secret": HMAC_SECRET,
            "config": {
                "signature_header": "X-Signature",
                "encoding": "hex",
                "prefix": None,
                "timestamp_header": None,
            },
        },
    )
    assert optional_null.status_code == 201, optional_null.text
    _assert_secret_hidden(optional_null.json(), optional_null.text)
    assert optional_null.json()["inbound_credential"]["config"] == {
        "signature_header": "X-Signature",
        "encoding": "hex",
    }

    listed = client.get("/inbound-credentials")
    assert listed.status_code == 200, listed.text
    _assert_secret_hidden(listed.json(), listed.text)
    body = listed.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert {item["id"] for item in body["items"]} == {
        credential["id"],
        query_token.json()["inbound_credential"]["id"],
        hmac["id"],
        plain.json()["inbound_credential"]["id"],
        optional_null.json()["inbound_credential"]["id"],
    }
    assert "inbound_credential" not in body["items"][0]

    fetched = client.get(f"/inbound-credentials/{credential['id']}")
    assert fetched.status_code == 200, fetched.text
    _assert_secret_hidden(fetched.json(), fetched.text)
    assert fetched.json()["inbound_credential"]["config"] == {
        "location": "header",
        "name": "X-Hook-Token",
    }
    assert json.dumps(fetched.json()).find(TOKEN_SECRET) == -1


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw) -> str:  # noqa: ANN001
    return "JSON"


@contextmanager
def _sqlite_inbound() -> Iterator[object]:
    from backend.channel import inbound_credentials as inbound_module
    from backend.channel.models import InboundCredentialRow
    from backend.core.db import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine, tables=[InboundCredentialRow.__table__])

    @contextmanager
    def session_scope() -> Iterator[Session]:
        session = Session(engine, autoflush=False, autocommit=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    previous = inbound_module.session_scope
    inbound_module.session_scope = session_scope
    try:
        yield session_scope
    finally:
        inbound_module.session_scope = previous
        engine.dispose()


def test_illegal_credentials_are_refused(client: TestClient) -> None:
    long_secret = "s" * 4097
    long_name = "n" * 201
    refused_bodies: list[dict[str, object]] = [
        {"name": " ", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token"}},
        {"name": long_name, "type": "token", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token"}},
        {"name": "Missing type", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token"}},
        {"name": "Bad type", "type": "basic", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token"}},
        {"name": "Blank", "type": "token", "secret": "", "config": {"location": "header", "name": "X-Token"}},
        {"name": "Spaces", "type": "token", "secret": "   ", "config": {"location": "header", "name": "X-Token"}},
        {"name": "Long", "type": "token", "secret": long_secret, "config": {"location": "header", "name": "X-Token"}},
        {"name": "No config", "type": "token", "secret": TOKEN_SECRET},
        {"name": "Cookie", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "cookie", "name": "X-Token"}},
        {"name": "Bad header", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "Not A Token"}},
        {"name": "Empty query", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "query", "name": ""}},
        {"name": "Secret field", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token", "value": TOKEN_SECRET}},
        {"name": "Hmac fields", "type": "token", "secret": TOKEN_SECRET, "config": {"signature_header": "X-Signature", "encoding": "hex"}},
        {"name": "Bad encoding", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"signature_header": "X-Signature", "encoding": "raw"}},
        {"name": "Bad header", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"signature_header": "Not A Token", "encoding": "hex"}},
        {"name": "Empty prefix", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"signature_header": "X-Signature", "encoding": "hex", "prefix": ""}},
        {"name": "Blank prefix", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"signature_header": "X-Signature", "encoding": "hex", "prefix": "  "}},
        {"name": "Bad time", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"signature_header": "X-Signature", "encoding": "base64", "timestamp_header": "Not A Token"}},
        {"name": "Token fields", "type": "hmac_sha256", "secret": HMAC_SECRET, "config": {"location": "header", "name": "X-Token"}},
        {"name": "Extra", "type": "token", "secret": TOKEN_SECRET, "config": {"location": "header", "name": "X-Token"}, "value": TOKEN_SECRET},
    ]
    for body in refused_bodies:
        response = client.post("/inbound-credentials", json=body)
        assert_problem(response, status=422, code="REQUEST_INVALID")
        for secret in SECRETS:
            assert secret not in response.text
    listed = client.get("/inbound-credentials")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 0


def test_memory_and_sql_stores_persist_ciphertext(client: TestClient) -> None:
    from backend.core.secrets import decrypt_secret

    created = client.post(
        "/inbound-credentials",
        json={
            "name": "Sealed",
            "type": "hmac_sha256",
            "secret": HMAC_SECRET,
            "config": {
                "signature_header": "X-Signature",
                "encoding": "hex",
                "prefix": "sha256=",
                "timestamp_header": "X-Timestamp",
            },
        },
    )
    assert created.status_code == 201, created.text
    credential_id = created.json()["inbound_credential"]["id"]
    sealed = get_inbound_credential_store()._rows[credential_id]
    assert sealed.secret_ciphertext != HMAC_SECRET
    assert HMAC_SECRET not in sealed.secret_ciphertext
    assert decrypt_secret(sealed.secret_ciphertext) == HMAC_SECRET
    assert sealed.config == {
        "signature_header": "X-Signature",
        "encoding": "hex",
        "prefix": "sha256=",
        "timestamp_header": "X-Timestamp",
    }
    assert HMAC_SECRET not in json.dumps(sealed.config)
    opened = get_inbound_credential_store().get(credential_id)
    assert opened is not None
    assert opened.secret == HMAC_SECRET

    from backend.channel.inbound_credentials import (
        InboundCredentialRecord,
        SqlInboundCredentialStore,
    )
    from backend.channel.models import InboundCredentialRow
    from backend.core.time import utc_now

    now = utc_now()
    record = InboundCredentialRecord(
        id="icr_sqlseal0001",
        name="SQL seal",
        credential_type="hmac_sha256",
        config={
            "signature_header": "X-Signature",
            "encoding": "base64",
            "prefix": "sha256=",
            "timestamp_header": "X-Timestamp",
        },
        secret=HMAC_SECRET,
        created_at=now,
        updated_at=now,
    )
    with _sqlite_inbound() as session_scope:
        saved = SqlInboundCredentialStore().create(record)
        assert saved.secret == HMAC_SECRET
        with session_scope() as session:
            row = session.get(InboundCredentialRow, record.id)
            assert row is not None
            assert row.secret_ciphertext != HMAC_SECRET
            assert HMAC_SECRET not in row.secret_ciphertext
            assert decrypt_secret(row.secret_ciphertext) == HMAC_SECRET
            assert row.config["prefix"] == "sha256="
            assert row.config["timestamp_header"] == "X-Timestamp"
            assert HMAC_SECRET not in json.dumps(row.config)
        again = SqlInboundCredentialStore().get(record.id)
        assert again is not None
        assert again.secret == HMAC_SECRET


def test_patch_omits_a_blank_or_invalid_secret_and_keeps_the_stored_one(
    client: TestClient,
) -> None:
    from backend.channel.errors import ChannelRequestInvalid
    from backend.channel.inbound_credentials import update_inbound_credential

    created = client.post(
        "/inbound-credentials",
        json={
            "name": "Keep me",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "header", "name": "X-Hook-Token"},
        },
    )
    assert created.status_code == 201, created.text
    credential = created.json()["inbound_credential"]
    credential_id = credential["id"]

    renamed = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={"name": "Renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    _assert_secret_hidden(renamed.json(), renamed.text)
    assert renamed.json()["inbound_credential"]["name"] == "Renamed"
    assert renamed.json()["inbound_credential"]["config"] == {
        "location": "header",
        "name": "X-Hook-Token",
    }
    assert get_inbound_credential_store().get(credential_id).secret == TOKEN_SECRET

    for body in (
        {"secret": ""},
        {"secret": "   "},
        {"secret": None},
        {"config": None},
        {"type": None},
        {
            "secret": "wiped-secret-9f3a",
            "config": {"location": "cookie", "name": "X-Hook-Token"},
        },
        {"type": "hmac_sha256"},
    ):
        refused = client.patch(f"/inbound-credentials/{credential_id}", json=body)
        assert_problem(refused, status=422, code="REQUEST_INVALID")
        assert TOKEN_SECRET not in refused.text
        assert "wiped-secret-9f3a" not in refused.text
        assert get_inbound_credential_store().get(credential_id).secret == TOKEN_SECRET

    with pytest.raises(ChannelRequestInvalid):
        update_inbound_credential(
            credential_id=credential_id,
            name=None,
            credential_type=None,
            type_set=False,
            secret="",
            secret_set=True,
            config=None,
            config_set=False,
        )
    assert get_inbound_credential_store().get(credential_id).secret == TOKEN_SECRET

    moved = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={"config": {"location": "query", "name": "access_token"}},
    )
    assert moved.status_code == 200, moved.text
    _assert_secret_hidden(moved.json(), moved.text)
    assert moved.json()["inbound_credential"]["config"] == {
        "location": "query",
        "name": "access_token",
    }
    assert get_inbound_credential_store().get(credential_id).secret == TOKEN_SECRET

    switched = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={
            "type": "hmac_sha256",
            "config": {"signature_header": "X-Signature", "encoding": "hex", "prefix": "sha256="},
        },
    )
    assert switched.status_code == 200, switched.text
    _assert_secret_hidden(switched.json(), switched.text)
    assert switched.json()["inbound_credential"]["type"] == "hmac_sha256"
    assert switched.json()["inbound_credential"]["config"] == {
        "signature_header": "X-Signature",
        "encoding": "hex",
        "prefix": "sha256=",
    }
    assert get_inbound_credential_store().get(credential_id).secret == TOKEN_SECRET

    replaced = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={"secret": "next-secret-9f3a"},
    )
    assert replaced.status_code == 200, replaced.text
    assert "next-secret-9f3a" not in replaced.text
    _assert_no_secret_fields(replaced.json())
    assert get_inbound_credential_store().get(credential_id).secret == "next-secret-9f3a"
    from backend.core.secrets import decrypt_secret

    sealed = get_inbound_credential_store()._rows[credential_id]
    assert "next-secret-9f3a" not in sealed.secret_ciphertext
    assert decrypt_secret(sealed.secret_ciphertext) == "next-secret-9f3a"


def test_list_is_newest_first_and_name_search_is_case_insensitive(client: TestClient) -> None:
    first = client.post(
        "/inbound-credentials",
        json={
            "name": "order-batch one",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "header", "name": "X-One"},
        },
    )
    second = client.post(
        "/inbound-credentials",
        json={
            "name": "order-batch two",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "query", "name": "two"},
        },
    )
    percent = client.post(
        "/inbound-credentials",
        json={
            "name": "100% done",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "header", "name": "X-Pct"},
        },
    )
    assert first.status_code == 201 and second.status_code == 201 and percent.status_code == 201

    def _order_key(credential_id: str) -> tuple[object, str]:
        stored = get_inbound_credential_store().get(credential_id)
        assert stored is not None
        return (stored.created_at, stored.id)

    newest, older = sorted(
        (first.json()["inbound_credential"], second.json()["inbound_credential"]),
        key=lambda item: _order_key(item["id"]),
        reverse=True,
    )
    listed = client.get("/inbound-credentials", params={"q": "ORDER-batch", "limit": 1})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [newest["id"]]
    _assert_secret_hidden(body, listed.text)
    page = client.get("/inbound-credentials", params={"q": "order-batch", "limit": 10, "offset": 1})
    assert [item["id"] for item in page.json()["items"]] == [older["id"]]
    assert page.json()["offset"] == 1
    blank = client.get("/inbound-credentials", params={"q": "   "})
    assert blank.status_code == 200, blank.text
    assert blank.json()["total"] == 3
    found = client.get("/inbound-credentials", params={"q": "100%"})
    assert [item["id"] for item in found.json()["items"]] == [
        percent.json()["inbound_credential"]["id"]
    ]
    missed = client.get("/inbound-credentials", params={"q": "100X"})
    assert missed.json()["items"] == []
    assert missed.json()["total"] == 0
    too_wide = client.get("/inbound-credentials", params={"limit": 201})
    assert_problem(too_wide, status=422, code="REQUEST_INVALID")


def test_create_and_update_write_one_audit_event_without_the_secret(client: TestClient) -> None:
    created = client.post(
        "/inbound-credentials",
        json={
            "name": "Partner hook",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "header", "name": "X-Hook-Token"},
        },
    )
    assert created.status_code == 201, created.text
    credential_id = created.json()["inbound_credential"]["id"]
    detail = _assert_audit("inbound_credential.create", credential_id, "Partner hook", "token")
    assert detail["config"] == {"location": "header", "name": "X-Hook-Token"}

    updated = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={
            "name": "Signed hook",
            "type": "hmac_sha256",
            "config": {
                "signature_header": "X-Signature",
                "encoding": "hex",
                "prefix": "sha256=",
                "timestamp_header": "X-Timestamp",
            },
        },
    )
    assert updated.status_code == 200, updated.text
    detail = _assert_audit("inbound_credential.update", credential_id, "Signed hook", "hmac_sha256")
    assert detail["config"] == {
        "signature_header": "X-Signature",
        "encoding": "hex",
        "prefix": "sha256=",
        "timestamp_header": "X-Timestamp",
    }
    assert _events("inbound_credential.create", credential_id) != []
    assert len(_events("inbound_credential.update", credential_id)) == 1

    before_create = _events("inbound_credential.create")
    before_update = _events("inbound_credential.update")
    refused = client.post(
        "/inbound-credentials",
        json={
            "name": "Bad",
            "type": "token",
            "secret": TOKEN_SECRET,
            "config": {"location": "cookie", "name": "X-Token"},
        },
    )
    assert_problem(refused, status=422, code="REQUEST_INVALID")
    bad_patch = client.patch(
        f"/inbound-credentials/{credential_id}",
        json={"secret": "   "},
    )
    assert_problem(bad_patch, status=422, code="REQUEST_INVALID")
    missing = client.patch("/inbound-credentials/icr_missing0001", json={"name": "Nope"})
    assert_problem(missing, status=404, code="INBOUND_CREDENTIAL_NOT_FOUND")
    assert _events("inbound_credential.create") == before_create
    assert _events("inbound_credential.update") == before_update


def test_delete_conflicts_while_a_draft_or_published_version_names_it(client: TestClient) -> None:
    draft = _create(client, name="Draft use")
    _plant(draft["id"], publish=False)
    before = _events("inbound_credential.delete", draft["id"])
    refused = client.delete(f"/inbound-credentials/{draft['id']}")
    assert_problem(refused, status=409, code="INBOUND_CREDENTIAL_IN_USE")
    assert set(refused.json()) <= {"type", "status", "detail", "code", "request_id"}
    assert _events("inbound_credential.delete", draft["id"]) == before
    assert client.get(f"/inbound-credentials/{draft['id']}").status_code == 200

    published = _create(client, name="Published use")
    channel_id = _plant(published["id"], publish=True)
    published_refused = client.delete(f"/inbound-credentials/{published['id']}")
    assert_problem(published_refused, status=409, code="INBOUND_CREDENTIAL_IN_USE")
    assert _events("inbound_credential.delete", published["id"]) == []
    get_channel_store().delete(channel_id)

    older = _create(client, name="Older version")
    older_channel = _plant(older["id"], publish=True)
    now = utc_now()
    get_channel_store().publish_version(
        older_channel,
        draft_revision=2,
        published_at=now,
        published_by_user_id="usr_test",
    )
    older_refused = client.delete(f"/inbound-credentials/{older['id']}")
    assert_problem(older_refused, status=409, code="INBOUND_CREDENTIAL_IN_USE")
    assert _events("inbound_credential.delete", older["id"]) == []
    get_channel_store().delete(older_channel)

    deleted = client.delete(f"/inbound-credentials/{published['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    _assert_audit("inbound_credential.delete", published["id"], "Published use", "token")
    assert_problem(
        client.get(f"/inbound-credentials/{published['id']}"),
        status=404,
        code="INBOUND_CREDENTIAL_NOT_FOUND",
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
                        "id": "nd_http",
                        "type": "action.http",
                        "config": {"credential_id": decoy["id"]},
                    },
                    {
                        "id": "nd_loose",
                        "type": "trigger.inbound",
                        "credential_id": decoy["id"],
                        "config": {},
                    },
                    {
                        "id": "nd_other",
                        "type": "trigger.inbound",
                        "config": {"credential_id": "icr_someoneelse"},
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
    removed = client.delete(f"/inbound-credentials/{decoy['id']}")
    assert removed.status_code == 204
    assert removed.content == b""


def test_unknown_credential_is_not_found_and_writes_no_audit(client: TestClient) -> None:
    missing = client.get("/inbound-credentials/icr_missing0001")
    assert_problem(missing, status=404, code="INBOUND_CREDENTIAL_NOT_FOUND")
    before = _events("inbound_credential.delete")
    deleted = client.delete("/inbound-credentials/icr_missing0001")
    assert_problem(deleted, status=404, code="INBOUND_CREDENTIAL_NOT_FOUND")
    assert _events("inbound_credential.delete") == before
    patched = client.patch("/inbound-credentials/icr_missing0001", json={"name": "Nope"})
    assert_problem(patched, status=404, code="INBOUND_CREDENTIAL_NOT_FOUND")
    assert _events("inbound_credential.update") == []


def test_permissions_are_catalog_keys_and_not_operator_defaults() -> None:
    assert "inbound_credential:read" in ALL_PERMISSIONS
    assert "inbound_credential:write" in ALL_PERMISSIONS
    roles = get_role_store()
    seed_roles(roles)
    operator = roles.get_by_key("operator")
    assert operator is not None
    assert "inbound_credential:read" not in effective_permissions(operator)
    assert "inbound_credential:write" not in effective_permissions(operator)
    assert "channel:write" not in effective_permissions(operator)


def test_channel_write_and_operator_cannot_use_the_catalog(client: TestClient) -> None:
    roles = get_role_store()
    operator = roles.get_by_key("operator")
    assert operator is not None
    author = create_role(
        roles,
        key="channel_author_inbound",
        name="Channel author",
        permissions=["console:access", "channel:write"],
    )
    reader = create_role(
        roles,
        key="inbound_reader",
        name="Inbound reader",
        permissions=["console:access", "inbound_credential:read"],
    )
    get_user_store().create_user(
        account="in-op",
        display_name="Inbound Op",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    get_user_store().create_user(
        account="in-author",
        display_name="Inbound Author",
        password_hash=hash_password("secret"),
        role_id=author.id,
        status="active",
    )
    get_user_store().create_user(
        account="in-reader",
        display_name="Inbound Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )
    credential = _create(client, name="Visible")

    logged = client.post("/auth/login", json={"account": "in-op", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/inbound-credentials").status_code == 403
    assert client.post("/inbound-credentials", json=_token_body("Nope")).status_code == 403

    logged = client.post("/auth/login", json={"account": "in-author", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/inbound-credentials").status_code == 403
    assert client.post("/inbound-credentials", json=_token_body("Nope")).status_code == 403
    assert client.delete(f"/inbound-credentials/{credential['id']}").status_code == 403

    logged = client.post("/auth/login", json={"account": "in-reader", "password": "secret"})
    assert logged.status_code == 200, logged.text
    assert client.get("/inbound-credentials").status_code == 200
    fetched = client.get(f"/inbound-credentials/{credential['id']}")
    assert fetched.status_code == 200, fetched.text
    _assert_secret_hidden(fetched.json(), fetched.text)
    assert client.post("/inbound-credentials", json=_token_body("Nope")).status_code == 403
    assert client.patch(
        f"/inbound-credentials/{credential['id']}", json={"name": "Nope"}
    ).status_code == 403
    assert client.delete(f"/inbound-credentials/{credential['id']}").status_code == 403
    assert client.get(f"/inbound-credentials/{credential['id']}").status_code == 200


def test_sql_list_orders_newest_first_and_searches_literally() -> None:
    from datetime import datetime, timezone

    from backend.channel.inbound_credentials import (
        InboundCredentialRecord,
        SqlInboundCredentialStore,
    )

    older = InboundCredentialRecord(
        id="icr_aaaaaaaaaaa1",
        name="order-batch one",
        credential_type="token",
        config={"location": "header", "name": "X-One"},
        secret=TOKEN_SECRET,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    newer = InboundCredentialRecord(
        id="icr_bbbbbbbbbbb2",
        name="100% done",
        credential_type="hmac_sha256",
        config={"signature_header": "X-Signature", "encoding": "hex"},
        secret=HMAC_SECRET,
        created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
    )
    with _sqlite_inbound():
        store = SqlInboundCredentialStore()
        store.create(older)
        store.create(newer)
        page, total = store.list_credentials(q="ORDER-batch", limit=10, offset=0)
        assert total == 1
        assert page[0].id == older.id
        assert page[0].secret == TOKEN_SECRET
        found, total = store.list_credentials(q="100%", limit=1, offset=0)
        assert total == 1
        assert found[0].id == newer.id
        assert found[0].secret == HMAC_SECRET
        missed, total = store.list_credentials(q="100X", limit=10, offset=0)
        assert total == 0
        assert missed == []
        newest, total = store.list_credentials(q=None, limit=1, offset=0)
        assert total == 2
        assert newest[0].id == newer.id
        rest, total = store.list_credentials(q=None, limit=10, offset=1)
        assert total == 2
        assert [item.id for item in rest] == [older.id]


def _token_body(name: str) -> dict[str, object]:
    return {
        "name": name,
        "type": "token",
        "secret": TOKEN_SECRET,
        "config": {"location": "header", "name": "X-Hook-Token"},
    }


def _create(client: TestClient, **overrides: object) -> dict:
    body = _token_body("Partner hook")
    body.update(overrides)
    created = client.post("/inbound-credentials", json=body)
    assert created.status_code == 201, created.text
    return created.json()["inbound_credential"]


def _plant(credential_id: str, *, publish: bool) -> str:
    now = utc_now()
    graph = {
        "nodes": [
            {
                "id": "nd_in",
                "type": "trigger.inbound",
                "config": {"credential_id": credential_id},
            }
        ],
        "edges": [],
        "settings": {},
    }
    channel = get_channel_store().create(
        ChannelRecord(
            id=new_channel_id(),
            name="Uses inbound",
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
