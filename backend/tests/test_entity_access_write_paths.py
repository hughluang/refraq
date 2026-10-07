"""Data-plane connection routing, written-row presentation, and write locators.

Fake connections record SQL so the checks run without PostgreSQL.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.security import hash_password  # noqa: E402
from backend.admin.system_parameters import (  # noqa: E402
    is_registry_frozen,
    register_parameters,
)
from backend.admin.user_store import UserRecord, get_user_store  # noqa: E402
from backend.entity.access import enforce  # noqa: E402
from backend.entity.access import plan as access_plan  # noqa: E402
from backend.entity.access.enforce import (  # noqa: E402
    begin_data,
    definition_allows,
    read_context,
)
from backend.entity.access.errors import EntityAccessWriteDenied  # noqa: E402
from backend.entity.access.service import (  # noqa: E402
    create_grant,
    create_profile,
    put_ladder,
)
from backend.entity.access.views import rebuild_entity_views  # noqa: E402
from backend.entity.data import sql as data_sql  # noqa: E402
from backend.entity.data.service import (  # noqa: E402
    create_row,
    delete_where_rows,
    get_row,
    update_row,
    update_where_rows,
    upsert_one,
)
from backend.entity.errors import EntityRequestInvalid, EntityRowInvalid  # noqa: E402
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED  # noqa: E402
from backend.entity.parameters import ENTITY_PARAMETER_SPECS  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402

RAW = "raw-secret-1234"


@pytest.fixture(autouse=True)
def _entity_parameters() -> None:
    if not is_registry_frozen():
        register_parameters(ENTITY_PARAMETER_SPECS, group_order=("entity_access",))


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0][0]

    def all(self):
        return list(self._rows)


class _Conn:
    def __init__(self, log: list[str], answers: list[list[tuple[Any, ...]]]) -> None:
        self._log = log
        self._answers = answers

    def execute(self, statement, params=None):
        self._log.append(str(statement))
        return _Result(self._answers.pop(0) if self._answers else [])


class _Channels:
    """Owner and reader SQL recorded separately; answers are consumed in order."""

    def __init__(self) -> None:
        self.owner: list[str] = []
        self.reader: list[str] = []
        self.owner_answers: list[list[tuple[Any, ...]]] = []
        self.reader_answers: list[list[tuple[Any, ...]]] = []


@pytest.fixture()
def channels(monkeypatch: pytest.MonkeyPatch) -> _Channels:
    found = _Channels()

    @contextmanager
    def _owner():
        yield _Conn(found.owner, found.owner_answers)

    @contextmanager
    def _reader(ctx=None):
        found.reader.append("SET app.ctx")
        yield _Conn(found.reader, found.reader_answers)

    monkeypatch.setattr(data_sql, "entity_connection", _owner)
    monkeypatch.setattr(data_sql, "entity_read_connection", _reader)
    return found


def _masked_entity() -> tuple[UserRecord, str]:
    """``sku`` (business key) and ``note`` clear, ``secret`` masked, one read/write grant."""
    now = datetime.now(timezone.utc)
    table = f"wp_{uuid.uuid4().hex[:8]}"
    attrs = [
        AttributeRecord(
            name="sku",
            type="string",
            max_length=32,
            unique=True,
            business_key=True,
            attribute_id="att_sku",
        ),
        AttributeRecord(name="note", type="string", max_length=32, attribute_id="att_note"),
        AttributeRecord(
            name="secret",
            type="string",
            max_length=32,
            unique=True,
            attribute_id="att_secret",
        ),
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=table,
        name="Probe",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    stored = []
    for attr in attrs:
        item = attribute_to_dict(attr)
        item["attribute_id"] = attr.attribute_id
        stored.append(item)
    get_entity_store().create_entity(
        entity,
        EntityVersionRecord(
            id=new_version_id(),
            entity_id=entity.id,
            version=1,
            attributes=attrs,
            materialized_attributes=stored,
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    user = get_user_store().create_user(
        account=f"wp_{uuid.uuid4().hex[:8]}",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=None,
        status="active",
    )
    put_ladder(
        entity.id,
        "att_secret",
        [
            {"key": "clear", "mode": "clear"},
            {"key": "last4", "mode": {"type": "partial", "keep_first": 0, "keep_last": 4}},
        ],
        actor_user_id=user.id,
        actor_token_id=None,
    )
    profile = create_profile(
        entity.id,
        key="masked",
        name="Masked",
        description=None,
        columns=[
            {"attribute_id": "att_sku", "level": "clear"},
            {"attribute_id": "att_note", "level": "clear"},
            {"attribute_id": "att_secret", "level": "last4"},
        ],
        actor_user_id=user.id,
        actor_token_id=None,
    )
    create_grant(
        entity.id,
        subject={"type": "user", "id": user.id},
        profile_id=profile["profile"]["id"],
        row_rule=None,
        actions=["read", "write"],
        status="active",
        valid_until=None,
        actor_user_id=user.id,
        actor_token_id=None,
    )
    rebuild_entity_views(entity.id)
    return user, table


def test_reads_use_the_reader_connection_and_the_profile_view(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.reader_answers.append([(7, "A1", "n", "**34")])
    row = get_row(table, {"row_id": 7}, user)
    assert row == {"row_id": 7, "sku": "A1", "note": "n", "secret": "**34"}
    assert channels.owner == []
    assert channels.reader[0] == "SET app.ctx"
    assert '"entity_access".' in channels.reader[1]
    assert "entity_data" not in channels.reader[1]


def test_create_presents_the_row_through_the_read_view(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.owner_answers.append([(7,)])
    channels.reader_answers.append([(7, "A1", "n", "**34")])
    row = create_row(table, {"values": {"sku": "A1", "note": "n"}}, user)
    assert row == {"row_id": 7, "sku": "A1", "note": "n", "secret": "**34"}
    assert channels.owner[0].startswith("INSERT INTO")
    assert channels.owner[0].endswith('RETURNING "row_id"')
    assert '"entity_access".' in channels.reader[1]


def test_update_locks_the_pre_image_and_writes_by_row_id(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.owner_answers.append([(7, "A1", "n", RAW)])
    channels.reader_answers.append([(7, "A1", "n2", "**34")])
    row = update_row(table, {"row_id": 7, "values": {"note": "n2"}}, user)
    assert row == {"row_id": 7, "sku": "A1", "note": "n2", "secret": "**34"}
    assert RAW not in str(row)
    select, update = channels.owner
    assert select.endswith("FOR UPDATE")
    assert "entity_data" in select
    assert update.startswith("UPDATE") and '"row_id" = ANY(:ids)' in update


def test_upsert_returns_the_read_view_not_the_stored_values(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.owner_answers.append([(7, "A1", "n", RAW)])
    channels.reader_answers.append([(7, "A1", "n2", "**34")])
    row, created = upsert_one(table, {"key": "sku", "values": {"sku": "A1", "note": "n2"}}, user)
    assert created is False
    assert RAW not in str(row)
    assert channels.owner[0].endswith("FOR UPDATE")


def test_update_where_locks_rows_and_mutates_by_id(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.owner_answers.append([(7, "A1", "n", RAW)])
    channels.owner_answers.append([(1,)])
    result = update_where_rows(
        table,
        {"filters": {"field": "sku", "op": "eq", "value": "A1"}, "set": {"note": "n2"}},
        user,
    )
    assert result == {"affected": 1}
    select, update = channels.owner
    assert "FOR UPDATE" in select
    assert '"row_id" = ANY(:ids)' in update


def test_masked_column_is_not_writable(channels: _Channels) -> None:
    user, table = _masked_entity()
    channels.owner_answers.append([(7, "A1", "n", RAW)])
    with pytest.raises(EntityAccessWriteDenied):
        update_row(table, {"row_id": 7, "values": {"secret": "x"}}, user)


def test_write_filters_and_locators_cannot_name_masked_columns(channels: _Channels) -> None:
    user, table = _masked_entity()
    probe = {"field": "secret", "op": "eq", "value": RAW}
    with pytest.raises(EntityRowInvalid, match="Unknown filter field 'secret'"):
        delete_where_rows(table, {"filters": probe}, user)
    with pytest.raises(EntityRowInvalid, match="Unknown filter field 'secret'"):
        update_where_rows(table, {"filters": probe, "set": {"note": "n"}}, user)
    with pytest.raises(EntityRowInvalid, match="is not an upsert_key"):
        upsert_one(table, {"key": "secret", "values": {"secret": RAW}}, user)
    assert channels.owner == []


def test_requests_do_not_load_every_user(
    channels: _Channels, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, table = _masked_entity()

    def _everyone():
        raise AssertionError("a data request loaded the whole User population")

    monkeypatch.setattr(access_plan, "_population", _everyone)
    channels.reader_answers.append([(7, "A1", "n", "**34")])
    assert get_row(table, {"row_id": 7}, user)["row_id"] == 7
    assert definition_allows(user, get_entity_store().get_entity_by_table_name(table).id)[0]


def test_read_context_failure_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    user, table = _masked_entity()
    access = begin_data(table, user, {}, action="read", for_write=False)

    class _Persistent:
        store_backend = "persistent"

    def _broken_ring():
        raise RuntimeError("acl key unavailable")

    monkeypatch.setattr(enforce, "get_settings", lambda: _Persistent())
    monkeypatch.setattr(enforce, "_signing_ring", _broken_ring)
    with pytest.raises(RuntimeError, match="acl key unavailable"):
        read_context(access)


def test_update_rejects_filters(channels: _Channels) -> None:
    user, table = _masked_entity()
    with pytest.raises(EntityRequestInvalid):
        update_row(table, {"row_id": 7, "filters": {}, "values": {"note": "n"}}, user)
