"""Source HTTP list and lifecycle under Source Access (memory backend)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.source_access import (  # noqa: E402
    EVERY_SOURCE_TARGET,
    create_membership,
    list_memberships,
    reset_source_access_store,
)
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)

_PASSWORD = "kept-secret"
_HOST = "db.hidden.example"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_source_store()
    reset_source_access_store()
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    create_role(
        roles,
        key="source_reader",
        name="Source reader",
        permissions=["console:access", "sources:read"],
    )
    create_role(
        roles,
        key="source_writer",
        name="Source writer",
        permissions=[
            "console:access",
            "sources:read",
            "sources:write",
            "audit:read",
        ],
    )
    create_role(
        roles,
        key="source_access",
        name="Source access manager",
        permissions=["console:access", "sources:access_manage"],
    )
    create_role(
        roles,
        key="source_curator",
        name="Source curator",
        permissions=["console:access", "sources:read", "sources:access_manage"],
    )
    users = get_user_store()
    for account, role_key in (
        ("admin", "super_admin"),
        ("reader", "source_reader"),
        ("writer", "source_writer"),
        ("grantor", "source_access"),
        ("curator", "source_curator"),
    ):
        role = roles.get_by_key(role_key)
        assert role is not None
        users.create_user(
            account=account,
            display_name=account,
            password_hash=hash_password("secret"),
            role_id=role.id,
            status="active",
        )
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, account: str) -> None:
    resp = client.post("/auth/login", json={"account": account, "password": "secret"})
    assert resp.status_code == 200, resp.text


def _user_id(account: str) -> str:
    user = get_user_store().get_by_account(account)
    assert user is not None
    return user.id


def _access(host: str = _HOST, password: str = _PASSWORD) -> dict:
    return {
        "host": host,
        "port": 5432,
        "username": "u",
        "password": password,
        "ssl_mode": "require",
        "database": "MES",
        "schema": "public",
        "extra": {},
    }


def _create(
    client: TestClient,
    key: str,
    *,
    host: str = _HOST,
    description: str | None = None,
) -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "description": description,
            "engine": "postgresql",
            "access": _access(host=host),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


def _patch_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    class OkConnector:
        engine = "postgresql"

        def test_connection(self, endpoint) -> None:  # noqa: ANN001
            return None

        def collect_structure(self, endpoint, progress=None):  # noqa: ANN001
            raise AssertionError("not used")

    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: OkConnector(),
    )


def _assert_not_found(resp) -> None:  # noqa: ANN001
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == "SOURCE_NOT_FOUND"
    assert _HOST not in resp.text
    assert _PASSWORD not in resp.text


def _assert_forbidden(resp) -> None:  # noqa: ANN001
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "AUTH_FORBIDDEN"
    assert _PASSWORD not in resp.text


def test_list_is_empty_when_the_caller_has_no_level(client: TestClient) -> None:
    _login(client, "admin")
    _create(client, "alpha")
    _create(client, "beta")

    _login(client, "reader")
    listed = client.get("/sources")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["items"] == []
    assert body["total"] == 0

    _login(client, "admin")
    assert client.get("/sources").json()["total"] == 2


def test_list_filters_before_pagination(client: TestClient) -> None:
    _login(client, "admin")
    created = [_create(client, key) for key in ("aaa", "bbb", "ccc")]
    visible = {created[1]["id"], created[2]["id"]}
    for source_id in visible:
        create_membership(
            subject_type="user",
            subject_id=_user_id("reader"),
            target=source_id,
            level="viewer",
        )

    _login(client, "reader")
    page = client.get("/sources", params={"limit": 1, "offset": 0})
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] in visible
    assert body["items"][0]["key"] == "bbb"
    rest = client.get("/sources", params={"limit": 1, "offset": 1})
    assert {body["items"][0]["id"], rest.json()["items"][0]["id"]} == visible
    hidden = client.get("/sources", params={"q": "aaa"})
    assert hidden.json()["items"] == []
    assert hidden.json()["total"] == 0


def test_access_manage_lists_identity_rows_without_opening_one_source(
    client: TestClient,
) -> None:
    _login(client, "admin")
    alpha = _create(
        client, "alpha", host="alpha.hidden.example", description="alpha notes"
    )
    beta = _create(
        client, "beta", host="beta.hidden.example", description="beta notes"
    )
    create_membership(
        subject_type="user",
        subject_id=_user_id("curator"),
        target=alpha["id"],
        level="viewer",
    )

    _login(client, "curator")
    listed = client.get("/sources", params={"limit": 1, "offset": 0})
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 2
    first = listed.json()["items"][0]
    assert first["key"] == "alpha"
    assert first["locator_key"]
    assert first["description"] == "alpha notes"
    assert first["access"]["host"] == "alpha.hidden.example"
    assert first["has_access"] is True
    assert first["access_updated_at"]
    assert "password" not in first["access"]

    second = client.get("/sources", params={"limit": 1, "offset": 1}).json()["items"][0]
    assert second["key"] == "beta"
    assert second["name"] == "beta"
    assert second["kind"] == "database"
    assert second["engine"] == "postgresql"
    assert second["status"] == "active"
    assert second["id"] == beta["id"]
    assert set(second) == {"id", "key", "name", "kind", "engine", "status"}
    assert "access" not in second
    assert "has_access" not in second
    assert "access_updated_at" not in second
    assert "beta.hidden.example" not in str(second)
    assert _PASSWORD not in str(second)

    opened = client.get(f"/sources/{alpha['id']}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["source"]["access"]["host"] == "alpha.hidden.example"
    hidden = client.get(f"/sources/{beta['id']}")
    assert hidden.status_code == 404, hidden.text
    assert hidden.json()["code"] == "SOURCE_NOT_FOUND"


def test_access_manage_without_sources_read_lists_identity_only(
    client: TestClient,
) -> None:
    _login(client, "admin")
    source = _create(client, "named", description="hidden notes")

    _login(client, "grantor")
    listed = client.get("/sources")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    item = listed.json()["items"][0]
    assert item["id"] == source["id"]
    assert item["key"] == "named"
    assert set(item) == {"id", "key", "name", "kind", "engine", "status"}
    assert "access" not in item
    assert "has_access" not in item
    assert _HOST not in str(item)

    denied = client.get(f"/sources/{source['id']}")
    _assert_forbidden(denied)
    schema = client.get("/sources/access-schema/postgresql")
    _assert_forbidden(schema)
    draft = client.post(
        "/sources/test",
        json={"engine": "postgresql", "access": _access()},
    )
    _assert_forbidden(draft)


def test_no_level_matches_an_unknown_source(client: TestClient) -> None:
    _login(client, "admin")
    source = _create(client, "hidden-mes")
    _login(client, "writer")

    _assert_not_found(client.get(f"/sources/{source['id']}"))
    _assert_not_found(client.get(f"/sources/{source['id']}/access"))
    _assert_not_found(client.patch(f"/sources/{source['id']}", json={"name": "nope"}))
    _assert_not_found(client.post(f"/sources/{source['id']}/test", json={}))
    deleted = client.delete(f"/sources/{source['id']}")
    _assert_not_found(deleted)
    assert deleted.json()["code"] != "SOURCE_NOT_DISABLED"

    _login(client, "admin")
    disabled = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200, disabled.text
    _login(client, "writer")
    _assert_not_found(client.delete(f"/sources/{source['id']}"))
    _assert_not_found(client.get("/sources/src_missing"))


def test_missing_access_blob_is_checked_after_the_level(
    client: TestClient,
) -> None:
    now = utc_now()
    bare = get_source_store().create_source(
        SourceRecord(
            id="src_bare",
            key="bare",
            locator_key="src/postgresql/bare",
            name="Bare",
            kind="database",
            status="disabled",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    _login(client, "writer")
    _assert_not_found(client.get(f"/sources/{bare.id}/access"))
    _assert_not_found(client.delete(f"/sources/{bare.id}"))

    create_membership(
        subject_type="user",
        subject_id=_user_id("writer"),
        target=bare.id,
        level="maintainer",
    )
    missing = client.get(f"/sources/{bare.id}/access")
    assert missing.status_code == 400, missing.text
    assert missing.json()["code"] == "SOURCE_ACCESS_REQUIRED"


@pytest.mark.parametrize("level", ["viewer", "steward"])
def test_weaker_level_cannot_mutate_or_read_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    _patch_probe(monkeypatch)
    _login(client, "admin")
    source = _create(client, f"src-{level}")
    create_membership(
        subject_type="user",
        subject_id=_user_id("writer"),
        target=source["id"],
        level=level,
    )
    _login(client, "writer")

    shown = client.get(f"/sources/{source['id']}")
    assert shown.status_code == 200, shown.text
    assert shown.json()["source"]["access"]["host"] == _HOST
    assert "password" not in shown.json()["source"]["access"]

    _assert_forbidden(client.get(f"/sources/{source['id']}/access"))
    _assert_forbidden(client.patch(f"/sources/{source['id']}", json={"name": "nope"}))
    _assert_forbidden(
        client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    )
    _assert_forbidden(client.post(f"/sources/{source['id']}/test", json={}))
    _assert_forbidden(client.delete(f"/sources/{source['id']}"))
    assert client.get(f"/sources/{source['id']}").json()["source"]["status"] == "active"


def test_maintainer_without_role_write_is_forbidden_not_missing(
    client: TestClient,
) -> None:
    _login(client, "admin")
    source = _create(client, "locked")
    create_membership(
        subject_type="user",
        subject_id=_user_id("reader"),
        target=source["id"],
        level="maintainer",
    )
    _login(client, "reader")
    shown = client.get(f"/sources/{source['id']}")
    assert shown.status_code == 200, shown.text
    _assert_forbidden(client.patch(f"/sources/{source['id']}", json={"name": "nope"}))
    _assert_forbidden(client.get(f"/sources/{source['id']}/access"))
    _assert_forbidden(client.delete(f"/sources/{source['id']}"))


def test_maintainer_with_write_operates_the_source(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probe(monkeypatch)
    _login(client, "writer")
    source = _create(client, "mine")
    listed = client.get("/sources")
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["access"]["host"] == _HOST

    patched = client.patch(f"/sources/{source['id']}", json={"name": "Mine"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["source"]["name"] == "Mine"

    full = client.get(f"/sources/{source['id']}/access")
    assert full.status_code == 200, full.text
    assert full.json()["access"]["password"] == _PASSWORD

    probed = client.post(f"/sources/{source['id']}/test", json={})
    assert probed.status_code == 200, probed.text
    assert probed.json()["ok"] is True

    blocked = client.delete(f"/sources/{source['id']}")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "SOURCE_NOT_DISABLED"

    disabled = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200, disabled.text
    active_delete = client.delete(f"/sources/{source['id']}")
    assert active_delete.status_code == 204, active_delete.text
    _assert_not_found(client.get(f"/sources/{source['id']}"))


def test_create_draft_test_and_schema_need_no_membership(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_probe(monkeypatch)
    _login(client, "reader")
    schema = client.get("/sources/access-schema/postgresql")
    assert schema.status_code == 200, schema.text
    assert schema.json()["engine"] == "postgresql"
    draft_denied = client.post(
        "/sources/test",
        json={"engine": "postgresql", "access": _access()},
    )
    _assert_forbidden(draft_denied)

    _login(client, "writer")
    schema = client.get("/sources/access-schema/postgresql")
    assert schema.status_code == 200, schema.text
    draft = client.post(
        "/sources/test",
        json={"engine": "postgresql", "access": _access()},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["ok"] is True
    created = _create(client, "fresh")
    assert created["has_access"] is True
    assert client.get(f"/sources/{created['id']}").status_code == 200


def test_creator_membership_and_audit_survive_every_source_access(
    client: TestClient,
) -> None:
    create_membership(
        subject_type="user",
        subject_id=_user_id("writer"),
        target=EVERY_SOURCE_TARGET,
        level="viewer",
    )
    _login(client, "writer")
    source = _create(client, "extra")

    rows = [
        row
        for row in list_memberships()
        if row.subject_type == "user" and row.subject_id == _user_id("writer")
    ]
    by_target = {row.target: row for row in rows}
    assert by_target[EVERY_SOURCE_TARGET].level == "viewer"
    assert by_target[source["id"]].level == "maintainer"

    created = client.get(
        "/audit/events", params={"action": "source.create", "limit": 20}
    )
    assert created.status_code == 200, created.text
    assert any(
        event["resource_type"] == "source" and event["resource_id"] == source["id"]
        for event in created.json()["items"]
    )
    membership = client.get(
        "/audit/events",
        params={"action": "source_membership.create", "limit": 20},
    )
    assert membership.status_code == 200, membership.text
    events = membership.json()["items"]
    assert len(events) == 1
    event = events[0]
    assert event["resource_type"] == "source_membership"
    assert event["resource_id"] == by_target[source["id"]].id
    assert event["detail"]["subject"] == {"type": "user", "id": _user_id("writer")}
    assert event["detail"]["target"] == source["id"]
    assert event["detail"]["old_level"] is None
    assert event["detail"]["new_level"] == "maintainer"


def test_super_admin_creator_still_receives_a_user_membership(
    client: TestClient,
) -> None:
    _login(client, "admin")
    source = _create(client, "admin-src")
    rows = [row for row in list_memberships() if row.target == source["id"]]
    assert len(rows) == 1
    assert rows[0].subject_type == "user"
    assert rows[0].subject_id == _user_id("admin")
    assert rows[0].level == "maintainer"


def test_failed_seed_removes_the_creator_membership(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("seed failed")

    monkeypatch.setattr(
        "backend.metadata.sources.service.seed_default_source_schedules",
        _fail,
    )
    _login(client, "writer")
    with pytest.raises(RuntimeError, match="seed failed"):
        _create(client, "doomed")

    assert list_memberships() == ()
    assert get_source_store().get_source_by_key("doomed") is None
    _login(client, "admin")
    audits = client.get(
        "/audit/events",
        params={"action": "source_membership.create", "limit": 20},
    )
    assert audits.status_code == 200, audits.text
    assert audits.json()["items"] == []


def test_hard_delete_removes_only_memberships_for_that_source(
    client: TestClient,
) -> None:
    _login(client, "admin")
    doomed = _create(client, "doomed")
    kept = _create(client, "kept")
    role = get_role_store().get_by_key("source_reader")
    assert role is not None
    create_membership(
        subject_type="role",
        subject_id=role.id,
        target=doomed["id"],
        level="viewer",
    )
    create_membership(
        subject_type="user",
        subject_id=_user_id("reader"),
        target=EVERY_SOURCE_TARGET,
        level="viewer",
    )
    create_membership(
        subject_type="user",
        subject_id=_user_id("reader"),
        target=kept["id"],
        level="steward",
    )
    disabled = client.patch(f"/sources/{doomed['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200, disabled.text
    deleted = client.delete(f"/sources/{doomed['id']}")
    assert deleted.status_code == 204, deleted.text

    remaining = list_memberships()
    assert all(row.target != doomed["id"] for row in remaining)
    assert any(row.target == EVERY_SOURCE_TARGET for row in remaining)
    assert any(
        row.target == kept["id"] and row.subject_id == _user_id("reader")
        for row in remaining
    )
    assert any(
        row.target == kept["id"] and row.subject_id == _user_id("admin")
        for row in remaining
    )
