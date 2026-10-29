"""Change-log sequence page on the entity database.

The read is the list the console tab calls. Entries are inserted directly so
sequence, time, and source are known literals. The trigger is not the surface.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from backend.core.config import reset_settings_cache
from backend.core.time import format_instant
from backend.entity.change_log import (
    ChangeLogTable,
    ensure_shared_relations,
    read_change_log,
)
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.ids import new_entity_id
from backend.entity.records import AttributeRecord
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_WHEN = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_SKU = (
    AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        business_key=True,
        max_length=32,
    ),
)


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
def change_log_database():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_clog6") as urls:
        previous = os.environ.get("ENTITY_DATABASE_URL")
        os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
        reset_settings_cache()
        reset_entity_engine()
        try:
            yield urls
        finally:
            reset_entity_engine()
            if previous is None:
                os.environ.pop("ENTITY_DATABASE_URL", None)
            else:
                os.environ["ENTITY_DATABASE_URL"] = previous
            reset_settings_cache()


def _table(name: str = "widget__v1__abcdef0123456789") -> ChangeLogTable:
    return ChangeLogTable(
        physical_table=f'"entity_data"."{name}"',
        attributes=_SKU,
        reference_snapshots={},
        business_key="sku",
    )


def _seed(engine: Engine, entity_id: str, count: int) -> None:
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        for seq in range(1, count + 1):
            _insert(
                conn,
                entity_id,
                sequence=seq,
                physical=_table().physical_table,
                operation="insert",
                image={"after": {"row_id": seq, "sku": f"S{seq}"}},
            )


def _insert(
    conn: Connection,
    entity_id: str,
    *,
    sequence: int,
    physical: str,
    operation: str,
    image: dict[str, object],
    occurred_at: datetime = _WHEN,
    source: str | None = None,
    subject: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO entity_change_log.entry ("
            "entity_id, physical_table, operation, seq, occurred_at, "
            "source, subject, image"
            ") VALUES ("
            ":entity_id, :physical, :operation, :seq, :occurred_at, "
            ":source, :subject, CAST(:image AS jsonb)"
            ")"
        ),
        {
            "entity_id": entity_id,
            "physical": physical,
            "operation": operation,
            "seq": sequence,
            "occurred_at": occurred_at,
            "source": source,
            "subject": subject,
            "image": json.dumps(image),
        },
    )


def test_first_page_is_the_fifty_newest_and_the_next_page_is_older(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    _seed(engine, entity_id, 55)
    table = _table()
    with engine.begin() as conn:
        first = read_change_log(conn, entity_id, [table])
        assert [item.sequence for item in first.items] == list(range(55, 5, -1))
        assert first.limit == 50
        assert first.next_before_sequence == 6
        second = read_change_log(
            conn, entity_id, [table], before_sequence=first.next_before_sequence
        )
    assert [item.sequence for item in second.items] == [5, 4, 3, 2, 1]
    assert second.next_before_sequence is None


def test_next_page_skips_a_missing_sequence(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _table()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        for seq in (10, 8, 7):
            _insert(
                conn,
                entity_id,
                sequence=seq,
                physical=table.physical_table,
                operation="insert",
                image={"after": {"row_id": seq, "sku": f"S{seq}"}},
            )
        page = read_change_log(conn, entity_id, [table], before_sequence=10)
    assert [item.sequence for item in page.items] == [8, 7]
    assert page.next_before_sequence is None


def test_filters_combine_and_a_missing_time_bound_stays_open(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _table()
    day = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    earlier = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity_id,
            sequence=5,
            physical=table.physical_table,
            operation="insert",
            image={"after": {"row_id": 5, "sku": "KEEP"}},
            occurred_at=day,
            source="user",
            subject="usr_a",
        )
        _insert(
            conn,
            entity_id,
            sequence=4,
            physical=table.physical_table,
            operation="update",
            image={"after": {"row_id": 4, "sku": "LATE"}, "changed": {"sku": "OLD"}},
            occurred_at=later,
            source="user",
            subject="usr_a",
        )
        _insert(
            conn,
            entity_id,
            sequence=3,
            physical=table.physical_table,
            operation="insert",
            image={"after": {"row_id": 3, "sku": "RUN"}},
            occurred_at=day,
            source="channel_run",
            subject="run_1",
        )
        _insert(
            conn,
            entity_id,
            sequence=2,
            physical=table.physical_table,
            operation="insert",
            image={"after": {"row_id": 2, "sku": "OTHER"}},
            occurred_at=day,
            source="user",
            subject="usr_b",
        )
        _insert(
            conn,
            entity_id,
            sequence=1,
            physical=table.physical_table,
            operation="delete",
            image={"before": {"row_id": 1, "sku": "EARLY"}},
            occurred_at=earlier,
            source="user",
            subject="usr_a",
        )
        matched = read_change_log(
            conn,
            entity_id,
            [table],
            operation="insert",
            source="user",
            subject="usr_a",
            occurred_from=day,
            occurred_to=day,
        )
        open_from = read_change_log(
            conn,
            entity_id,
            [table],
            operation="insert",
            source="user",
            subject="usr_a",
            occurred_to=day,
        )
        open_both = read_change_log(
            conn, entity_id, [table], operation="insert"
        )
    assert [item.sequence for item in matched.items] == [5]
    assert [item.sequence for item in open_from.items] == [5]
    assert [item.sequence for item in open_both.items] == [5, 3, 2]


def test_row_identity_matches_row_id_or_business_key_on_every_table(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    left = _table("widget__v1__aaaaaaaaaaaaaaaa")
    right = ChangeLogTable(
        physical_table='"entity_data"."widget__v2__bbbbbbbbbbbbbbbb"',
        attributes=(
            AttributeRecord(
                name="code",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
        ),
        reference_snapshots={},
        business_key="code",
    )
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity_id,
            sequence=3,
            physical=left.physical_table,
            operation="insert",
            image={"after": {"row_id": 7, "sku": "LEFT"}},
        )
        _insert(
            conn,
            entity_id,
            sequence=2,
            physical=right.physical_table,
            operation="insert",
            image={"after": {"row_id": 7, "code": "RIGHT"}},
        )
        _insert(
            conn,
            entity_id,
            sequence=1,
            physical=left.physical_table,
            operation="insert",
            image={"after": {"row_id": 8, "sku": "OTHER"}},
        )
        by_row = read_change_log(
            conn, entity_id, [left, right], row_identity="7"
        )
        by_left = read_change_log(
            conn, entity_id, [left, right], row_identity="LEFT"
        )
        by_right = read_change_log(
            conn, entity_id, [left, right], row_identity="RIGHT"
        )
    assert [(item.sequence, item.physical_table) for item in by_row.items] == [
        (3, left.physical_table),
        (2, right.physical_table),
    ]
    assert [item.sequence for item in by_left.items] == [3]
    assert [item.physical_table for item in by_left.items] == [left.physical_table]
    assert [item.sequence for item in by_right.items] == [2]


def test_one_entry_rebuilds_the_full_physical_row(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = ChangeLogTable(
        physical_table='"entity_data"."widget__v1__cccccccccccccccc"',
        attributes=(
            AttributeRecord(
                name="sku",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
            ),
            AttributeRecord(name="secret", type="text"),
        ),
        reference_snapshots={},
        business_key="sku",
    )
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity_id,
            sequence=3,
            physical=table.physical_table,
            operation="insert",
            image={"after": {"row_id": 1, "sku": "A", "secret": "hidden"}},
        )
        _insert(
            conn,
            entity_id,
            sequence=2,
            physical=table.physical_table,
            operation="update",
            image={
                "after": {"row_id": 1, "sku": "B", "secret": "hidden"},
                "changed": {"sku": "A"},
            },
        )
        _insert(
            conn,
            entity_id,
            sequence=1,
            physical=table.physical_table,
            operation="delete",
            image={"before": {"row_id": 1, "sku": "B", "secret": "hidden"}},
        )
        from backend.entity.change_log import read_change_log_entry

        inserted = read_change_log_entry(conn, entity_id, [table], 3)
        updated = read_change_log_entry(conn, entity_id, [table], 2)
        deleted = read_change_log_entry(conn, entity_id, [table], 1)
    assert inserted is not None and inserted.before is None
    assert inserted.after == {"row_id": 1, "sku": "A", "secret": "hidden"}
    assert updated is not None
    assert updated.before == {"row_id": 1, "sku": "A", "secret": "hidden"}
    assert updated.after == {"row_id": 1, "sku": "B", "secret": "hidden"}
    assert deleted is not None and deleted.after is None
    assert deleted.before == {"row_id": 1, "sku": "B", "secret": "hidden"}


def test_reference_column_decodes_when_the_snapshot_is_passed(
    change_log_database,
) -> None:
    del change_log_database
    from backend.entity.errors import EntityNotServing

    engine = get_entity_engine()
    entity_id = new_entity_id()
    attributes = (
        AttributeRecord(
            name="supplier",
            type="reference",
            target_entity_id="ent_other",
        ),
    )
    image = {"after": {"row_id": 4, "supplier": "ACME"}}
    with_snap = ChangeLogTable(
        physical_table='"entity_data"."widget__v1__dddddddddddddddd"',
        attributes=attributes,
        reference_snapshots={"supplier": {"type": "string", "max_length": 16}},
        business_key=None,
    )
    without = ChangeLogTable(
        physical_table=with_snap.physical_table,
        attributes=attributes,
        reference_snapshots={},
        business_key=None,
    )
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity_id,
            sequence=1,
            physical=with_snap.physical_table,
            operation="insert",
            image=image,
        )
        page = read_change_log(conn, entity_id, [with_snap])
        with pytest.raises(EntityNotServing):
            read_change_log(conn, entity_id, [without])
    assert page.items[0].after == {"row_id": 4, "supplier": "ACME"}


def test_unknown_physical_table_is_not_decoded_as_a_row(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _table()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity_id,
            sequence=1,
            physical='"entity_data"."other__v1__abcdef0123456789"',
            operation="insert",
            image={"after": {"row_id": 1, "sku": "KEEP"}},
        )
        with pytest.raises(ValueError, match="physical table is not loaded"):
            read_change_log(conn, entity_id, [table])


@pytest.fixture()
def client(change_log_database):
    del change_log_database
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
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
        reset_settings_cache()


def _create_logged(client: TestClient) -> dict:
    created = client.post(
        "/entities",
        json={
            "table_name": f"m{uuid.uuid4().hex[:10]}",
            "name": "Material",
            "description": "A stock-keeping material.",
            "change_log_enabled": True,
            "attributes": [
                {
                    "name": "sku",
                    "type": "string",
                    "required": True,
                    "unique": True,
                    "business_key": True,
                    "description": "SKU",
                    "config": {"max_length": 32},
                },
                {
                    "name": "secret",
                    "type": "text",
                    "required": False,
                    "unique": False,
                    "description": "Not a grant projection",
                    "config": {},
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["entity"]


def _publish(client: TestClient, entity: dict) -> dict:
    version_id = entity["current_version"]["id"]
    published = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert published.status_code == 201, published.text
    detail = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["version"]


def test_fractionless_occurred_to_includes_the_stored_second(
    client: TestClient,
) -> None:
    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    second = datetime(2026, 10, 28, 23, 40, 0, tzinfo=timezone.utc)
    within = second.replace(microsecond=739746)
    nxt = second + timedelta(seconds=1)
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=3,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 1, "sku": "EDGE", "secret": "a"}},
            occurred_at=second,
        )
        _insert(
            conn,
            entity["id"],
            sequence=2,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 2, "sku": "MID", "secret": "b"}},
            occurred_at=within,
        )
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 3, "sku": "NEXT", "secret": "c"}},
            occurred_at=nxt,
        )
    published = format_instant(within)
    assert published == "2026-10-28T23:40:00Z"
    covered = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"occurred_from": published, "occurred_to": published},
    )
    assert covered.status_code == 200, covered.text
    assert [item["sequence"] for item in covered.json()["items"]] == [3, 2]
    assert covered.json()["items"][0]["occurred_at"] == published
    exact = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"occurred_to": "2026-10-28T23:40:00.000000Z"},
    )
    assert exact.status_code == 200, exact.text
    assert [item["sequence"] for item in exact.json()["items"]] == [3]
    later = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"occurred_to": "2026-10-28T23:40:00.739746Z"},
    )
    assert later.status_code == 200, later.text
    assert [item["sequence"] for item in later.json()["items"]] == [3, 2]


def test_list_omits_images_and_detail_returns_the_physical_row(
    client: TestClient,
) -> None:
    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    me = client.get("/auth/me")
    assert me.status_code == 200, me.text
    user_id = me.json()["user"]["id"]
    engine = get_entity_engine()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=4,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 7, "sku": "LEFT", "secret": "hidden"}},
            source="user",
            subject=user_id,
        )
        _insert(
            conn,
            entity["id"],
            sequence=3,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 8, "sku": "GONE", "secret": "x"}},
            source="user",
            subject="usr_missing",
        )
        _insert(
            conn,
            entity["id"],
            sequence=2,
            physical=physical,
            operation="update",
            image={
                "after": {"row_id": 7, "sku": "LEFT", "secret": "hidden"},
                "changed": {},
            },
            source="channel_run",
            subject="run_9",
        )
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="delete",
            image={"before": {"row_id": 9, "sku": "OLD", "secret": "z"}},
        )
    listed = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"row_identity": "7"},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["limit"] == 50
    assert body["next_before_sequence"] is None
    assert [item["sequence"] for item in body["items"]] == [4, 2]
    for item in body["items"]:
        assert "before" not in item
        assert "after" not in item
        assert "secret" not in item
        assert item["row_id"] == 7
        assert item["business_key"] == "LEFT"
        assert item["physical_table"] == physical
    labels = {item["sequence"]: item for item in body["items"]}
    assert labels[4]["source"] == "user"
    assert labels[4]["subject"] == user_id
    assert labels[4]["subject_label"] == "Admin"
    missing = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"subject": "usr_missing"},
    )
    assert missing.status_code == 200, missing.text
    missed = missing.json()["items"]
    assert len(missed) == 1
    assert missed[0]["subject_label"] == "usr_missing"
    run = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"source": "channel_run"},
    )
    assert run.json()["items"][0]["subject"] == "run_9"
    assert run.json()["items"][0]["subject_label"] == "run_9"
    plain = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"source": "unattributed"},
    )
    assert plain.json()["items"][0]["source"] is None
    assert plain.json()["items"][0]["subject"] is None
    assert plain.json()["items"][0]["subject_label"] is None
    detail = client.get(f"/entities/{entity['id']}/change-log/4")
    assert detail.status_code == 200, detail.text
    entry = detail.json()
    assert entry["before"] is None
    assert entry["after"]["secret"] == "hidden"
    assert entry["after"]["sku"] == "LEFT"
    assert entry["subject_label"] == "Admin"


def test_dropped_table_entries_stay_on_the_list_and_the_detail(
    client: TestClient,
) -> None:
    from backend.jobs.store import get_job_store

    entity = _create_logged(client)
    first = _publish(client, entity)
    old_physical = f'"entity_data"."{first["table_name"]}"'
    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 201, opened.text
    current = client.get(f"/entities/{entity['id']}").json()["entity"]
    second = _publish(client, current)
    head_physical = f'"entity_data"."{second["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=old_physical,
            operation="insert",
            image={"after": {"row_id": 7, "sku": "LEFT", "secret": "hidden"}},
        )
        _insert(
            conn,
            entity["id"],
            sequence=2,
            physical=head_physical,
            operation="delete",
            image={"before": {"row_id": 8, "sku": "HEAD", "secret": "kept"}},
        )
    dropped = client.post(
        f"/entities/{entity['id']}/versions/{first['id']}/drop-table"
    )
    assert dropped.status_code == 201, dropped.text
    job = get_job_store().get(dropped.json()["job"]["id"])
    assert job is not None
    assert job.status == "succeeded"
    gone = client.get(f"/entities/{entity['id']}/versions/{first['id']}")
    assert gone.status_code == 200, gone.text
    assert gone.json()["version"]["alignment"]["table_present"] is False

    listed = client.get(f"/entities/{entity['id']}/change-log")
    assert listed.status_code == 200, listed.text
    assert [item["sequence"] for item in listed.json()["items"]] == [2, 1]
    by_key = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"row_identity": "LEFT"},
    )
    assert by_key.status_code == 200, by_key.text
    matched = by_key.json()["items"]
    assert [item["sequence"] for item in matched] == [1]
    assert matched[0]["business_key"] == "LEFT"
    assert matched[0]["row_id"] == 7
    assert matched[0]["physical_table"] == old_physical
    assert "before" not in matched[0]
    assert "after" not in matched[0]

    old = client.get(f"/entities/{entity['id']}/change-log/1")
    assert old.status_code == 200, old.text
    assert old.json()["before"] is None
    assert old.json()["after"] == {
        "row_id": 7,
        "sku": "LEFT",
        "secret": "hidden",
    }
    head = client.get(f"/entities/{entity['id']}/change-log/2")
    assert head.status_code == 200, head.text
    assert head.json()["after"] is None
    assert head.json()["before"]["sku"] == "HEAD"
    assert head.json()["physical_table"] == head_physical


def test_published_entity_exposes_recording_without_the_draft_facts(
    client: TestClient,
) -> None:
    entity = _create_logged(client)
    _publish(client, entity)
    detail = client.get(f"/entities/{entity['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()["entity"]
    assert body["change_log_recording"] is True
    assert "effective_change_log" not in body
    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 201, opened.text
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_enabled": False},
    )
    assert patched.status_code == 200, patched.text
    draft = client.get(
        f"/entities/{entity['id']}/versions/{opened.json()['version']['id']}"
    )
    assert draft.json()["version"]["change_log_enabled"] is False
    again = client.get(f"/entities/{entity['id']}")
    assert again.json()["entity"]["change_log_recording"] is True
    assert again.json()["entity"]["effective_change_log"]["enabled"] is True


def test_change_log_read_requires_data_read(client: TestClient) -> None:
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.main import app

    entity = _create_logged(client)
    role = create_role(
        get_role_store(),
        key="entity_editor",
        name="Entity editor",
        permissions=["console:access", "entity:read", "entity:write"],
    )
    get_user_store().create_user(
        account="editor",
        display_name="Editor",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as editor:
        login = editor.post(
            "/auth/login", json={"account": "editor", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        listed = editor.get(f"/entities/{entity['id']}/change-log")
        assert listed.status_code == 403
        detail = editor.get(f"/entities/{entity['id']}/change-log/1")
        assert detail.status_code == 403
        patched = editor.patch(
            f"/entities/{entity['id']}",
            json={"name": "Material renamed"},
        )
        assert patched.status_code == 200, patched.text
