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
    open_ended = client.get(f"/entities/{entity['id']}/change-log")
    assert open_ended.status_code == 200, open_ended.text
    assert [item["sequence"] for item in open_ended.json()["items"]] == [3, 2, 1]
    assert open_ended.json()["next_cursor"] is None


def test_list_and_detail_share_the_projected_event(
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
            sequence=5,
            physical=physical,
            operation="update",
            image={
                "after": {"row_id": 7, "sku": "LEFT", "secret": "equal-secret-token"},
                "changed": {},
            },
        )
        _insert(
            conn,
            entity["id"],
            sequence=2,
            physical=physical,
            operation="update",
            image={
                "after": {"row_id": 7, "sku": "LEFT", "secret": "hidden"},
                "changed": {"sku": "PREV"},
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
        params={"version_id": version["id"], "row_id": "7"},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["limit"] == 50
    assert body["next_cursor"] is None
    assert "next_before_sequence" not in body
    assert "physical_table" not in listed.text
    assert [item["sequence"] for item in body["items"]] == [4, 2]
    assert "equal-secret-token" not in listed.text
    for item in body["items"]:
        assert item["version_id"] == version["id"]
        assert item["version_number"] == version["version"]
        assert "row_id" not in item
        assert "business_key" not in item
        assert "physical_table" not in item
    labels = {item["sequence"]: item for item in body["items"]}
    assert labels[4]["before"] == {"state": "absent"}
    assert "values" not in labels[4]["before"]
    assert labels[4]["after"]["state"] == "visible"
    assert labels[4]["after"]["values"]["row_id"] == 7
    assert labels[4]["after"]["values"]["sku"] == "LEFT"
    assert labels[4]["after"]["values"]["secret"] == "hidden"
    assert labels[2]["before"]["state"] == "visible"
    assert labels[2]["before"]["values"]["sku"] == "PREV"
    assert labels[2]["after"]["state"] == "visible"
    assert labels[2]["after"]["values"]["sku"] == "LEFT"
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
    assert entry["before"] == {"state": "absent"}
    assert entry["after"]["state"] == "visible"
    assert entry["after"]["values"]["secret"] == "hidden"
    assert entry["after"]["values"]["sku"] == "LEFT"
    assert entry["version_id"] == version["id"]
    assert entry["subject_label"] == "Admin"
    assert "physical_table" not in detail.text
    hidden = client.get(f"/entities/{entity['id']}/change-log/5")
    assert hidden.status_code == 404, hidden.text
    assert hidden.json()["code"] == "ENTITY_NOT_FOUND"
    assert hidden.json()["detail"] == "Business Entity not found"
    assert "equal-secret-token" not in hidden.text
    assert "physical_table" not in hidden.text


def test_change_log_lookup_is_a_business_key_or_one_version_row(
    client: TestClient,
) -> None:
    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        for sequence in range(1, 52):
            _insert(
                conn,
                entity["id"],
                sequence=sequence,
                physical=physical,
                operation="insert",
                image={"after": {"row_id": 7, "sku": "LEFT", "secret": "v"}},
            )
        _insert(
            conn,
            entity["id"],
            sequence=60,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 8, "sku": "OTHER", "secret": "v"}},
        )
    by_key = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"row_identity": "LEFT"},
    )
    assert by_key.status_code == 200, by_key.text
    assert [item["sequence"] for item in by_key.json()["items"]] == list(
        range(51, 1, -1)
    )
    cursor = by_key.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor
    rebound = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor},
    )
    assert rebound.status_code == 422, rebound.text
    assert rebound.json()["code"] == "REQUEST_INVALID"
    assert rebound.json()["detail"] == "Request validation failed"
    assert "LEFT" not in rebound.text
    rest = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "row_identity": "LEFT"},
    )
    assert rest.status_code == 200, rest.text
    assert [item["sequence"] for item in rest.json()["items"]] == [1]
    by_row_text = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"row_identity": "7"},
    )
    assert by_row_text.status_code == 200, by_row_text.text
    assert by_row_text.json()["items"] == []
    assert by_row_text.json()["next_cursor"] is None
    by_version_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"version_id": version["id"], "row_id": "7"},
    )
    assert by_version_row.status_code == 200, by_version_row.text
    assert by_version_row.json()["items"][0]["sequence"] == 51
    assert "row_id" not in by_version_row.json()["items"][0]
    assert "business_key" not in by_version_row.json()["items"][0]
    bound = by_version_row.json()["next_cursor"]
    assert isinstance(bound, str) and bound
    omit_version = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": bound, "row_id": "7"},
    )
    assert omit_version.status_code == 422, omit_version.text
    assert omit_version.json()["code"] == "REQUEST_INVALID"
    assert omit_version.json()["detail"] == "Request validation failed"
    assert "items" not in omit_version.json()
    omit_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": bound, "version_id": version["id"]},
    )
    assert omit_row.status_code == 422, omit_row.text
    assert omit_row.json()["code"] == "REQUEST_INVALID"
    assert omit_row.json()["detail"] == "Request validation failed"
    assert "items" not in omit_row.json()
    stacked = client.get(
        f"/entities/{entity['id']}/change-log",
        params={
            "cursor": bound,
            "version_id": version["id"],
            "row_id": "7",
            "row_identity": "LEFT",
        },
    )
    assert stacked.status_code == 422, stacked.text
    assert stacked.json()["code"] == "REQUEST_INVALID"
    assert stacked.json()["detail"] == "Request validation failed"
    assert "items" not in stacked.json()
    changed_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": bound, "version_id": version["id"], "row_id": "8"},
    )
    assert changed_row.status_code == 422, changed_row.text
    assert changed_row.json()["code"] == "REQUEST_INVALID"
    changed_operation = client.get(
        f"/entities/{entity['id']}/change-log",
        params={
            "cursor": bound,
            "version_id": version["id"],
            "row_id": "7",
            "operation": "delete",
        },
    )
    assert changed_operation.status_code == 422, changed_operation.text
    assert changed_operation.json()["code"] == "REQUEST_INVALID"
    other = client.get(f"/entities/{entity['id']}/change-log/60")
    assert other.status_code == 200, other.text
    assert other.json()["after"]["values"]["sku"] == "OTHER"
    lone_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"row_id": "7"},
    )
    assert lone_row.status_code == 422, lone_row.text
    assert lone_row.json()["code"] == "ENTITY_CHANGE_LOG_QUERY_UNSUPPORTED"
    assert lone_row.json()["detail"] == "This change-log query is not supported."
    assert "LEFT" not in lone_row.text
    assert "60" not in lone_row.text
    lone_version = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"version_id": version["id"]},
    )
    assert lone_version.status_code == 422, lone_version.text
    assert lone_version.json()["code"] == "ENTITY_CHANGE_LOG_QUERY_UNSUPPORTED"
    both = client.get(
        f"/entities/{entity['id']}/change-log",
        params={
            "row_identity": "LEFT",
            "version_id": version["id"],
            "row_id": "7",
        },
    )
    assert both.status_code == 422, both.text
    assert both.json()["detail"] == "This change-log query is not supported."
    bad_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"version_id": version["id"], "row_id": "nope"},
    )
    assert bad_row.status_code == 422, bad_row.text
    assert bad_row.json()["code"] == "REQUEST_INVALID"
    assert bad_row.json()["detail"] == "Request validation failed"


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
    assert "physical_table" not in by_key.text
    assert matched[0]["version_id"] == first["id"]
    assert matched[0]["version_number"] == first["version"]
    assert "row_id" not in matched[0]
    assert "business_key" not in matched[0]
    assert matched[0]["before"] == {"state": "absent"}
    assert matched[0]["after"]["state"] == "visible"
    assert matched[0]["after"]["values"]["sku"] == "LEFT"
    assert matched[0]["after"]["values"]["row_id"] == 7

    old = client.get(f"/entities/{entity['id']}/change-log/1")
    assert old.status_code == 200, old.text
    assert old.json()["before"] == {"state": "absent"}
    assert old.json()["after"]["state"] == "visible"
    assert old.json()["after"]["values"]["sku"] == "LEFT"
    assert old.json()["after"]["values"]["secret"] == "hidden"
    assert old.json()["version_id"] == first["id"]
    assert "physical_table" not in old.text
    head = client.get(f"/entities/{entity['id']}/change-log/2")
    assert head.status_code == 200, head.text
    assert head.json()["after"] == {"state": "absent"}
    assert head.json()["before"]["state"] == "visible"
    assert head.json()["before"]["values"]["sku"] == "HEAD"
    assert head.json()["version_id"] == second["id"]
    assert "physical_table" not in head.text


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
        assert listed.json()["code"] == "AUTH_FORBIDDEN"
        detail = editor.get(f"/entities/{entity['id']}/change-log/1")
        assert detail.status_code == 403
        assert detail.json()["code"] == "AUTH_FORBIDDEN"
        unknown = editor.get("/entities/ent_does_not_exist/change-log")
        assert unknown.status_code == 403
        assert unknown.json()["code"] == "AUTH_FORBIDDEN"
        patched = editor.patch(
            f"/entities/{entity['id']}",
            json={"name": "Material renamed"},
        )
        assert patched.status_code == 200, patched.text


