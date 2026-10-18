"""Case-insensitive list `q` for Users, Roles, Sources, and Channels.

Memory coverage goes through HTTP. SQL coverage uses sqlite so the suite
does not open Postgres. LIKE metacharacters stay literal on both adapters.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.models import RoleRow, UserRow  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, RoleRecord, SqlRoleStore  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.session_store import MemorySessionStore  # noqa: E402
from backend.admin.user_store import (  # noqa: E402
    IdentitySource,
    MemoryUserStore,
    SqlUserStore,
)
from backend.channel.models import ChannelRow  # noqa: E402
from backend.channel.store import (  # noqa: E402
    ChannelRecord,
    MemoryChannelStore,
    SqlChannelStore,
    empty_graph,
)
from backend.core.db import Base  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.models import SourceRow  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    MemorySourceStore,
    SourceRecord,
    SqlSourceStore,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw) -> str:  # noqa: ANN001
    return "JSON"


_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def _page_matches(full_ids: list[str], page_ids: list[str], total: int) -> None:
    assert total == len(full_ids) == 3
    assert page_ids == full_ids[1:2]


@contextmanager
def _sqlite(module: str, tables: list) -> Iterator[None]:
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

    Base.metadata.create_all(engine, tables=tables)

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

    target = __import__(module, fromlist=["session_scope"])
    previous = target.session_scope
    target.session_scope = session_scope
    try:
        yield
    finally:
        target.session_scope = previous
        engine.dispose()


def _assert_user_query(store: MemoryUserStore | SqlUserStore) -> None:
    for account, display_name, email in (
        ("wild_mark", "Alpha", None),
        ("wildx", "Beta", None),
        ("pct", "100% done", "Ada@Example.com"),
        ("ann-a", "Annabel One", None),
        ("ann-b", "Annabel Two", None),
        ("ann-c", "Annabel Three", None),
    ):
        store.create_user(
            account=account,
            display_name=display_name,
            password_hash="x",
            role_id=None,
            email=email,
            user_id=f"user_{account}",
        )

    folded, folded_total = store.list_users(q="ANNABEL")
    assert folded_total == 3
    assert {item.account for item in folded} == {"ann-a", "ann-b", "ann-c"}

    missing, missing_total = store.list_users(q="zzzz-no-such")
    assert missing == []
    assert missing_total == 0

    blank, blank_total = store.list_users(q="   ")
    omitted, omitted_total = store.list_users()
    assert blank_total == omitted_total == 6
    assert [item.id for item in blank] == [item.id for item in omitted]

    underscore, underscore_total = store.list_users(q="wild_")
    assert underscore_total == 1
    assert underscore[0].account == "wild_mark"

    percent, percent_total = store.list_users(q="%")
    assert percent_total == 1
    assert percent[0].account == "pct"

    email, email_total = store.list_users(q="ada@example")
    assert email_total == 1
    assert email[0].account == "pct"

    full, full_total = store.list_users(q="annabel", limit=50, offset=0)
    page, page_total = store.list_users(q="annabel", limit=1, offset=1)
    _page_matches([item.id for item in full], [item.id for item in page], page_total)
    assert full_total == page_total


def _assert_role_query(store: MemoryRoleStore | SqlRoleStore) -> None:
    for index, (key, name) in enumerate(
        (
            ("wild_mark", "Alpha"),
            ("other", "100% done"),
            ("analysta", "Analyst A"),
            ("analystb", "Analyst B"),
            ("analystc", "Analyst C"),
        )
    ):
        store.insert(
            RoleRecord(
                id=f"role_{key}",
                key=key,
                name=name,
                permissions=["console:access"],
                created_at=float(index),
            )
        )

    folded, folded_total = store.list_roles(q="ALPHA")
    assert folded_total == 1
    assert folded[0].key == "wild_mark"

    missing, missing_total = store.list_roles(q="zzzz-no-such")
    assert missing == []
    assert missing_total == 0

    blank, blank_total = store.list_roles(q="   ")
    omitted, omitted_total = store.list_roles()
    assert blank_total == omitted_total
    assert [item.id for item in blank] == [item.id for item in omitted]

    underscore, underscore_total = store.list_roles(q="_")
    assert underscore_total == 1
    assert underscore[0].key == "wild_mark"

    percent, percent_total = store.list_roles(q="%")
    assert percent_total == 1
    assert percent[0].key == "other"

    full, _full_total = store.list_roles(q="analyst", limit=50, offset=0)
    page, page_total = store.list_roles(q="analyst", limit=1, offset=1)
    _page_matches([item.id for item in full], [item.id for item in page], page_total)


def _source(
    source_id: str, key: str, name: str, *, engine: str = "postgresql"
) -> SourceRecord:
    return SourceRecord(
        id=source_id,
        key=key,
        locator_key="pending",
        name=name,
        kind="database",
        status="active",
        description=None,
        engine=engine,
        access_ciphertext=None,
        access_updated_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _assert_source_query(store: MemorySourceStore | SqlSourceStore) -> None:
    for key, name in (
        ("wild_mark", "Alpha"),
        ("wildx", "Beta"),
        ("pct", "100% done"),
        ("ann-a", "Annabel One"),
        ("ann-b", "Annabel Two"),
        ("ann-c", "Annabel Three"),
    ):
        store.create_source(_source(f"src_{key}", key, name))

    folded, folded_total = store.list_sources(query_text="ANNABEL")
    assert folded_total == 3
    assert {item.key for item in folded} == {"ann-a", "ann-b", "ann-c"}

    locator, locator_total = store.list_sources(query_text="postgresql")
    assert locator_total == 6
    assert all("postgresql" in item.locator_key for item in locator)

    missing, missing_total = store.list_sources(query_text="zzzz-no-such")
    assert missing == []
    assert missing_total == 0

    blank, blank_total = store.list_sources(query_text="   ")
    omitted, omitted_total = store.list_sources()
    assert blank_total == omitted_total == 6
    assert [item.id for item in blank] == [item.id for item in omitted]

    underscore, underscore_total = store.list_sources(query_text="wild_")
    assert underscore_total == 1
    assert underscore[0].key == "wild_mark"

    percent, percent_total = store.list_sources(query_text="%")
    assert percent_total == 1
    assert percent[0].key == "pct"

    full, _full_total = store.list_sources(query_text="annabel", limit=50, offset=0)
    page, page_total = store.list_sources(query_text="annabel", limit=1, offset=1)
    _page_matches([item.id for item in full], [item.id for item in page], page_total)


def _channel(channel_id: str, name: str, *, seconds: int) -> ChannelRecord:
    stamp = _NOW + timedelta(seconds=seconds)
    return ChannelRecord(
        id=channel_id,
        name=name,
        description=None,
        active=False,
        draft_graph=empty_graph(),
        draft_revision=1,
        draft_updated_at=stamp,
        created_at=stamp,
        updated_at=stamp,
    )


def _assert_channel_query(store: MemoryChannelStore | SqlChannelStore) -> None:
    for index, (channel_id, name) in enumerate(
        (
            ("ch_material", "Material Master"),
            ("ch_pct", "100% done"),
            ("ch_under", "under_score"),
            ("ch_a", "Batch A"),
            ("ch_b", "Batch B"),
            ("ch_c", "Batch C"),
        )
    ):
        store.create(_channel(channel_id, name, seconds=index))

    folded, folded_total = store.list_channels(q="MATERIAL", active=None, limit=50, offset=0)
    assert folded_total == 1
    assert folded[0].id == "ch_material"

    missing, missing_total = store.list_channels(
        q="zzzz-no-such", active=None, limit=50, offset=0
    )
    assert missing == []
    assert missing_total == 0

    blank, blank_total = store.list_channels(q="   ", active=None, limit=50, offset=0)
    omitted, omitted_total = store.list_channels(q=None, active=None, limit=50, offset=0)
    assert blank_total == omitted_total == 6
    assert [item.id for item in blank] == [item.id for item in omitted]

    underscore, underscore_total = store.list_channels(
        q="_", active=None, limit=50, offset=0
    )
    assert underscore_total == 1
    assert underscore[0].id == "ch_under"

    percent, percent_total = store.list_channels(q="%", active=None, limit=50, offset=0)
    assert percent_total == 1
    assert percent[0].id == "ch_pct"

    full, _full_total = store.list_channels(q="batch", active=None, limit=50, offset=0)
    page, page_total = store.list_channels(q="batch", active=None, limit=1, offset=1)
    _page_matches([item.id for item in full], [item.id for item in page], page_total)


def test_memory_user_query() -> None:
    _assert_user_query(MemoryUserStore())


def test_sql_user_query() -> None:
    with _sqlite("backend.admin.user_store", [RoleRow.__table__, UserRow.__table__]):
        _assert_user_query(SqlUserStore())


def test_memory_role_query() -> None:
    _assert_role_query(MemoryRoleStore())


def test_sql_role_query() -> None:
    with _sqlite("backend.admin.role_store", [RoleRow.__table__]):
        _assert_role_query(SqlRoleStore())


def test_memory_source_query() -> None:
    _assert_source_query(MemorySourceStore())


def test_sql_source_query() -> None:
    with _sqlite("backend.metadata.sources.store", [SourceRow.__table__]):
        _assert_source_query(SqlSourceStore())


def _assert_user_identity_source(store: MemoryUserStore | SqlUserStore) -> None:
    seeded: tuple[tuple[str, IdentitySource, str], ...] = (
        ("ann-a", "local", "Annabel One"),
        ("ann-b", "local", "Annabel Two"),
        ("ann-c", "local", "Annabel Three"),
        ("ann-o", "oidc", "Annabel Oidc"),
        ("zed", "local", "Zed"),
    )
    for account, source, name in seeded:
        store.create_user(
            account=account,
            display_name=name,
            password_hash="x" if source == "local" else None,
            role_id=None,
            identity_source=source,
            user_id=f"user_{account}",
        )
    store.create_user(
        account="sys",
        display_name="System",
        password_hash=None,
        role_id=None,
        identity_source="system",
        user_id="user_sys",
    )

    local, local_total = store.list_users(identity_source="local")
    assert local_total == 4
    assert {item.account for item in local} == {"ann-a", "ann-b", "ann-c", "zed"}

    oidc, oidc_total = store.list_users(identity_source="oidc")
    assert oidc_total == 1
    assert oidc[0].account == "ann-o"

    missing, missing_total = store.list_users(identity_source="oidc", q="zzzz-no-such")
    assert missing == []
    assert missing_total == 0

    combined, combined_total = store.list_users(identity_source="local", q="annabel")
    assert combined_total == 3
    assert {item.account for item in combined} == {"ann-a", "ann-b", "ann-c"}

    hidden, hidden_total = store.list_users(identity_source="system")
    assert hidden == []
    assert hidden_total == 0
    shown, shown_total = store.list_users(identity_source="system", include_system=True)
    assert shown_total == 1
    assert shown[0].account == "sys"

    full, full_total = store.list_users(
        identity_source="local", q="annabel", limit=50, offset=0
    )
    page, page_total = store.list_users(
        identity_source="local", q="annabel", limit=1, offset=1
    )
    _page_matches([item.id for item in full], [item.id for item in page], page_total)
    assert full_total == page_total


def _assert_source_engine(store: MemorySourceStore | SqlSourceStore) -> None:
    for key, name, engine in (
        ("ann-a", "Annabel One", "postgresql"),
        ("ann-b", "Annabel Two", "postgresql"),
        ("ann-c", "Annabel Three", "postgresql"),
        ("ann-o", "Annabel Oracle", "oracle"),
        ("zed", "Zed", "mssql"),
    ):
        store.create_source(_source(f"src_{key}", key, name, engine=engine))

    postgres, postgres_total = store.list_sources(engine="postgresql")
    assert postgres_total == 3
    assert {item.key for item in postgres} == {"ann-a", "ann-b", "ann-c"}

    oracle, oracle_total = store.list_sources(engine="oracle", query_text="zzzz-no-such")
    assert oracle == []
    assert oracle_total == 0

    combined, combined_total = store.list_sources(engine="oracle", query_text="annabel")
    assert combined_total == 1
    assert combined[0].key == "ann-o"

    blank, blank_total = store.list_sources(engine="   ", query_text="annabel")
    omitted, omitted_total = store.list_sources(query_text="annabel")
    assert blank_total == omitted_total == 4
    assert [item.id for item in blank] == [item.id for item in omitted]

    full, full_total = store.list_sources(
        engine="postgresql", query_text="annabel", limit=50, offset=0
    )
    page, page_total = store.list_sources(
        engine="postgresql", query_text="annabel", limit=1, offset=1
    )
    _page_matches([item.id for item in full], [item.id for item in page], page_total)
    assert full_total == page_total


def test_memory_user_identity_source() -> None:
    _assert_user_identity_source(MemoryUserStore())


def test_sql_user_identity_source() -> None:
    with _sqlite("backend.admin.user_store", [RoleRow.__table__, UserRow.__table__]):
        _assert_user_identity_source(SqlUserStore())


def test_memory_source_engine() -> None:
    _assert_source_engine(MemorySourceStore())


def test_sql_source_engine() -> None:
    with _sqlite("backend.metadata.sources.store", [SourceRow.__table__]):
        _assert_source_engine(SqlSourceStore())


def test_memory_channel_query() -> None:
    _assert_channel_query(MemoryChannelStore())


def test_sql_channel_query() -> None:
    with _sqlite("backend.channel.store", [ChannelRow.__table__]):
        _assert_channel_query(SqlChannelStore())


@pytest.fixture
def client():
    from backend.admin.role_store import get_role_store, reset_role_store
    from backend.admin.session_store import get_session_store, reset_session_store
    from backend.admin.user_store import get_user_store, reset_user_store
    from backend.core.config import reset_settings_cache
    from backend.metadata.sources.store import reset_source_store
    from backend.channel.store import reset_channel_store

    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_source_store()
    reset_channel_store()
    role_store = MemoryRoleStore()
    seed_roles(role_store)
    user_store = MemoryUserStore()
    super_admin = role_store.get_by_key("super_admin")
    assert super_admin is not None
    user_store.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
    )
    session_store = MemorySessionStore()
    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "root", "password": "s3cret"}
        )
        assert login.status_code == 200, login.text
        yield test_client, user_store, role_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_source_store()
    reset_channel_store()


def _ids(body: dict, field: str) -> list[str]:
    return [item[field] for item in body["items"]]


def test_users_q_http(client) -> None:
    test_client, user_store, _roles = client
    for account, display_name, email in (
        ("wild_mark", "Alpha", None),
        ("wildx", "Beta", None),
        ("pct", "100% done", "Ada@Example.com"),
        ("ann-a", "Annabel One", None),
        ("ann-b", "Annabel Two", None),
        ("ann-c", "Annabel Three", None),
    ):
        user_store.create_user(
            account=account,
            display_name=display_name,
            password_hash="x",
            role_id=None,
            email=email,
            user_id=f"user_{account}",
        )

    folded = test_client.get("/users", params={"q": "ANNABEL"}).json()
    assert folded["total"] == 3
    assert {item["account"] for item in folded["items"]} == {"ann-a", "ann-b", "ann-c"}

    missing = test_client.get("/users", params={"q": "zzzz-no-such"}).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    omitted = test_client.get("/users").json()
    blank = test_client.get("/users", params={"q": "   "}).json()
    assert blank["total"] == omitted["total"]
    assert _ids(blank, "id") == _ids(omitted, "id")

    underscore = test_client.get("/users", params={"q": "wild_"}).json()
    assert underscore["total"] == 1
    assert underscore["items"][0]["account"] == "wild_mark"

    percent = test_client.get("/users", params={"q": "%"}).json()
    assert percent["total"] == 1
    assert percent["items"][0]["account"] == "pct"

    email = test_client.get("/users", params={"q": "ada@example"}).json()
    assert email["total"] == 1
    assert email["items"][0]["account"] == "pct"

    full = test_client.get("/users", params={"q": "annabel", "limit": 50}).json()
    page = test_client.get(
        "/users", params={"q": "annabel", "limit": 1, "offset": 1}
    ).json()
    assert page["limit"] == 1
    assert page["offset"] == 1
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])


def test_roles_q_http(client) -> None:
    test_client, _users, _roles = client
    for key, name in (
        ("wild_mark", "Alpha"),
        ("other", "100% done"),
        ("analysta", "Analyst A"),
        ("analystb", "Analyst B"),
        ("analystc", "Analyst C"),
    ):
        created = test_client.post(
            "/roles",
            json={"key": key, "name": name, "permissions": ["console:access"]},
        )
        assert created.status_code == 201, created.text

    folded = test_client.get("/roles", params={"q": "ALPHA"}).json()
    assert folded["total"] == 1
    assert folded["items"][0]["key"] == "wild_mark"

    missing = test_client.get("/roles", params={"q": "zzzz-no-such"}).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    omitted = test_client.get("/roles").json()
    blank = test_client.get("/roles", params={"q": "   "}).json()
    assert blank["total"] == omitted["total"]
    assert _ids(blank, "id") == _ids(omitted, "id")

    underscore = test_client.get("/roles", params={"q": "wild_"}).json()
    assert underscore["total"] == 1
    assert underscore["items"][0]["key"] == "wild_mark"

    percent = test_client.get("/roles", params={"q": "%"}).json()
    assert percent["total"] == 1
    assert percent["items"][0]["name"] == "100% done"

    full = test_client.get("/roles", params={"q": "analyst", "limit": 50}).json()
    page = test_client.get(
        "/roles", params={"q": "analyst", "limit": 1, "offset": 1}
    ).json()
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])


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


def test_sources_q_http(client) -> None:
    test_client, _users, _roles = client
    for key, name in (
        ("wild_mark", "Alpha"),
        ("wildx", "Beta"),
        ("pct", "100% done"),
        ("ann-a", "Annabel One"),
        ("ann-b", "Annabel Two"),
        ("ann-c", "Annabel Three"),
    ):
        created = test_client.post(
            "/sources",
            json={
                "key": key,
                "name": name,
                "kind": "database",
                "engine": "postgresql",
                "access": _access(),
            },
        )
        assert created.status_code == 201, created.text

    folded = test_client.get("/sources", params={"q": "ANNABEL"}).json()
    assert folded["total"] == 3

    locator = test_client.get("/sources", params={"q": "postgresql"}).json()
    assert locator["total"] == 6

    missing = test_client.get("/sources", params={"q": "zzzz-no-such"}).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    omitted = test_client.get("/sources").json()
    blank = test_client.get("/sources", params={"q": "   "}).json()
    assert blank["total"] == omitted["total"]
    assert _ids(blank, "id") == _ids(omitted, "id")

    underscore = test_client.get("/sources", params={"q": "wild_"}).json()
    assert underscore["total"] == 1
    assert underscore["items"][0]["key"] == "wild_mark"

    percent = test_client.get("/sources", params={"q": "%"}).json()
    assert percent["total"] == 1
    assert percent["items"][0]["key"] == "pct"

    full = test_client.get("/sources", params={"q": "annabel", "limit": 50}).json()
    page = test_client.get(
        "/sources", params={"q": "annabel", "limit": 1, "offset": 1}
    ).json()
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])


def test_channels_q_http(client) -> None:
    test_client, _users, _roles = client
    for name in (
        "Material Master",
        "100% done",
        "under_score",
        "Batch A",
        "Batch B",
        "Batch C",
    ):
        created = test_client.post(
            "/channels", json={"name": name, "description": None}
        )
        assert created.status_code == 201, created.text

    folded = test_client.get("/channels", params={"q": "MATERIAL"}).json()
    assert folded["total"] == 1
    assert folded["items"][0]["name"] == "Material Master"

    missing = test_client.get("/channels", params={"q": "zzzz-no-such"}).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    omitted = test_client.get("/channels").json()
    blank = test_client.get("/channels", params={"q": "   "}).json()
    assert blank["total"] == omitted["total"]
    assert _ids(blank, "id") == _ids(omitted, "id")

    underscore = test_client.get("/channels", params={"q": "_"}).json()
    assert underscore["total"] == 1
    assert underscore["items"][0]["name"] == "under_score"

    percent = test_client.get("/channels", params={"q": "%"}).json()
    assert percent["total"] == 1
    assert percent["items"][0]["name"] == "100% done"

    full = test_client.get("/channels", params={"q": "batch", "limit": 50}).json()
    page = test_client.get(
        "/channels", params={"q": "batch", "limit": 1, "offset": 1}
    ).json()
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])


def test_users_identity_source_http(client) -> None:
    test_client, user_store, _roles = client
    seeded: tuple[tuple[str, IdentitySource, str], ...] = (
        ("ann-a", "local", "Annabel One"),
        ("ann-b", "local", "Annabel Two"),
        ("ann-c", "local", "Annabel Three"),
        ("ann-o", "oidc", "Annabel Oidc"),
        ("zed", "local", "Zed"),
    )
    for account, source, name in seeded:
        user_store.create_user(
            account=account,
            display_name=name,
            password_hash="x" if source == "local" else None,
            role_id=None,
            identity_source=source,
            user_id=f"user_{account}",
        )

    local = test_client.get("/users", params={"identity_source": "local"}).json()
    assert local["total"] == 5
    assert "ann-o" not in {item["account"] for item in local["items"]}

    oidc = test_client.get("/users", params={"identity_source": "oidc"}).json()
    assert oidc["total"] == 1
    assert oidc["items"][0]["account"] == "ann-o"

    missing = test_client.get(
        "/users", params={"identity_source": "oidc", "q": "zzzz-no-such"}
    ).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    combined = test_client.get(
        "/users", params={"identity_source": "local", "q": "annabel"}
    ).json()
    assert combined["total"] == 3
    assert {item["account"] for item in combined["items"]} == {"ann-a", "ann-b", "ann-c"}

    full = test_client.get(
        "/users", params={"identity_source": "local", "q": "annabel", "limit": 50}
    ).json()
    page = test_client.get(
        "/users",
        params={"identity_source": "local", "q": "annabel", "limit": 1, "offset": 1},
    ).json()
    assert page["limit"] == 1
    assert page["offset"] == 1
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])

    invalid = test_client.get("/users", params={"identity_source": "ldap"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_INVALID"


def _source_access(engine: str) -> dict:
    access: dict = {
        "host": "127.0.0.1",
        "username": "u",
        "password": "p",
        "extra": {},
    }
    if engine == "oracle":
        access.update(port=1521, ssl_mode="disable", service_name="ORCL", owner="APP")
    elif engine == "mssql":
        access.update(port=1433, ssl_mode="disable", database="app", schema="dbo")
    else:
        access.update(port=5432, ssl_mode="require", database="MES", schema="public")
    return access


def test_sources_engine_http(client) -> None:
    test_client, _users, _roles = client
    for key, name, engine in (
        ("ann-a", "Annabel One", "postgresql"),
        ("ann-b", "Annabel Two", "postgresql"),
        ("ann-c", "Annabel Three", "postgresql"),
        ("ann-o", "Annabel Oracle", "oracle"),
        ("zed", "Zed", "mssql"),
    ):
        created = test_client.post(
            "/sources",
            json={
                "key": key,
                "name": name,
                "kind": "database",
                "engine": engine,
                "access": _source_access(engine),
            },
        )
        assert created.status_code == 201, created.text

    postgres = test_client.get("/sources", params={"engine": "postgresql"}).json()
    assert postgres["total"] == 3
    assert {item["key"] for item in postgres["items"]} == {"ann-a", "ann-b", "ann-c"}

    missing = test_client.get(
        "/sources", params={"engine": "oracle", "q": "zzzz-no-such"}
    ).json()
    assert missing["items"] == []
    assert missing["total"] == 0

    combined = test_client.get(
        "/sources", params={"engine": "oracle", "q": "annabel"}
    ).json()
    assert combined["total"] == 1
    assert combined["items"][0]["key"] == "ann-o"
    assert combined["items"][0]["engine"] == "oracle"

    full = test_client.get(
        "/sources", params={"engine": "postgresql", "q": "annabel", "limit": 50}
    ).json()
    page = test_client.get(
        "/sources",
        params={"engine": "postgresql", "q": "annabel", "limit": 1, "offset": 1},
    ).json()
    _page_matches(_ids(full, "id"), _ids(page, "id"), page["total"])

    invalid = test_client.get("/sources", params={"engine": "snowflake"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_INVALID"
