"""Audit list Instant bounds: offset required before comparison."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.audit_store import AuditEventRecord, get_audit_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, reset_role_store  # noqa: E402
from backend.admin.session_store import MemorySessionStore, reset_session_store  # noqa: E402
from backend.admin.user_store import MemoryUserStore, reset_user_store  # noqa: E402


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    role_store = MemoryRoleStore()
    seed_roles(role_store)
    user_store = MemoryUserStore()
    super_admin = role_store.get_by_key("super_admin")
    assert super_admin is not None
    user_store.create_user(
        account="root",
        display_name="Root Admin",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
        status="active",
    )
    session_store = MemorySessionStore()
    yield user_store, role_store, session_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store = store_bundle
    from backend.admin.role_store import get_role_store
    from backend.admin.session_store import get_session_store
    from backend.admin.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"account": "root", "password": "s3cret"}
    )
    assert response.status_code == 200


def _seed_event(created_at: datetime) -> None:
    get_audit_store().create(
        AuditEventRecord(
            id="aud_bound",
            created_at=created_at,
            actor_user_id=None,
            actor_token_id=None,
            resource_type="source",
            resource_id="src_1",
            action="secret.rotate",
            result="success",
        )
    )


@pytest.mark.parametrize("param", ["from", "to"])
def test_audit_list_rejects_offsetless_bound_before_comparison(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, param: str
) -> None:
    _seed_event(datetime(2026, 8, 12, 2, 0, 5, tzinfo=timezone.utc))
    store = get_audit_store()
    calls: list[tuple[datetime | None, datetime | None]] = []
    original = store.list_events

    def wrapped(**kwargs):
        calls.append((kwargs.get("from_dt"), kwargs.get("to_dt")))
        return original(**kwargs)

    monkeypatch.setattr(store, "list_events", wrapped)
    _login(client)
    response = client.get("/audit/events", params={param: "2026-08-12T02:00:05"})
    assert_problem(response, status=422, code="REQUEST_INVALID")
    assert calls == []


def test_audit_list_compares_fractional_offset_and_returns_second_z(
    client: TestClient,
) -> None:
    _seed_event(datetime(2026, 8, 12, 2, 0, 5, 100000, tzinfo=timezone.utc))
    _login(client)

    later = client.get("/audit/events", params={"from": "2026-08-12T02:00:05.900000Z"})
    assert later.status_code == 200
    assert later.json()["items"] == []

    matched = client.get(
        "/audit/events", params={"from": "2026-08-12T10:00:05.100000+08:00"}
    )
    assert matched.status_code == 200
    items = matched.json()["items"]
    assert [item["id"] for item in items] == ["aud_bound"]
    assert items[0]["created_at"] == "2026-08-12T02:00:05Z"

    before = client.get("/audit/events", params={"to": "2026-08-12T02:00:05.099999Z"})
    assert before.status_code == 200
    assert before.json()["items"] == []

    inclusive = client.get(
        "/audit/events", params={"to": "2026-08-12T02:00:05.100000Z"}
    )
    assert inclusive.status_code == 200
    assert inclusive.json()["items"][0]["created_at"] == "2026-08-12T02:00:05Z"