def _attribute_id(version: dict, name: str) -> str:
    for item in version["attributes"]:
        if item["name"] == name:
            found = item["attribute_id"]
            assert isinstance(found, str) and found
            return found
    raise AssertionError(name)


def _fill_inserts(entity_id: str, physical: str, count: int) -> None:
    engine = get_entity_engine()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        for seq in range(1, count + 1):
            _insert(
                conn,
                entity_id,
                sequence=seq,
                physical=physical,
                operation="insert",
                image={"after": {"row_id": seq, "sku": f"S{seq}", "secret": "v"}},
            )


def test_opaque_cursor_pages_and_rejects_a_rebound_token(client: TestClient) -> None:
    from datetime import timedelta

    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.core.time import FixedClock, reset_clock, set_clock
    from backend.entity.access.context import CONTEXT_TTL_SEC
    from backend.entity.access.service import create_grant
    from backend.entity.access.store import get_access_store
    from backend.entity.access.views import rebuild_entity_views
    from backend.main import app

    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    _fill_inserts(entity["id"], physical, 55)
    first = client.get(f"/entities/{entity['id']}/change-log")
    assert first.status_code == 200, first.text
    page = first.json()
    assert [item["sequence"] for item in page["items"]] == list(range(55, 5, -1))
    assert page["limit"] == 50
    cursor = page["next_cursor"]
    assert isinstance(cursor, str) and cursor
    assert "next_before_sequence" not in page
    second = client.get(
        f"/entities/{entity['id']}/change-log", params={"cursor": cursor}
    )
    assert second.status_code == 200, second.text
    assert [item["sequence"] for item in second.json()["items"]] == [5, 4, 3, 2, 1]
    assert second.json()["next_cursor"] is None

    rebound_query = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "operation": "delete"},
    )
    assert rebound_query.status_code == 422, rebound_query.text
    assert rebound_query.json()["code"] == "REQUEST_INVALID"
    assert rebound_query.json()["detail"] == "Request validation failed"
    assert "items" not in rebound_query.json()
    rebound_key = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "row_identity": "S1"},
    )
    assert rebound_key.status_code == 422, rebound_key.text
    assert rebound_key.json()["code"] == "REQUEST_INVALID"
    assert rebound_key.json()["detail"] == "Request validation failed"
    rebound_row = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "version_id": version["id"], "row_id": "1"},
    )
    assert rebound_row.status_code == 422, rebound_row.text
    assert rebound_row.json()["code"] == "REQUEST_INVALID"
    half_pair = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "row_id": "1"},
    )
    assert half_pair.status_code == 422, half_pair.text
    assert half_pair.json()["code"] == "REQUEST_INVALID"
    assert half_pair.json()["detail"] == "Request validation failed"
    assert "items" not in half_pair.json()
    blank_lookup = client.get(
        f"/entities/{entity['id']}/change-log",
        params={"cursor": cursor, "row_identity": "", "version_id": "", "row_id": ""},
    )
    assert blank_lookup.status_code == 200, blank_lookup.text
    assert [item["sequence"] for item in blank_lookup.json()["items"]] == [
        5,
        4,
        3,
        2,
        1,
    ]
    other = _create_logged(client)
    _publish(client, other)
    rebound_entity = client.get(
        f"/entities/{other['id']}/change-log", params={"cursor": cursor}
    )
    assert rebound_entity.status_code == 422, rebound_entity.text
    assert rebound_entity.json()["detail"] == "Request validation failed"
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    damaged = client.get(
        f"/entities/{entity['id']}/change-log", params={"cursor": tampered}
    )
    assert damaged.status_code == 422, damaged.text
    assert "S1" not in damaged.text
    blank = client.get(
        f"/entities/{entity['id']}/change-log", params={"cursor": ""}
    )
    assert blank.status_code == 422, blank.text

    me = client.get("/auth/me")
    profile_id = next(
        item.profile_id
        for item in get_access_store().grants(entity["id"])
        if not item.locked
    )
    role = create_role(
        get_role_store(),
        key="entity_change_reader",
        name="Change reader",
        permissions=["console:access", "entity:data_read"],
    )
    reader = get_user_store().create_user(
        account="change-reader",
        display_name="Change reader",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    create_grant(
        entity["id"],
        subject={"type": "user", "id": reader.id},
        profile_id=profile_id,
        row_rule=None,
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=me.json()["user"]["id"],
        actor_token_id=None,
    )
    rebuild_entity_views(entity["id"])
    with TestClient(app) as other_user:
        login = other_user.post(
            "/auth/login", json={"account": "change-reader", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        stolen = other_user.get(
            f"/entities/{entity['id']}/change-log", params={"cursor": cursor}
        )
        assert stolen.status_code == 422, stolen.text
        assert stolen.json()["code"] == "REQUEST_INVALID"
        own = other_user.get(f"/entities/{entity['id']}/change-log")
        assert own.status_code == 200, own.text
        assert own.json()["items"][0]["sequence"] == 55

    set_clock(
        FixedClock(_WHEN + timedelta(days=4000, seconds=CONTEXT_TTL_SEC + 5))
    )
    try:
        expired = client.get(
            f"/entities/{entity['id']}/change-log", params={"cursor": cursor}
        )
        assert expired.status_code == 422, expired.text
        assert expired.json()["detail"] == "Request validation failed"
        assert "55" not in expired.json()["detail"]
    finally:
        reset_clock()


def test_empty_page_continues_until_the_range_is_exhausted(
    client: TestClient,
) -> None:
    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    engine = get_entity_engine()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        for seq in range(2, 52):
            _insert(
                conn,
                entity["id"],
                sequence=seq,
                physical=physical,
                operation="update",
                image={
                    "after": {"row_id": 1, "sku": "SAME", "secret": "same"},
                    "changed": {},
                },
            )
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 2, "sku": "KEPT", "secret": "kept"}},
        )
    first = client.get(f"/entities/{entity['id']}/change-log")
    assert first.status_code == 200, first.text
    assert first.json()["items"] == []
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor
    second = client.get(
        f"/entities/{entity['id']}/change-log", params={"cursor": cursor}
    )
    assert second.status_code == 200, second.text
    assert [item["sequence"] for item in second.json()["items"]] == [1]
    assert second.json()["items"][0]["after"]["values"]["sku"] == "KEPT"
    assert second.json()["next_cursor"] is None


