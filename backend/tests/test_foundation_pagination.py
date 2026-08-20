"""Foundation Offset Page: users, roles, tokens, sources, schedules, joins."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.token_store import reset_token_store  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.store import reset_catalog_store  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.schedules import reset_schedule_store  # noqa: E402


def _access() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "u",
        "password": "p",
        "ssl_mode": "require",
        "database": "MES",
        "schema": "public",
        "extra": {},
    }


def _source_body(key: str) -> dict:
    return {
        "key": key,
        "name": key,
        "kind": "database",
        "engine": "postgresql",
        "access": _access(),
    }


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_token_store()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    reset_schedule_store()
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=super_admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client


def test_users_http_envelope_and_pages(client: TestClient) -> None:
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    for account in ("alice", "bob"):
        created = client.post(
            "/users",
            json={
                "account": account,
                "display_name": account,
                "password": "pw",
                "role_id": operator.id,
            },
        )
        assert created.status_code == 201, created.text

    defaulted = client.get("/users")
    assert defaulted.status_code == 200
    body = defaulted.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["account"] for item in body["items"]] == ["admin", "alice", "bob"]

    page1 = client.get("/users?limit=2&offset=0")
    page2 = client.get("/users?limit=2&offset=2")
    assert [item["account"] for item in page1.json()["items"]] == ["admin", "alice"]
    assert page1.json()["total"] == 3
    assert [item["account"] for item in page2.json()["items"]] == ["bob"]
    past = client.get("/users?limit=2&offset=99")
    assert past.status_code == 200
    assert past.json()["items"] == []
    assert past.json()["total"] == 3


def test_users_http_rejects_oversize_limit(client: TestClient) -> None:
    resp = client.get("/users?limit=201")
    assert resp.status_code == 422
    assert resp.json()["code"] == "REQUEST_INVALID"


def test_roles_http_envelope_and_pages(client: TestClient) -> None:
    defaulted = client.get("/roles")
    assert defaulted.status_code == 200
    body = defaulted.json()
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["total"] >= 2
    keys = [item["key"] for item in body["items"]]
    assert keys[0] == "super_admin"
    page = client.get("/roles?limit=1&offset=0")
    assert page.json()["items"][0]["key"] == "super_admin"
    assert page.json()["total"] == body["total"]
    over = client.get("/roles?limit=201")
    assert over.status_code == 422


def test_tokens_http_envelope_and_pages(client: TestClient) -> None:
    expires = (utc_now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    for name in ("alpha", "beta", "gamma"):
        created = client.post("/tokens", json={"name": name, "expires_at": expires})
        assert created.status_code == 201, created.text
        ids.append(created.json()["token"]["id"])

    defaulted = client.get("/tokens")
    assert defaulted.status_code == 200
    body = defaulted.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert [item["id"] for item in body["items"]] == list(reversed(ids))
    page = client.get("/tokens?limit=1&offset=1")
    assert page.json()["items"][0]["id"] == ids[1]
    assert page.json()["total"] == 3
    over = client.get("/tokens?limit=201")
    assert over.status_code == 422


def test_sources_http_envelope_and_pages(client: TestClient) -> None:
    first = client.post("/sources", json=_source_body("aaa-src"))
    second = client.post("/sources", json=_source_body("bbb-src"))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    a_id = first.json()["source"]["id"]
    b_id = second.json()["source"]["id"]

    defaulted = client.get("/sources")
    assert defaulted.status_code == 200
    body = defaulted.json()
    assert body["total"] == 2
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [a_id, b_id]

    page1 = client.get("/sources?limit=1&offset=0")
    page2 = client.get("/sources?limit=1&offset=1")
    assert page1.json()["items"][0]["id"] == a_id
    assert page2.json()["items"][0]["id"] == b_id
    assert page2.json()["total"] == 2
    past = client.get("/sources?offset=99")
    assert past.json()["items"] == []
    assert past.json()["total"] == 2
    over = client.get("/sources?limit=501")
    assert over.status_code == 422


def test_schedules_http_envelope_and_source_scope(client: TestClient) -> None:
    src_a = client.post("/sources", json=_source_body("sched-a"))
    src_b = client.post("/sources", json=_source_body("sched-b"))
    assert src_a.status_code == 201, src_a.text
    assert src_b.status_code == 201, src_b.text
    a_id = src_a.json()["source"]["id"]
    b_id = src_b.json()["source"]["id"]

    platform = client.get("/schedules")
    assert platform.status_code == 200
    body = platform.json()
    assert body["total"] == 4
    assert body["limit"] == 50
    page = client.get("/schedules?limit=1&offset=0")
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == 4
    with_system = client.get("/schedules?system=true")
    assert with_system.status_code == 200
    assert with_system.json()["total"] > body["total"]
    over = client.get("/schedules?limit=201")
    assert over.status_code == 422

    scoped = client.get(f"/sources/{a_id}/schedules")
    assert scoped.status_code == 200
    scoped_body = scoped.json()
    assert scoped_body["total"] == 2
    assert scoped_body["limit"] == 50
    assert scoped_body["items"][0]["target"]["source_id"] == a_id
    other = client.get(f"/sources/{b_id}/schedules")
    assert other.json()["items"][0]["id"] != scoped_body["items"][0]["id"]
    past = client.get(f"/sources/{a_id}/schedules?offset=99")
    assert past.json()["items"] == []
    assert past.json()["total"] == 2
    over_src = client.get(f"/sources/{a_id}/schedules?limit=201")
    assert over_src.status_code == 422
