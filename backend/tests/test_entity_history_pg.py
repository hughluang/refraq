"""Historical change reads through the published Entity operations."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from backend.admin.role_store import get_role_store
from backend.admin.roles import create_role
from backend.admin.system_parameters import is_registry_frozen, register_parameters
from backend.admin.user_store import UserRecord, get_user_store
from backend.core.config import reset_settings_cache
from backend.core.time import utc_now
from backend.entity.access.errors import (
    EntityAccessCombinationLimit,
    EntityAccessPending,
)
from backend.entity.access.records import GrantRecord, RestrictionRecord
from backend.entity.access.seed import ensure_system_grant
from backend.entity.access.service import (
    create_grant,
    create_profile,
    create_restriction,
    put_ladder,
)
from backend.entity.access.store import get_access_store
from backend.entity.access.views import rebuild_entity_views
from backend.entity.change_log import (
    SOURCE_CHANNEL_RUN,
    SOURCE_GUC,
    SOURCE_USER,
    SUBJECT_GUC,
    ChangeLogEffective,
    ensure_shared_relations,
    install_triggers,
    write_effective,
)
from backend.entity.changes import ChangeLogOff, capture_bound
from backend.entity.ddl import (
    ENTITY_DATA_SCHEMA,
    EXPOSURE_OWNER_ROLE,
    ident,
    qualified_table,
)
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.errors import (
    EntityChangeLogQueryUnsupported,
    EntityNotFound,
    EntityRequestInvalid,
)
from backend.entity.history.service import (
    read_history,
    read_incremental,
)
from backend.entity.ids import (
    new_access_grant_id,
    new_access_restriction_id,
    new_entity_id,
    new_version_id,
)
from backend.entity.lifecycle import PUBLISHED
from backend.entity.parameters import ENTITY_PARAMETER_SPECS
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_stored,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import compose_physical_table_name
from backend.entity.table_port import PostgresEntityTablePort, bind_entity_table_port
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_PARTIAL = {"type": "partial", "keep_first": 1, "keep_last": 1}
_CLEAR_LEVELS = [{"key": "clear", "mode": "clear"}]
_MASK_LEVELS = [
    {"key": "clear", "mode": "clear"},
    {"key": "masked", "mode": _PARTIAL},
]
_HASH_LEVELS = [
    {"key": "clear", "mode": "clear"},
    {"key": "hashed", "mode": {"type": "hash"}},
]


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
def history_database():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_hread") as urls:
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


@pytest.fixture
def history_db(history_database, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    reset_settings_cache()
    reset_entity_engine()
    bind_entity_table_port(PostgresEntityTablePort())
    if not is_registry_frozen():
        register_parameters(
            ENTITY_PARAMETER_SPECS, group_order=("entity_access", "entity")
        )
    yield history_database


class _World:
    def __init__(
        self,
        entity_id: str,
        user: UserRecord,
        tables: list[str],
        version_ids: list[str],
    ) -> None:
        self.entity_id = entity_id
        self.user = user
        self.tables = tables
        self.version_ids = version_ids


def _attr(
    attribute_id: str,
    name: str,
    type_: str,
    *,
    business_key: bool = False,
    max_length: int | None = None,
) -> AttributeRecord:
    return AttributeRecord(
        name=name,
        type=type_,
        required=business_key,
        unique=business_key,
        business_key=business_key,
        max_length=max_length,
        attribute_id=attribute_id,
    )


def _sku(attribute_id: str = "att_sku", name: str = "sku") -> AttributeRecord:
    return _attr(attribute_id, name, "string", business_key=True, max_length=32)


def _qty(attribute_id: str = "att_qty", name: str = "qty", type_: str = "integer") -> AttributeRecord:
    length = 32 if type_ == "string" else None
    return _attr(attribute_id, name, type_, max_length=length)


def _note(attribute_id: str = "att_note", name: str = "note") -> AttributeRecord:
    return _attr(attribute_id, name, "text")


def _user(account: str, *, role_id: str | None = None) -> UserRecord:
    return get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash="x",
        role_id=role_id,
        status="active",
    )


def _publish(
    versions: list[list[AttributeRecord]],
    *,
    user: UserRecord | None = None,
    materialized: set[int] | None = None,
    recording: bool = True,
) -> _World:
    """Publish versions numbered from 1. ``materialized`` indexes default to all."""
    entity_id = new_entity_id()
    stem = f"m{uuid.uuid4().hex[:8]}"
    reader = user or _user(f"u{uuid.uuid4().hex[:8]}")
    now = utc_now()
    present = set(range(len(versions))) if materialized is None else materialized
    tables: list[str] = []
    version_ids: list[str] = []
    records: list[EntityVersionRecord] = []
    for index, attributes in enumerate(versions):
        version_id = new_version_id()
        version_ids.append(version_id)
        table, _comment = compose_physical_table_name(stem, index + 1, version_id)
        tables.append(table)
        PostgresEntityTablePort().create_physical_table(
            ENTITY_DATA_SCHEMA, table, list(attributes)
        )
        stored = [attribute_to_stored(item) for item in attributes]
        records.append(
            EntityVersionRecord(
                id=version_id,
                entity_id=entity_id,
                version=index + 1,
                attributes=list(attributes),
                materialized_attributes=stored if index in present else [],
                publish_status=PUBLISHED,
                latest_reconcile_job_id=None,
                created_at=now,
                updated_at=now,
            )
        )
    get_entity_store().create_entity(
        BusinessEntityRecord(
            id=entity_id,
            table_name=stem,
            name="History",
            description="",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        records[0],
    )
    for record in records[1:]:
        get_entity_store().create_version(record)
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity_id,
                recording=recording,
                retention_days=None,
                applied_version_id=version_ids[-1],
            ),
        )
        install_triggers(conn, entity_id, tables)
    return _World(entity_id, reader, tables, version_ids)


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _ready(entity_id: str) -> None:
    rebuild_entity_views(entity_id)


def _profile(
    entity_id: str,
    user_id: str,
    key: str,
    columns: list[tuple[str, str]],
) -> str:
    created = create_profile(
        entity_id,
        key=key,
        name=key,
        description=None,
        columns=[
            {"attribute_id": attribute_id, "level": level}
            for attribute_id, level in columns
        ],
        actor_user_id=user_id,
        actor_token_id=None,
    )
    return str(created["profile"]["id"])


def _grant(
    entity_id: str,
    user_id: str,
    profile_id: str,
    *,
    row_rule: dict | None = None,
    valid_until: datetime | None = None,
    subject_id: str | None = None,
) -> None:
    create_grant(
        entity_id,
        subject={"type": "user", "id": subject_id or user_id},
        profile_id=profile_id,
        row_rule=row_rule,
        actions=["read"],
        status="active",
        valid_until=valid_until,
        actor_user_id=user_id,
        actor_token_id=None,
    )


def _clear(
    world: _World,
    columns: list[str],
    *,
    row_rule: dict | None = None,
    valid_until: datetime | None = None,
    key: str = "reader",
    subject_id: str | None = None,
) -> None:
    profile_id = _profile(
        world.entity_id,
        world.user.id,
        key,
        [(attribute_id, "clear") for attribute_id in columns],
    )
    _grant(
        world.entity_id,
        world.user.id,
        profile_id,
        row_rule=row_rule,
        valid_until=valid_until,
        subject_id=subject_id,
    )


def _ladder(entity_id: str, user_id: str, attribute_id: str, levels: list[dict]) -> None:
    put_ladder(
        entity_id,
        attribute_id,
        levels,
        actor_user_id=user_id,
        actor_token_id=None,
    )


def _insert(
    table: str,
    values: dict[str, object],
    *,
    source: str | None = None,
    subject: str | None = None,
) -> int:
    columns = ", ".join(values)
    holders = ", ".join(f":{name}" for name in values)
    with get_entity_engine().begin() as conn:
        _source(conn, source, subject)
        row_id = conn.execute(
            text(
                f"INSERT INTO {_relation(table)} ({columns}) "
                f"VALUES ({holders}) RETURNING row_id"
            ),
            values,
        ).scalar_one()
    return int(row_id)


def _update(
    table: str,
    sku: str,
    values: dict[str, object],
    *,
    sku_column: str = "sku",
) -> None:
    sets = ", ".join(f"{name} = :{name}" for name in values)
    with get_entity_engine().begin() as conn:
        conn.execute(
            text(
                f"UPDATE {_relation(table)} SET {sets} WHERE {sku_column} = :sku_key"
            ),
            {**values, "sku_key": sku},
        )


def _delete(table: str, sku: str, *, sku_column: str = "sku") -> None:
    with get_entity_engine().begin() as conn:
        conn.execute(
            text(f"DELETE FROM {_relation(table)} WHERE {sku_column} = :sku"),
            {"sku": sku},
        )


def _source(conn: Connection, source: str | None, subject: str | None) -> None:
    if source is None:
        return
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SOURCE_GUC, "value": source},
    )
    if subject is not None:
        conn.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": SUBJECT_GUC, "value": subject},
        )


def _stamp(entity_id: str, occurred_at: str) -> None:
    with get_entity_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE entity_change_log.entry SET occurred_at = CAST(:at AS timestamptz) "
                "WHERE entity_id = :entity_id"
            ),
            {"at": occurred_at, "entity_id": entity_id},
        )


def _corrupt(entity_id: str) -> None:
    with get_entity_engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE entity_change_log.entry SET image = '{}'::jsonb "
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": entity_id},
        )


def _visible_sku(event: object) -> str:
    after = getattr(event, "after")
    assert after.state == "visible"
    assert after.values is not None
    return str(after.values["sku"])


def test_no_read_grant_is_entity_not_found(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _insert(world.tables[0], {"sku": "kept", "qty": 1})
    with pytest.raises(EntityNotFound) as caught:
        read_history(world.entity_id, world.user)
    assert caught.value.code == "ENTITY_NOT_FOUND"
    assert caught.value.http_status == 404


def test_expired_grant_is_entity_not_found(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(
        world,
        ["att_sku", "att_qty"],
        valid_until=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "kept", "qty": 1})
    with pytest.raises(EntityNotFound):
        read_history(world.entity_id, world.user)


def test_management_permissions_are_not_a_grant(history_db: object) -> None:
    role = create_role(
        get_role_store(),
        key=f"mgr{uuid.uuid4().hex[:8]}",
        name="Manager",
        permissions=["entity:read", "entity:write"],
    )
    manager = _user(f"m{uuid.uuid4().hex[:8]}", role_id=role.id)
    world = _publish([[_sku(), _qty()]], user=manager)
    _insert(world.tables[0], {"sku": "kept", "qty": 1})
    with pytest.raises(EntityNotFound):
        read_history(world.entity_id, manager)


def test_no_grant_is_not_found_before_pending(history_db: object) -> None:
    holder = _user(f"h{uuid.uuid4().hex[:8]}")
    outsider = _user(f"o{uuid.uuid4().hex[:8]}")
    world = _publish([[_sku()]], user=holder)
    _clear(world, ["att_sku"], subject_id=holder.id)
    _insert(world.tables[0], {"sku": "kept"})
    with pytest.raises(EntityNotFound):
        read_history(world.entity_id, outsider)
    with pytest.raises(EntityAccessPending):
        read_history(world.entity_id, holder)


def test_grant_union_keeps_the_clear_value(history_db: object) -> None:
    world = _publish([[_sku()]])
    _ladder(world.entity_id, world.user.id, "att_sku", _MASK_LEVELS)
    wide = _profile(world.entity_id, world.user.id, "wide", [("att_sku", "clear")])
    narrow = _profile(world.entity_id, world.user.id, "narrow", [("att_sku", "masked")])
    _grant(world.entity_id, world.user.id, wide)
    _grant(world.entity_id, world.user.id, narrow)
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "abcdef"})
    page = read_history(world.entity_id, world.user)
    assert len(page.events) == 1
    values = page.events[0].after.values
    assert values is not None
    assert values["sku"] == "abcdef"
    assert values["__withheld"] == []


def test_restriction_still_applies_to_the_system_grant(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    ensure_system_grant(world.entity_id, [_sku(), _qty()])
    create_restriction(
        world.entity_id,
        applies_to={"mode": "all"},
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
        deny_columns=[],
        ceilings=[],
        actions=["read"],
        actor_user_id=world.user.id,
        actor_token_id=None,
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "open", "qty": 1})
    _insert(world.tables[0], {"sku": "shut", "qty": 2})
    page = read_incremental(
        world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=10
    )
    assert [event.after.values["sku"] for event in page.events if event.after.values] == [
        "open"
    ]
    assert page.has_more is False
    assert page.progress is not None


def test_ceiling_lowers_a_clear_profile(history_db: object) -> None:
    world = _publish([[_sku()]])
    _ladder(world.entity_id, world.user.id, "att_sku", _MASK_LEVELS)
    _clear(world, ["att_sku"])
    create_restriction(
        world.entity_id,
        applies_to={"mode": "all"},
        row_rule=None,
        deny_columns=[],
        ceilings=[{"attribute_id": "att_sku", "level": "masked"}],
        actions=["read"],
        actor_user_id=world.user.id,
        actor_token_id=None,
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "abcdef"})
    page = read_history(world.entity_id, world.user)
    assert page.events[0].after.values is not None
    assert page.events[0].after.values["sku"] == "a****f"


def test_mask_projects_the_profile_level(history_db: object) -> None:
    world = _publish([[_sku(), _note()]])
    _ladder(world.entity_id, world.user.id, "att_sku", _MASK_LEVELS)
    profile_id = _profile(
        world.entity_id, world.user.id, "masked", [("att_sku", "masked")]
    )
    _grant(world.entity_id, world.user.id, profile_id)
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "abcdef", "note": "secret"})
    values = read_history(world.entity_id, world.user).events[0].after.values
    assert values is not None
    assert values["sku"] == "a****f"
    assert "note" not in values


def test_hash_mask_matches_the_access_function(history_db: object) -> None:
    world = _publish([[_sku()]])
    _ladder(world.entity_id, world.user.id, "att_sku", _HASH_LEVELS)
    profile_id = _profile(
        world.entity_id, world.user.id, "hashed", [("att_sku", "hashed")]
    )
    _grant(world.entity_id, world.user.id, profile_id)
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "abcdef"})
    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql(f"SET LOCAL ROLE {ident(EXPOSURE_OWNER_ROLE)}")
        hashed = conn.execute(
            text("SELECT acl.mask_hash(CAST(:value AS text))"),
            {"value": "abcdef"},
        ).scalar_one()
    values = read_history(world.entity_id, world.user).events[0].after.values
    assert values is not None
    assert values["sku"] == hashed
    assert values["sku"] != "abcdef"


def test_withheld_cell_hides_the_value_and_names_the_column(history_db: object) -> None:
    attributes = [_sku(), _qty(), _attr("att_secret", "secret", "text")]
    world = _publish([attributes])
    shown = _profile(
        world.entity_id,
        world.user.id,
        "shown",
        [("att_sku", "clear"), ("att_secret", "clear")],
    )
    hidden = _profile(
        world.entity_id, world.user.id, "hidden", [("att_sku", "clear")]
    )
    _grant(
        world.entity_id,
        world.user.id,
        shown,
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
    )
    _grant(
        world.entity_id,
        world.user.id,
        hidden,
        row_rule={"eq": {"attr": "att_qty", "value": 2}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "shown", "qty": 2, "secret": "hidden-value"})
    values = read_history(world.entity_id, world.user).events[0].after.values
    assert values is not None
    assert values["sku"] == "shown"
    assert values["secret"] is None
    assert values["__withheld"] == ["secret"]
    assert "hidden-value" not in values.values()


def test_broken_grant_is_dropped(history_db: object) -> None:
    world = _publish([[_sku()]])
    profile_id = _profile(world.entity_id, world.user.id, "reader", [("att_sku", "clear")])
    now = utc_now()
    get_access_store().insert_grant(
        GrantRecord(
            id=new_access_grant_id(),
            entity_id=world.entity_id,
            subject_type="user",
            subject_id=world.user.id,
            profile_id=profile_id,
            row_rule={"eq": {"attr": "att_missing", "value": "x"}},
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    _insert(world.tables[0], {"sku": "kept"})
    with pytest.raises(EntityNotFound):
        read_history(world.entity_id, world.user)


def test_broken_restriction_hides_the_entity(history_db: object) -> None:
    world = _publish([[_sku()]])
    _clear(world, ["att_sku"])
    now = utc_now()
    get_access_store().insert_restriction(
        RestrictionRecord(
            id=new_access_restriction_id(),
            entity_id=world.entity_id,
            applies_to={"mode": "all", "subjects": []},
            row_rule={"eq": {"attr": "att_missing", "value": "x"}},
            deny_columns=[],
            ceilings=[],
            actions=["read"],
            created_at=now,
            updated_at=now,
        )
    )
    store = get_access_store()
    store.set_revision(world.entity_id, store.revision(world.entity_id) + 1)
    _insert(world.tables[0], {"sku": "kept"})
    with pytest.raises(EntityNotFound):
        read_history(world.entity_id, world.user)


def test_pending_entity_does_not_fail_an_unrelated_entity(history_db: object) -> None:
    pending = _publish([[_sku()]])
    _clear(pending, ["att_sku"])
    _insert(pending.tables[0], {"sku": "waiting"})
    ready = _publish([[_sku()]])
    _clear(ready, ["att_sku"])
    _ready(ready.entity_id)
    _insert(ready.tables[0], {"sku": "served"})
    with pytest.raises(EntityAccessPending) as caught:
        read_history(pending.entity_id, pending.user)
    assert caught.value.code == "ENTITY_ACCESS_PENDING"
    assert caught.value.http_status == 503
    assert caught.value.retry_after_sec == 1
    page = read_history(ready.entity_id, ready.user)
    assert [_visible_sku(event) for event in page.events] == ["served"]


def test_combination_limit_is_the_existing_conflict(history_db: object, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _publish([[_sku()]])
    first = _profile(world.entity_id, world.user.id, "first", [("att_sku", "clear")])
    second = _profile(world.entity_id, world.user.id, "second", [("att_sku", "clear")])
    _grant(world.entity_id, world.user.id, first)
    _grant(world.entity_id, world.user.id, second)
    _ready(world.entity_id)
    monkeypatch.setattr(
        "backend.entity.access.plan.max_profile_combinations", lambda: 0
    )
    with pytest.raises(EntityAccessCombinationLimit) as caught:
        read_history(world.entity_id, world.user)
    assert caught.value.code == "ENTITY_ACCESS_COMBINATION_LIMIT"
    assert caught.value.http_status == 409


def test_missing_policy_attribute_is_not_a_stored_null(history_db: object) -> None:
    old = [_sku(), _qty()]
    head = [_sku(), _qty(), _note()]
    world = _publish([old, head])
    _clear(
        world,
        ["att_sku", "att_qty", "att_note"],
        row_rule={"is_null": {"attr": "att_note", "value": True}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "old", "qty": 1})
    _insert(world.tables[1], {"sku": "blank", "qty": 1, "note": None})
    _insert(world.tables[1], {"sku": "filled", "qty": 1, "note": "kept"})
    page = read_history(world.entity_id, world.user)
    by_sku = {_visible_sku(event): event for event in page.events}
    assert "old" not in by_sku
    assert "filled" not in by_sku
    blank = by_sku["blank"]
    assert blank.version_id == world.version_ids[1]
    assert blank.after.values is not None
    assert "note" in blank.after.values
    assert blank.after.values["note"] is None


def _ref(target: str) -> AttributeRecord:
    return AttributeRecord(
        name="supplier",
        type="reference",
        attribute_id="att_supplier",
        target_entity_id=target,
        reference_key_type="integer",
    )


def test_changed_reference_target_is_unavailable_and_a_match_stays(
    history_db: object,
) -> None:
    old_target = new_entity_id()
    head_target = new_entity_id()
    world = _publish([[_sku(), _ref(old_target)], [_sku(), _ref(head_target)]])
    store = get_entity_store()
    for version_id in world.version_ids:
        version = store.get_version(version_id)
        assert version is not None
        version.reference_snapshots = {"supplier": {"type": "integer"}}
        store.save_version(version)
    _clear(world, ["att_sku", "att_supplier"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "moved", "supplier": 9})
    _insert(world.tables[1], {"sku": "kept", "supplier": 7})
    page = read_history(world.entity_id, world.user)
    assert [_visible_sku(event) for event in page.events] == ["kept"]
    values = page.events[0].after.values
    assert values is not None
    assert values["supplier"] == 7


def test_time_cell_is_an_iso_string(history_db: object) -> None:
    world = _publish([[_sku(), _attr("att_clock", "clock", "time")]])
    _clear(world, ["att_sku", "att_clock"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "shift", "clock": "03:04:05"})
    values = read_history(world.entity_id, world.user).events[0].after.values
    assert values is not None
    assert values["clock"] == "03:04:05"


def test_incompatible_historical_type_is_unavailable(history_db: object) -> None:
    old = [_sku(), _qty(type_="string")]
    head = [_sku(), _qty(type_="integer")]
    world = _publish([old, head])
    _clear(world, ["att_sku", "att_qty"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "old", "qty": "abc"})
    _insert(world.tables[1], {"sku": "head", "qty": 4})
    page = read_history(world.entity_id, world.user)
    assert [_visible_sku(event) for event in page.events] == ["head"]
    assert page.events[0].after.values is not None
    assert page.events[0].after.values["qty"] == 4


def test_renamed_attribute_is_read_by_identity_after_the_table_is_dropped(
    history_db: object,
) -> None:
    old = [_sku(name="code")]
    head = [_sku(name="sku")]
    world = _publish([old, head], materialized={1})
    _clear(world, ["att_sku"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"code": "kept-code"})
    with get_entity_engine().begin() as conn:
        conn.execute(text(f"DROP TABLE {_relation(world.tables[0])} CASCADE"))
    page = read_history(world.entity_id, world.user)
    event = page.events[0]
    assert event.version_id == world.version_ids[0]
    assert event.version_number == 1
    assert not hasattr(event, "physical_table")
    assert event.before.state == "absent"
    assert event.before.values is None
    assert event.after.values is not None
    assert event.after.values["sku"] == "kept-code"
    assert "code" not in event.after.values
    assert "row_id" not in event.__slots__


def test_insert_has_no_before_side(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(world, ["att_sku", "att_qty"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "made", "qty": 3})
    event = read_history(world.entity_id, world.user).events[0]
    assert event.operation == "insert"
    assert event.before.state == "absent"
    assert event.before.values is None
    assert event.after.state == "visible"
    assert event.after.values is not None
    assert event.after.values["sku"] == "made"
    assert event.after.values["qty"] == 3
    assert isinstance(event.after.values["row_id"], int)


def test_delete_has_no_after_side(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(world, ["att_sku", "att_qty"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "gone", "qty": 3})
    _delete(world.tables[0], "gone")
    page = read_history(world.entity_id, world.user)
    deleted = next(event for event in page.events if event.operation == "delete")
    assert deleted.after.state == "absent"
    assert deleted.after.values is None
    assert deleted.before.state == "visible"
    assert deleted.before.values is not None
    assert deleted.before.values["sku"] == "gone"


def test_update_can_show_both_sides(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(world, ["att_sku", "att_qty"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "row", "qty": 1})
    _update(world.tables[0], "row", {"qty": 5})
    updated = next(
        event
        for event in read_history(world.entity_id, world.user).events
        if event.operation == "update"
    )
    assert updated.before.state == "visible"
    assert updated.after.state == "visible"
    assert updated.before.values is not None and updated.after.values is not None
    assert updated.before.values["qty"] == 1
    assert updated.after.values["qty"] == 5
    assert updated.before.values["row_id"] == updated.after.values["row_id"]


def test_each_single_visible_side_is_kept(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(
        world,
        ["att_sku", "att_qty"],
        row_rule={"eq": {"attr": "att_qty", "value": 5}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "rise", "qty": 1})
    _update(world.tables[0], "rise", {"qty": 5})
    _insert(world.tables[0], {"sku": "fall", "qty": 5})
    _update(world.tables[0], "fall", {"qty": 1})
    events = {
        event.before.values["sku"]
        if event.before.values is not None
        else event.after.values["sku"]: event
        for event in read_history(world.entity_id, world.user).events
        if event.operation == "update"
    }
    rise = events["rise"]
    assert rise.before.state == "unavailable"
    assert rise.before.values is None
    assert rise.after.state == "visible"
    assert rise.after.values is not None
    assert rise.after.values["qty"] == 5
    fall = events["fall"]
    assert fall.before.state == "visible"
    assert fall.before.values is not None
    assert fall.before.values["qty"] == 5
    assert fall.after.state == "unavailable"
    assert fall.after.values is None


def test_both_unreadable_sides_are_omitted_and_still_advance(history_db: object) -> None:
    world = _publish([[_sku(), _qty()]])
    ensure_system_grant(world.entity_id, [_sku(), _qty()])
    create_restriction(
        world.entity_id,
        applies_to={"mode": "all"},
        row_rule={"eq": {"attr": "att_qty", "value": 9}},
        deny_columns=[],
        ceilings=[],
        actions=["read"],
        actor_user_id=world.user.id,
        actor_token_id=None,
    )
    _clear(
        world,
        ["att_sku", "att_qty"],
        row_rule={"eq": {"attr": "att_qty", "value": 9}},
        key="human",
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "hidden", "qty": 1})
    _update(world.tables[0], "hidden", {"qty": 2})
    _insert(world.tables[0], {"sku": "later", "qty": 4})
    history = read_history(world.entity_id, world.user)
    assert history.events == []
    assert history.continuation is None
    first = read_incremental(
        world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=1
    )
    assert first.events == []
    assert first.has_more is True
    assert first.progress is not None
    second = read_incremental(
        world.entity_id,
        after=first.progress,
        bound=capture_bound(world.entity_id),
        limit=10,
    )
    assert [event.operation for event in second.events] == []
    assert second.progress is not None
    assert second.progress.commit_seq > first.progress.commit_seq


def test_equal_projected_update_is_omitted_only_from_interactive_history(
    history_db: object,
) -> None:
    world = _publish([[_sku(), _qty()]])
    ensure_system_grant(world.entity_id, [_sku(), _qty()])
    create_restriction(
        world.entity_id,
        applies_to={"mode": "all"},
        row_rule=None,
        deny_columns=["att_qty"],
        ceilings=[],
        actions=["read"],
        actor_user_id=world.user.id,
        actor_token_id=None,
    )
    _clear(world, ["att_sku"], key="human")
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "kept", "qty": 1})
    for qty in range(2, 52):
        _update(world.tables[0], "kept", {"qty": qty})
    history = read_history(world.entity_id, world.user)
    assert history.events == []
    assert history.continuation is not None
    rest = read_history(
        world.entity_id, world.user, before_sequence=history.continuation
    )
    assert [event.operation for event in rest.events] == ["insert"]
    assert rest.events[0].after.values is not None
    assert rest.events[0].after.values["sku"] == "kept"
    assert rest.continuation is None
    consumed = read_incremental(
        world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=60
    )
    assert [event.operation for event in consumed.events].count("update") == 50
    assert consumed.events[0].operation == "insert"
    assert consumed.has_more is False


def test_corrupt_image_is_not_an_empty_exhausted_page(history_db: object) -> None:
    world = _publish([[_sku()]])
    ensure_system_grant(world.entity_id, [_sku()])
    _clear(world, ["att_sku"])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "kept"})
    _corrupt(world.entity_id)
    with pytest.raises(KeyError):
        read_history(world.entity_id, world.user)
    with pytest.raises(KeyError):
        read_incremental(
            world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=10
        )


def test_filters_keep_matching_rules_and_drop_unauthorized_rows(
    history_db: object,
) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(
        world,
        ["att_sku", "att_qty"],
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
    )
    _ready(world.entity_id)
    _insert(
        world.tables[0],
        {"sku": "ada", "qty": 1},
        source=SOURCE_USER,
        subject="ada",
    )
    _insert(
        world.tables[0],
        {"sku": "blocked", "qty": 9},
        source=SOURCE_USER,
        subject="ada",
    )
    _insert(
        world.tables[0],
        {"sku": "run", "qty": 1},
        source=SOURCE_CHANNEL_RUN,
        subject="run-1",
    )
    _insert(world.tables[0], {"sku": "plain", "qty": 1})
    _stamp(world.entity_id, "2020-01-02T03:04:05.739746Z")
    matched = read_history(
        world.entity_id,
        world.user,
        operation="insert",
        source=SOURCE_USER,
        subject="ada",
    )
    assert [_visible_sku(event) for event in matched.events] == ["ada"]
    early = read_history(
        world.entity_id,
        world.user,
        occurred_to="2020-01-02T03:04:05Z",
    )
    assert {_visible_sku(event) for event in early.events} == {"ada", "plain", "run"}
    exact = read_history(
        world.entity_id,
        world.user,
        occurred_to="2020-01-02T03:04:05.000000Z",
    )
    assert exact.events == []
    unbounded = read_history(world.entity_id, world.user)
    assert {_visible_sku(event) for event in unbounded.events} == {"ada", "plain", "run"}
    identity = read_history(world.entity_id, world.user, row_identity="ada")
    assert [_visible_sku(event) for event in identity.events] == ["ada"]
    hidden = read_history(world.entity_id, world.user, row_identity="blocked")
    assert hidden.events == []
    assert hidden.continuation is None


def test_interactive_history_is_newest_sequence_first(history_db: object) -> None:
    world = _publish([[_sku()]])
    _clear(world, ["att_sku"])
    ensure_system_grant(world.entity_id, [_sku()])
    _ready(world.entity_id)
    engine = get_entity_engine()
    held = engine.connect()
    held_tx = held.begin()
    try:
        held.execute(
            text(f"INSERT INTO {_relation(world.tables[0])} (sku) VALUES ('first')")
        )
        _insert(world.tables[0], {"sku": "second"})
        held_tx.commit()
    finally:
        held.close()
    history = read_history(world.entity_id, world.user)
    assert [_visible_sku(event) for event in history.events] == ["second", "first"]
    assert history.events[0].sequence > history.events[1].sequence
    consumed = read_incremental(
        world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=10
    )
    assert [event.after.values["sku"] for event in consumed.events if event.after.values] == [
        "second",
        "first",
    ]


def test_interactive_page_continues_after_fifty_visible_events(history_db: object) -> None:
    world = _publish([[_sku()]])
    _clear(world, ["att_sku"])
    _ready(world.entity_id)
    for index in range(51):
        _insert(world.tables[0], {"sku": f"s{index:02d}"})
    first = read_history(world.entity_id, world.user)
    assert [_visible_sku(event) for event in first.events] == [
        f"s{index:02d}" for index in range(50, 0, -1)
    ]
    assert first.continuation == first.events[-1].sequence
    second = read_history(
        world.entity_id, world.user, before_sequence=first.continuation
    )
    assert [_visible_sku(event) for event in second.events] == ["s00"]
    assert second.continuation is None


def test_incremental_limit_does_not_invent_a_time_window(history_db: object) -> None:
    world = _publish([[_sku()]])
    ensure_system_grant(world.entity_id, [_sku()])
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "old"})
    _stamp(world.entity_id, "2020-01-02T03:04:05Z")
    _insert(world.tables[0], {"sku": "new"})
    page = read_incremental(
        world.entity_id, after=None, bound=capture_bound(world.entity_id), limit=1
    )
    assert [event.after.values["sku"] for event in page.events if event.after.values] == [
        "old"
    ]
    assert page.has_more is True
    assert page.progress is not None
    rest = read_incremental(
        world.entity_id,
        after=page.progress,
        bound=capture_bound(world.entity_id),
        limit=10,
    )
    assert [event.after.values["sku"] for event in rest.events if event.after.values] == [
        "new"
    ]
    assert rest.has_more is False
    assert rest.events[0].physical_table
    assert rest.events[0].version_number == 1


def test_lookup_matches_a_clear_business_key_or_one_version_row(
    history_db: object,
) -> None:
    world = _publish([[_sku()], [_sku()]])
    _clear(world, ["att_sku"])
    _ready(world.entity_id)
    left_row = _insert(world.tables[0], {"sku": "LEFT"})
    right_row = _insert(world.tables[1], {"sku": "RIGHT"})
    assert left_row == 1
    assert right_row == 1
    by_key = read_history(world.entity_id, world.user, row_identity="LEFT")
    assert [_visible_sku(event) for event in by_key.events] == ["LEFT"]
    assert by_key.events[0].version_id == world.version_ids[0]
    by_row_text = read_history(world.entity_id, world.user, row_identity="1")
    assert by_row_text.events == []
    assert by_row_text.continuation is None
    left = read_history(
        world.entity_id,
        world.user,
        version_id=world.version_ids[0],
        row_id="1",
    )
    assert [_visible_sku(event) for event in left.events] == ["LEFT"]
    right = read_history(
        world.entity_id,
        world.user,
        version_id=world.version_ids[1],
        row_id="1",
    )
    assert [_visible_sku(event) for event in right.events] == ["RIGHT"]
    opened = read_history(world.entity_id, world.user)
    assert {_visible_sku(event) for event in opened.events} == {"LEFT", "RIGHT"}
    blank = read_history(
        world.entity_id,
        world.user,
        row_identity="",
        version_id="",
        row_id="",
    )
    assert {_visible_sku(event) for event in blank.events} == {"LEFT", "RIGHT"}


def test_business_key_lookup_rejects_when_the_key_cannot_be_clear(
    history_db: object,
) -> None:
    masked = _publish([[_sku(), _note()]])
    _ladder(masked.entity_id, masked.user.id, "att_sku", _MASK_LEVELS)
    masked_profile = _profile(
        masked.entity_id, masked.user.id, "masked", [("att_sku", "masked")]
    )
    _grant(masked.entity_id, masked.user.id, masked_profile)
    _ready(masked.entity_id)
    _insert(masked.tables[0], {"sku": "abcdef", "note": "kept"})
    with pytest.raises(EntityChangeLogQueryUnsupported) as masked_error:
        read_history(masked.entity_id, masked.user, row_identity="abcdef")
    assert masked_error.value.code == "ENTITY_CHANGE_LOG_QUERY_UNSUPPORTED"
    assert masked_error.value.message == "This change-log query is not supported."
    assert "abcdef" not in masked_error.value.message

    hidden = _publish([[_sku(), _note()]])
    note_only = _profile(
        hidden.entity_id, hidden.user.id, "note", [("att_note", "clear")]
    )
    _grant(hidden.entity_id, hidden.user.id, note_only)
    _ready(hidden.entity_id)
    _insert(hidden.tables[0], {"sku": "secret-key", "note": "visible"})
    with pytest.raises(EntityChangeLogQueryUnsupported) as hidden_error:
        read_history(hidden.entity_id, hidden.user, row_identity="secret-key")
    assert hidden_error.value.message == "This change-log query is not supported."
    assert "secret-key" not in hidden_error.value.message
    listed = read_history(hidden.entity_id, hidden.user)
    assert listed.events[0].after.values is not None
    assert "sku" not in listed.events[0].after.values
    assert listed.events[0].after.values["note"] == "visible"


def test_row_varying_mask_matches_only_a_clear_business_key(
    history_db: object,
) -> None:
    world = _publish([[_sku(), _qty()]])
    _ladder(world.entity_id, world.user.id, "att_sku", _MASK_LEVELS)
    clear = _profile(
        world.entity_id,
        world.user.id,
        "clear",
        [("att_sku", "clear"), ("att_qty", "clear")],
    )
    masked = _profile(
        world.entity_id,
        world.user.id,
        "masked",
        [("att_sku", "masked"), ("att_qty", "clear")],
    )
    _grant(
        world.entity_id,
        world.user.id,
        clear,
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
    )
    _grant(
        world.entity_id,
        world.user.id,
        masked,
        row_rule={"eq": {"attr": "att_qty", "value": 2}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "OPEN", "qty": 1})
    _insert(world.tables[0], {"sku": "SECRET", "qty": 2})
    matched = read_history(world.entity_id, world.user, row_identity="OPEN")
    assert [_visible_sku(event) for event in matched.events] == ["OPEN"]
    missed = read_history(world.entity_id, world.user, row_identity="SECRET")
    assert missed.events == []
    assert missed.continuation is None
    masked_text = read_history(world.entity_id, world.user, row_identity="S****T")
    assert masked_text.events == []


def test_withheld_business_key_does_not_match_and_does_not_reject_the_query(
    history_db: object,
) -> None:
    world = _publish([[_sku(), _qty()]])
    shown = _profile(
        world.entity_id,
        world.user.id,
        "shown",
        [("att_sku", "clear"), ("att_qty", "clear")],
    )
    omitted = _profile(
        world.entity_id, world.user.id, "omitted", [("att_qty", "clear")]
    )
    _grant(
        world.entity_id,
        world.user.id,
        shown,
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
    )
    _grant(
        world.entity_id,
        world.user.id,
        omitted,
        row_rule={"eq": {"attr": "att_qty", "value": 2}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "SHOWN", "qty": 1})
    _insert(world.tables[0], {"sku": "HIDDEN", "qty": 2})
    matched = read_history(world.entity_id, world.user, row_identity="SHOWN")
    assert [_visible_sku(event) for event in matched.events] == ["SHOWN"]
    missed = read_history(world.entity_id, world.user, row_identity="HIDDEN")
    assert missed.events == []
    assert missed.continuation is None
    held = read_history(world.entity_id, world.user)
    withheld = [
        event.after.values
        for event in held.events
        if event.after.values is not None and event.after.values.get("sku") is None
    ]
    assert withheld[0] is not None
    assert "HIDDEN" not in withheld[0].values()
    assert withheld[0]["__withheld"] == ["sku"]


def test_lookup_uses_the_visible_side_and_rejects_an_incomplete_pair(
    history_db: object,
) -> None:
    world = _publish([[_sku(), _qty()]])
    _clear(
        world,
        ["att_sku", "att_qty"],
        row_rule={"eq": {"attr": "att_qty", "value": 1}},
    )
    _ready(world.entity_id)
    _insert(world.tables[0], {"sku": "START", "qty": 1})
    _update(world.tables[0], "START", {"sku": "NEXT", "qty": 9})
    _insert(world.tables[0], {"sku": "SECRET", "qty": 9})
    visible = read_history(world.entity_id, world.user, row_identity="START")
    updates = [item for item in visible.events if item.operation == "update"]
    assert len(updates) == 1
    assert any(item.operation == "insert" for item in visible.events)
    event = updates[0]
    assert event.before.state == "visible"
    assert event.before.values is not None
    assert event.before.values["sku"] == "START"
    assert event.after.state == "unavailable"
    assert event.after.values is None
    assert not hasattr(event, "business_key")
    hidden_after = read_history(world.entity_id, world.user, row_identity="NEXT")
    assert hidden_after.events == []
    hidden_row = read_history(world.entity_id, world.user, row_identity="SECRET")
    assert hidden_row.events == []
    opened = read_history(world.entity_id, world.user)
    assert event.sequence in {item.sequence for item in opened.events}
    assert all(
        item.after.values is None or item.after.values.get("sku") != "SECRET"
        for item in opened.events
    )
    with pytest.raises(EntityChangeLogQueryUnsupported) as lone_row:
        read_history(world.entity_id, world.user, row_id="1")
    assert lone_row.value.message == "This change-log query is not supported."
    with pytest.raises(EntityChangeLogQueryUnsupported):
        read_history(world.entity_id, world.user, version_id=world.version_ids[0])
    with pytest.raises(EntityChangeLogQueryUnsupported):
        read_history(
            world.entity_id,
            world.user,
            row_identity="START",
            version_id=world.version_ids[0],
            row_id="1",
        )
    with pytest.raises(EntityRequestInvalid) as bad_row:
        read_history(
            world.entity_id,
            world.user,
            version_id=world.version_ids[0],
            row_id="nope",
        )
    assert bad_row.value.code == "REQUEST_INVALID"


def test_recording_off_raises_for_incremental_consumption(history_db: object) -> None:
    world = _publish([[_sku()]], recording=False)
    ensure_system_grant(world.entity_id, [_sku()])
    _ready(world.entity_id)
    with pytest.raises(ChangeLogOff):
        read_incremental(world.entity_id, after=None, bound=0, limit=10)