def test_one_visible_side_is_returned_and_an_equal_update_is_not(
    client: TestClient,
) -> None:
    from backend.entity.access.service import create_grant, create_profile, update_grant
    from backend.entity.access.store import get_access_store
    from backend.entity.access.views import rebuild_entity_views

    created = client.post(
        "/entities",
        json={
            "table_name": f"q{uuid.uuid4().hex[:10]}",
            "name": "Quantity",
            "description": "A counted row.",
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
                    "name": "qty",
                    "type": "integer",
                    "required": False,
                    "unique": False,
                    "description": "Quantity",
                    "config": {},
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version = _publish(client, entity)
    qty_id = _attribute_id(version, "qty")
    sku_id = _attribute_id(version, "sku")
    me = client.get("/auth/me")
    user_id = me.json()["user"]["id"]
    # The published all-clear grant has no row rule. A second grant on that
    # profile would still open every row, so the caller holds only this one.
    profile = create_profile(
        entity["id"],
        key="counted",
        name="Counted",
        description=None,
        columns=[
            {"attribute_id": sku_id, "level": "clear"},
            {"attribute_id": qty_id, "level": "clear"},
        ],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    creator = next(
        item for item in get_access_store().grants(entity["id"]) if not item.locked
    )
    update_grant(
        entity["id"],
        creator.id,
        fields={"status"},
        profile_id=None,
        row_rule=None,
        actions=None,
        status="disabled",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity["id"],
        subject={"type": "user", "id": user_id},
        profile_id=profile["profile"]["id"],
        row_rule={"eq": {"attr": qty_id, "value": 5}},
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity["id"])
    physical = f'"entity_data"."{version["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=3,
            physical=physical,
            operation="update",
            image={
                "after": {"row_id": 9, "sku": "rise", "qty": 5},
                "changed": {"qty": 4},
            },
        )
        _insert(
            conn,
            entity["id"],
            sequence=2,
            physical=physical,
            operation="update",
            image={
                "after": {"row_id": 8, "sku": "equal-sku", "qty": 5},
                "changed": {},
            },
        )
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 7, "sku": "blocked", "qty": 1}},
        )
    listed = client.get(f"/entities/{entity['id']}/change-log")
    assert listed.status_code == 200, listed.text
    assert [item["sequence"] for item in listed.json()["items"]] == [3]
    shown = listed.json()["items"][0]
    assert shown["before"] == {"state": "unavailable"}
    assert "values" not in shown["before"]
    assert shown["after"]["state"] == "visible"
    assert shown["after"]["values"]["qty"] == 5
    assert shown["after"]["values"]["sku"] == "rise"
    assert "4" not in json.dumps(shown["before"])
    detail = client.get(f"/entities/{entity['id']}/change-log/3")
    assert detail.status_code == 200, detail.text
    assert detail.json()["before"] == {"state": "unavailable"}
    assert detail.json()["after"]["values"]["qty"] == 5
    assert '"qty": 4' not in detail.text
    assert '"qty":4' not in detail.text
    assert "blocked" not in detail.text
    assert "equal-sku" not in detail.text
    for sequence in (2, 1):
        missing = client.get(f"/entities/{entity['id']}/change-log/{sequence}")
        assert missing.status_code == 404, missing.text
        assert missing.json()["code"] == "ENTITY_NOT_FOUND"
        assert missing.json()["detail"] == "Business Entity not found"
    filtered = client.get(
        f"/entities/{entity['id']}/change-log", params={"operation": "insert"}
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["items"] == []
    assert filtered.json()["next_cursor"] is None


def test_withheld_marker_hides_the_clear_value(client: TestClient) -> None:
    from backend.entity.access.service import create_grant, create_profile, update_grant
    from backend.entity.access.store import get_access_store
    from backend.entity.access.views import rebuild_entity_views

    entity = _create_logged(client)
    version = _publish(client, entity)
    me = client.get("/auth/me")
    user_id = me.json()["user"]["id"]
    sku_id = _attribute_id(version, "sku")
    secret_id = _attribute_id(version, "secret")
    shown = create_profile(
        entity["id"],
        key="shown",
        name="Shown",
        description=None,
        columns=[
            {"attribute_id": sku_id, "level": "clear"},
            {"attribute_id": secret_id, "level": "clear"},
        ],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    hidden = create_profile(
        entity["id"],
        key="hidden",
        name="Hidden",
        description=None,
        columns=[{"attribute_id": sku_id, "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    grant = next(
        item for item in get_access_store().grants(entity["id"]) if not item.locked
    )
    update_grant(
        entity["id"],
        grant.id,
        fields={"status"},
        profile_id=None,
        row_rule=None,
        actions=None,
        status="disabled",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity["id"],
        subject={"type": "user", "id": user_id},
        profile_id=shown["profile"]["id"],
        row_rule={"eq": {"attr": sku_id, "value": "shown"}},
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    create_grant(
        entity["id"],
        subject={"type": "user", "id": user_id},
        profile_id=hidden["profile"]["id"],
        row_rule={"eq": {"attr": sku_id, "value": "withheld-row"}},
        actions=["read"],
        status="active",
        valid_until=None,
        actor_user_id=user_id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity["id"])
    physical = f'"entity_data"."{version["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={
                "after": {
                    "row_id": 4,
                    "sku": "withheld-row",
                    "secret": "hidden-value",
                }
            },
        )
    listed = client.get(f"/entities/{entity['id']}/change-log")
    assert listed.status_code == 200, listed.text
    values = listed.json()["items"][0]["after"]["values"]
    assert values["sku"] == "withheld-row"
    assert values["secret"] is None
    assert values["__withheld"] == ["secret"]
    assert "hidden-value" not in listed.text
    detail = client.get(f"/entities/{entity['id']}/change-log/1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["after"]["values"]["__withheld"] == ["secret"]
    assert "hidden-value" not in detail.text


def test_management_permissions_do_not_read_events(client: TestClient) -> None:
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.main import app

    entity = _create_logged(client)
    version = _publish(client, entity)
    physical = f'"entity_data"."{version["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            entity["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 1, "sku": "KEEP", "secret": "manager-secret"}},
        )
    role = create_role(
        get_role_store(),
        key="entity_manager_only",
        name="Entity manager",
        permissions=[
            "console:access",
            "entity:read",
            "entity:write",
            "entity:access_manage",
            "entity:data_read",
        ],
    )
    get_user_store().create_user(
        account="manager-only",
        display_name="Manager",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as manager:
        login = manager.post(
            "/auth/login", json={"account": "manager-only", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        visible = manager.get(f"/entities/{entity['id']}")
        assert visible.status_code == 200, visible.text
        listed = manager.get(f"/entities/{entity['id']}/change-log")
        assert listed.status_code == 404, listed.text
        assert listed.json()["code"] == "ENTITY_NOT_FOUND"
        assert "manager-secret" not in listed.text
        detail = manager.get(f"/entities/{entity['id']}/change-log/1")
        assert detail.status_code == 404, detail.text
        assert detail.json()["code"] == "ENTITY_NOT_FOUND"
        assert "manager-secret" not in detail.text


def test_pending_entity_does_not_block_another(client: TestClient) -> None:
    from backend.entity.access.store import get_access_store

    pending = _create_logged(client)
    _publish(client, pending)
    ready = _create_logged(client)
    ready_version = _publish(client, ready)
    physical = f'"entity_data"."{ready_version["table_name"]}"'
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        _insert(
            conn,
            ready["id"],
            sequence=1,
            physical=physical,
            operation="insert",
            image={"after": {"row_id": 1, "sku": "SERVED", "secret": "ok"}},
        )
    store = get_access_store()
    store.set_revision(pending["id"], store.revision(pending["id"]) + 1)
    waiting = client.get(f"/entities/{pending['id']}/change-log")
    assert waiting.status_code == 503, waiting.text
    assert waiting.json()["code"] == "ENTITY_ACCESS_PENDING"
    assert waiting.headers["retry-after"] == "1"
    served = client.get(f"/entities/{ready['id']}/change-log")
    assert served.status_code == 200, served.text
    assert served.json()["items"][0]["after"]["values"]["sku"] == "SERVED"


def test_combination_limit_is_a_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.entity.access.service import create_grant, create_profile
    from backend.entity.access.views import rebuild_entity_views

    entity = _create_logged(client)
    version = _publish(client, entity)
    me = client.get("/auth/me")
    user_id = me.json()["user"]["id"]
    sku_id = _attribute_id(version, "sku")
    first = create_profile(
        entity["id"],
        key="first",
        name="First",
        description=None,
        columns=[{"attribute_id": sku_id, "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    second = create_profile(
        entity["id"],
        key="second",
        name="Second",
        description=None,
        columns=[{"attribute_id": sku_id, "level": "clear"}],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    for profile, key in ((first, "one"), (second, "two")):
        create_grant(
            entity["id"],
            subject={"type": "user", "id": user_id},
            profile_id=profile["profile"]["id"],
            row_rule=None,
            actions=["read"],
            status="active",
            valid_until=None,
            actor_user_id=user_id,
            actor_token_id=None,
        )
        del key
    rebuild_entity_views(entity["id"])
    monkeypatch.setattr(
        "backend.entity.access.plan.max_profile_combinations", lambda: 0
    )
    listed = client.get(f"/entities/{entity['id']}/change-log")
    assert listed.status_code == 409, listed.text
    assert listed.json()["code"] == "ENTITY_ACCESS_COMBINATION_LIMIT"
    detail = client.get(f"/entities/{entity['id']}/change-log/1")
    assert detail.status_code == 409, detail.text
    assert detail.json()["code"] == "ENTITY_ACCESS_COMBINATION_LIMIT"


def test_database_error_is_not_an_empty_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from backend.main import app

    entity = _create_logged(client)
    _publish(client, entity)

    def _timeout(*_args: object, **_kwargs: object) -> None:
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("canceling statement due to statement timeout"),
        )

    monkeypatch.setattr("backend.entity.routers.entities.read_history", _timeout)
    # Starlette still raises after the 500 handler so a server can log it.
    # raise_server_exceptions hides that response; the handler itself is unchanged.
    with TestClient(app, raise_server_exceptions=False) as quiet:
        login = quiet.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        listed = quiet.get(f"/entities/{entity['id']}/change-log")
        assert listed.status_code == 500, listed.text
        assert listed.json()["code"] == "INTERNAL_ERROR"
        assert "next_cursor" not in listed.json()
        assert "items" not in listed.json()
        assert "statement timeout" not in listed.text
        detail = quiet.get(f"/entities/{entity['id']}/change-log/1")
        assert detail.status_code == 500, detail.text
        assert detail.json()["code"] == "INTERNAL_ERROR"
        assert "statement timeout" not in detail.text
