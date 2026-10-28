"""Publish applies the change-log draft on the Postgres entity database.

A draft save does not touch the effective record or the entries. A successful
Publish creates the new empty head, leaves old rows on the old table, then
applies the draft. A failure before the version is published leaves both.
A policy failure after publish is retried without another head.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.entity.change_log import (
    CHANGE_LOG_SCHEMA,
    ENTRY_TABLE,
    ChangeLogEffective,
    list_entries,
    read_effective,
    write_effective,
)
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.records import AttributeRecord
from backend.tests.entity_pg import bootstrapped_entity_database

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_SKU = {
    "name": "sku",
    "type": "string",
    "required": True,
    "unique": True,
    "indexed": False,
    "description": "SKU code",
    "config": {"max_length": 32},
}

_LOG_ATTRIBUTES = (
    AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        max_length=32,
    ),
)
_ARMED = {"change_log_insert", "change_log_update", "change_log_delete"}


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def publish_database():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_cpub") as urls:
        yield urls


@pytest.fixture()
def client(publish_database):
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import reset_entity_engine
    from backend.entity.table_port import (
        PostgresEntityTablePort,
        bind_entity_table_port,
        reset_entity_table_port,
    )
    from backend.main import app
    from backend.worker.app import celery_app

    previous_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    previous_url = os.environ.get("ENTITY_DATABASE_URL")
    os.environ["ENTITY_DATABASE_URL"] = publish_database.owner_url
    reset_settings_cache()
    reset_entity_engine()
    bind_entity_table_port(PostgresEntityTablePort())
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
    try:
        with TestClient(app) as test_client:
            login = test_client.post(
                "/auth/login", json={"account": "admin", "password": "secret"}
            )
            assert login.status_code == 200, login.text
            yield test_client
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.task_eager_propagates = previous_propagates
        reset_entity_table_port()
        reset_entity_engine()
        if previous_url is None:
            os.environ.pop("ENTITY_DATABASE_URL", None)
        else:
            os.environ["ENTITY_DATABASE_URL"] = previous_url
        reset_settings_cache()


def _create(client: TestClient, **overrides: object) -> dict:
    body: dict = {
        "table_name": f"m{uuid.uuid4().hex[:10]}",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [_SKU],
    }
    body.update(overrides)
    created = client.post("/entities", json=body)
    assert created.status_code == 201, created.text
    return created.json()["entity"]


def _publish(client: TestClient, entity: dict) -> dict:
    version_id = entity["current_version"]["id"]
    published = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert published.status_code == 201, published.text
    return published.json()


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _count_rows(table: str) -> int:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        count = conn.execute(
            text(f"SELECT count(*) FROM {_relation(table)}")
        ).scalar_one()
    return int(count)


def _insert_sku(table: str, sku: str) -> None:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().begin() as conn:
        conn.execute(
            text(f"INSERT INTO {_relation(table)} (sku) VALUES (:sku)"),
            {"sku": sku},
        )


def _triggers(table: str) -> set[str]:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :table "
                "AND NOT t.tgisinternal"
            ),
            {"schema": ENTITY_DATA_SCHEMA, "table": table},
        ).all()
    return {str(row[0]) for row in rows}


def _effective(entity_id: str):
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        return read_effective(conn, entity_id)


def _entries(entity_id: str):
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        return list_entries(conn, entity_id, _LOG_ATTRIBUTES)


def _set_occurred_at(entity_id: str, sequence: int, when: object) -> None:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().begin() as conn:
        conn.execute(
            text(
                f"UPDATE {qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)} "
                "SET occurred_at = :when "
                "WHERE entity_id = :entity_id AND seq = :sequence"
            ),
            {"when": when, "entity_id": entity_id, "sequence": sequence},
        )


def test_first_publish_off_creates_the_table_and_installs_no_log(
    client: TestClient,
) -> None:
    from backend.entity.store import get_entity_store
    from backend.entity.table_name import compose_physical_table_name

    entity = _create(client)
    version_id = entity["current_version"]["id"]
    published = _publish(client, entity)
    assert published["job"]["status"] == "succeeded"
    physical, _comment = compose_physical_table_name(
        entity["table_name"], 1, version_id
    )
    assert _count_rows(physical) == 0
    stored = get_entity_store().get_version(version_id)
    assert stored is not None
    assert stored.publish_status == "published"
    assert stored.change_log_policy == "applied"
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is False
    assert effective.retention_days is None
    assert effective.applied_version_id == version_id
    assert _triggers(physical) == set()
    _insert_sku(physical, "kept")
    assert _entries(entity["id"]) == []
    assert _count_rows(physical) == 1


def _physical(stem: str, version: int, version_id: str) -> str:
    from backend.entity.table_name import compose_physical_table_name

    name, _comment = compose_physical_table_name(stem, version, version_id)
    return name


def _open(client: TestClient, entity_id: str) -> dict:
    opened = client.post(f"/entities/{entity_id}/versions", json={})
    assert opened.status_code == 201, opened.text
    return opened.json()["version"]


def _patch_log(
    client: TestClient,
    entity_id: str,
    *,
    enabled: bool,
    retention_days: int | None,
) -> dict:
    patched = client.patch(
        f"/entities/{entity_id}",
        json={
            "change_log_enabled": enabled,
            "change_log_retention_days": retention_days,
        },
    )
    assert patched.status_code == 200, patched.text
    return patched.json()["entity"]


def _current(client: TestClient, entity_id: str) -> dict:
    detail = client.get(f"/entities/{entity_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["entity"]


def _stem_target(stem: str) -> str | None:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        name = conn.execute(
            text(
                "SELECT ref.relname FROM pg_class v "
                "JOIN pg_namespace n ON n.oid = v.relnamespace "
                "JOIN pg_rewrite rw ON rw.ev_class = v.oid "
                "JOIN pg_depend d ON d.objid = rw.oid AND d.deptype = 'n' "
                "JOIN pg_class ref ON ref.oid = d.refobjid AND ref.relkind = 'r' "
                "WHERE n.nspname = :schema AND v.relname = :stem AND ref.oid <> v.oid"
            ),
            {"schema": ENTITY_DATA_SCHEMA, "stem": stem},
        ).scalar()
    return None if name is None else str(name)


def _materialized_count(entity_id: str) -> int:
    from backend.entity.store import get_entity_store

    return sum(
        1
        for item in get_entity_store().list_all_versions(entity_id)
        if item.materialized_attributes
    )


def test_draft_save_does_not_change_the_effective_record_or_entries(
    client: TestClient,
) -> None:
    entity = _create(client, change_log_enabled=True, change_log_retention_days=14)
    published = _publish(client, entity)
    assert published["job"]["status"] == "succeeded"
    physical = _physical(entity["table_name"], 1, entity["current_version"]["id"])
    _insert_sku(physical, "live")
    assert len(_entries(entity["id"])) == 1
    draft = _open(client, entity["id"])
    assert draft["change_log_enabled"] is True
    assert draft["change_log_retention_days"] == 14
    _patch_log(client, entity["id"], enabled=False, retention_days=14)
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is True
    assert effective.retention_days == 14
    assert len(_entries(entity["id"])) == 1
    assert _count_rows(physical) == 1
    assert _triggers(physical) == _ARMED
    assert _stem_target(entity["table_name"]) == physical
    assert _materialized_count(entity["id"]) == 1
    overview = _current(client, entity["id"])
    assert overview["current_version"]["publish_status"] == "unpublished"
    assert overview["effective_change_log"] == {
        "enabled": True,
        "retention_days": 14,
    }
    saved = client.get(
        f"/entities/{entity['id']}/versions/{draft['id']}"
    )
    assert saved.json()["version"]["change_log_enabled"] is False
    assert saved.json()["version"]["change_log_retention_days"] == 14


def test_publish_on_arms_every_table_and_does_not_invent_entries(
    client: TestClient,
) -> None:
    entity = _create(client)
    first = _publish(client, entity)
    assert first["job"]["status"] == "succeeded"
    v1 = entity["current_version"]["id"]
    old = _physical(entity["table_name"], 1, v1)
    _insert_sku(old, "already")
    assert _entries(entity["id"]) == []
    draft = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=None)
    current = _current(client, entity["id"])
    second = _publish(client, current)
    assert second["job"]["status"] == "succeeded"
    new = _physical(entity["table_name"], 2, draft["id"])
    assert _count_rows(old) == 1
    assert _count_rows(new) == 0
    assert _stem_target(entity["table_name"]) == new
    assert _entries(entity["id"]) == []
    assert _triggers(old) == _ARMED
    assert _triggers(new) == _ARMED
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is True
    assert effective.retention_days is None
    assert effective.applied_version_id == draft["id"]
    _insert_sku(new, "fresh")
    _insert_sku(old, "later")
    assert len(_entries(entity["id"])) == 2


def test_publish_off_deletes_every_entry_and_disarms(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.entity import change_log

    entity = _create(client, change_log_enabled=True, change_log_retention_days=14)
    _publish(client, entity)
    v1 = entity["current_version"]["id"]
    old = _physical(entity["table_name"], 1, v1)
    _insert_sku(old, "logged")
    assert len(_entries(entity["id"])) == 1
    draft = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=False, retention_days=14)
    seen: dict[str, object] = {}
    real = change_log.write_effective

    def spy(conn, record):
        from backend.entity.entity_db import get_entity_engine

        with get_entity_engine().connect() as other:
            seen["before"] = read_effective(other, entity["id"])
        return real(conn, record)

    monkeypatch.setattr(change_log, "write_effective", spy)
    current = _current(client, entity["id"])
    published = _publish(client, current)
    assert published["job"]["status"] == "succeeded"
    before = seen["before"]
    assert before is not None
    assert before.recording is True
    new = _physical(entity["table_name"], 2, draft["id"])
    assert _count_rows(old) == 1
    assert _count_rows(new) == 0
    assert _entries(entity["id"]) == []
    assert _triggers(old) == set()
    assert _triggers(new) == set()
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is False
    assert effective.retention_days == 14
    assert effective.applied_version_id == draft["id"]


def test_shorter_retention_deletes_entries_already_past_it(
    client: TestClient,
) -> None:
    from backend.core.time import FixedClock, set_clock

    entity = _create(client, change_log_enabled=True, change_log_retention_days=None)
    _publish(client, entity)
    old = _physical(entity["table_name"], 1, entity["current_version"]["id"])
    _insert_sku(old, "early")
    _insert_sku(old, "exact")
    _insert_sku(old, "inside")
    instant = datetime(2026, 6, 15, tzinfo=timezone.utc)
    set_clock(FixedClock(instant))
    cutoff = instant - timedelta(days=7)
    _set_occurred_at(entity["id"], 1, cutoff - timedelta(seconds=1))
    _set_occurred_at(entity["id"], 2, cutoff)
    _set_occurred_at(entity["id"], 3, cutoff + timedelta(days=1))
    draft = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=7)
    published = _publish(client, _current(client, entity["id"]))
    assert published["job"]["status"] == "succeeded"
    remaining = {entry.sequence for entry in _entries(entity["id"])}
    assert remaining == {2, 3}
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is True
    assert effective.retention_days == 7
    assert effective.applied_version_id == draft["id"]
    new = _physical(entity["table_name"], 2, draft["id"])
    assert _count_rows(old) == 3
    assert _count_rows(new) == 0
    assert _triggers(old) == _ARMED
    assert _triggers(new) == _ARMED


def test_never_expire_and_turning_recording_on_do_not_restore_entries(
    client: TestClient,
) -> None:
    from backend.core.time import FixedClock, set_clock
    from backend.entity.store import get_entity_store

    instant = datetime(2026, 8, 1, tzinfo=timezone.utc)
    set_clock(FixedClock(instant))
    entity = _create(client, change_log_enabled=True, change_log_retention_days=7)
    _publish(client, entity)
    old = _physical(entity["table_name"], 1, entity["current_version"]["id"])
    _insert_sku(old, "aged")
    _set_occurred_at(entity["id"], 1, instant - timedelta(days=100))
    _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=30)
    assert _publish(client, _current(client, entity["id"]))["job"]["status"] == "succeeded"
    assert {entry.sequence for entry in _entries(entity["id"])} == {1}
    _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=None)
    assert _publish(client, _current(client, entity["id"]))["job"]["status"] == "succeeded"
    assert {entry.sequence for entry in _entries(entity["id"])} == {1}
    assert _effective(entity["id"]).retention_days is None
    _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=3)
    assert _publish(client, _current(client, entity["id"]))["job"]["status"] == "succeeded"
    assert _entries(entity["id"]) == []
    _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=None)
    assert _publish(client, _current(client, entity["id"]))["job"]["status"] == "succeeded"
    assert _entries(entity["id"]) == []
    _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=False, retention_days=7)
    assert _publish(client, _current(client, entity["id"]))["job"]["status"] == "succeeded"
    assert _entries(entity["id"]) == []
    assert _effective(entity["id"]).recording is False
    assert _effective(entity["id"]).retention_days == 7
    again = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=True, retention_days=None)
    turned = _publish(client, _current(client, entity["id"]))
    assert turned["job"]["status"] == "succeeded"
    assert _entries(entity["id"]) == []
    head = _physical(entity["table_name"], again["version"], again["id"])
    _insert_sku(head, "after")
    entries = _entries(entity["id"])
    assert len(entries) == 1
    assert entries[0].sequence > 1
    stored = get_entity_store().get_version(again["id"])
    assert stored is not None
    assert stored.change_log_policy == "applied"
    second = client.post(
        f"/entities/{entity['id']}/versions/{again['id']}/publish"
    )
    assert second.status_code == 422
    assert second.json()["code"] == "ENTITY_NOT_UNPUBLISHED"


def test_failure_before_publish_leaves_the_effective_record_and_entries(
    client: TestClient,
) -> None:
    from backend.entity.table_port import PostgresEntityTablePort, bind_entity_table_port
    from backend.jobs.store import get_job_store

    entity = _create(client, change_log_enabled=True, change_log_retention_days=None)
    _publish(client, entity)
    old = _physical(entity["table_name"], 1, entity["current_version"]["id"])
    _insert_sku(old, "kept")
    assert len(_entries(entity["id"])) == 1
    draft = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=False, retention_days=None)

    class _CreateFails(PostgresEntityTablePort):
        def create_physical_table(self, *args, **kwargs):
            raise RuntimeError("create failed")

    bind_entity_table_port(_CreateFails())
    failed = client.post(
        f"/entities/{entity['id']}/versions/{draft['id']}/publish"
    )
    assert failed.status_code == 201, failed.text
    job = get_job_store().get(failed.json()["job"]["id"])
    assert job is not None
    assert job.status == "failed"
    version = client.get(f"/entities/{entity['id']}/versions/{draft['id']}")
    body = version.json()["version"]
    assert body["publish_status"] == "unpublished"
    assert body["change_log_enabled"] is False
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is True
    assert effective.retention_days is None
    assert effective.applied_version_id == entity["current_version"]["id"]
    assert len(_entries(entity["id"])) == 1
    assert _triggers(old) == _ARMED
    assert _materialized_count(entity["id"]) == 1
    assert _stem_target(entity["table_name"]) == old


def test_policy_failure_after_publish_is_retried_without_another_head(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.entity import change_log
    from backend.entity.store import get_entity_store
    from backend.jobs.store import get_job_store

    entity = _create(client, change_log_enabled=True, change_log_retention_days=None)

    def boom(conn, record):
        del conn, record
        raise RuntimeError("policy write failed")

    monkeypatch.setattr(change_log, "write_effective", boom)
    failed = _publish(client, entity)
    job = get_job_store().get(failed["job"]["id"])
    assert job is not None
    assert job.status == "failed"
    version_id = entity["current_version"]["id"]
    stored = get_entity_store().get_version(version_id)
    assert stored is not None
    assert stored.publish_status == "published"
    assert stored.change_log_policy == "pending"
    physical = _physical(entity["table_name"], 1, version_id)
    assert _count_rows(physical) == 0
    assert _triggers(physical) == set()
    assert _effective(entity["id"]) is None
    assert _materialized_count(entity["id"]) == 1
    _insert_sku(physical, "stored")
    monkeypatch.undo()
    retried = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert retried.status_code == 201, retried.text
    retry_job = get_job_store().get(retried.json()["job"]["id"])
    assert retry_job is not None
    assert retry_job.status == "succeeded"
    assert retry_job.result["action"] == "change_log_policy"
    stored = get_entity_store().get_version(version_id)
    assert stored is not None
    assert stored.publish_status == "published"
    assert stored.change_log_policy == "applied"
    assert _materialized_count(entity["id"]) == 1
    assert _count_rows(physical) == 1
    assert _triggers(physical) == _ARMED
    assert _entries(entity["id"]) == []
    effective = _effective(entity["id"])
    assert effective is not None
    assert effective.recording is True
    assert effective.retention_days is None
    assert effective.applied_version_id == version_id
    again = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert again.status_code == 422
    assert again.json()["code"] == "ENTITY_NOT_UNPUBLISHED"


def test_open_version_copies_the_effective_record_not_the_draft_columns(
    client: TestClient,
) -> None:
    from backend.entity.entity_db import get_entity_engine

    entity = _create(client, change_log_enabled=True, change_log_retention_days=9)
    _publish(client, entity)
    with get_entity_engine().begin() as conn:
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity["id"],
                recording=True,
                retention_days=21,
                applied_version_id=None,
            ),
        )
    draft = _open(client, entity["id"])
    assert draft["change_log_enabled"] is True
    assert draft["change_log_retention_days"] == 21
    previous = client.get(
        f"/entities/{entity['id']}/versions/{entity['current_version']['id']}"
    )
    assert previous.json()["version"]["change_log_enabled"] is True
    assert previous.json()["version"]["change_log_retention_days"] == 9

    other = _create(client, change_log_enabled=True, change_log_retention_days=9)
    _publish(client, other)
    with get_entity_engine().begin() as conn:
        conn.execute(
            text(
                f"DELETE FROM {qualified_table(CHANGE_LOG_SCHEMA, 'effective')} "
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": other["id"]},
        )
    missing = _open(client, other["id"])
    assert missing["change_log_enabled"] is False
    assert missing["change_log_retention_days"] is None
    kept = client.get(
        f"/entities/{other['id']}/versions/{other['current_version']['id']}"
    )
    assert kept.json()["version"]["change_log_enabled"] is True
    assert kept.json()["version"]["change_log_retention_days"] == 9


def test_preview_names_a_deletion_only_for_the_two_effects(
    client: TestClient,
) -> None:
    entity = _create(client, change_log_enabled=True, change_log_retention_days=30)
    _publish(client, entity)
    draft = _open(client, entity["id"])
    _patch_log(client, entity["id"], enabled=False, retention_days=30)

    def effect() -> str:
        preview = client.post(
            f"/entities/{entity['id']}/versions/{draft['id']}/publish/preview"
        )
        assert preview.status_code == 200, preview.text
        return preview.json()["change_log_effect"]

    assert effect() == "delete_all"
    _patch_log(client, entity["id"], enabled=True, retention_days=7)
    assert effect() == "delete_expired"
    _patch_log(client, entity["id"], enabled=True, retention_days=30)
    assert effect() == "none"
    _patch_log(client, entity["id"], enabled=True, retention_days=None)
    assert effect() == "none"
    _patch_log(client, entity["id"], enabled=True, retention_days=90)
    assert effect() == "none"
