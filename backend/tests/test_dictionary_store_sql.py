"""SqlDictionaryStore against an engine that enforces foreign keys.

Memory tests never insert a child row, so they cannot see flush order.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.db import Base
from backend.entity.dictionaries.records import DictionaryEntryRecord, DictionaryRecord
from backend.entity.dictionaries.store import MemoryDictionaryStore, SqlDictionaryStore
from backend.entity.errors import DictionaryNameDup
from backend.entity.models import DictionaryEntryRow, DictionaryRow

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sql_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[SqlDictionaryStore, Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[DictionaryRow.__table__, DictionaryEntryRow.__table__],
    )

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

    monkeypatch.setattr(
        "backend.entity.dictionaries.store.session_scope",
        session_scope,
    )
    probe = Session(engine, autoflush=False, autocommit=False)
    try:
        yield SqlDictionaryStore(), probe
    finally:
        probe.close()
        engine.dispose()


def test_create_persists_parent_and_entries(sql_store) -> None:
    store, probe = sql_store
    store.create(_record("cl_new", "order_status", ("open", "closed")))

    parent = probe.get(DictionaryRow, "cl_new")
    assert parent is not None
    assert parent.name == "order_status"
    codes = probe.scalars(
        select(DictionaryEntryRow.code)
        .where(DictionaryEntryRow.dictionary_id == "cl_new")
        .order_by(DictionaryEntryRow.position)
    ).all()
    assert codes == ["open", "closed"]


def test_duplicate_name_hits_parent_unique_constraint(sql_store) -> None:
    store, _probe = sql_store
    store.create(_record("cl_first", "order_status", ("open",)))

    with pytest.raises(IntegrityError) as raised:
        store.create(_record("cl_second", "order_status", ("held",)))

    message = str(raised.value.orig).upper()
    assert "UNIQUE" in message
    assert "DICTIONARIES" in message
    assert "FOREIGN KEY" not in message


def test_parent_only_patch_keeps_committed_entries_and_revision(sql_store) -> None:
    store, probe = sql_store
    store.create(_record("cl_live", "order_status", ("base",)))
    store.modify(
        "cl_live",
        lambda _current: _record(
            "cl_live", "order_status", ("base", "held"), revision=2
        ),
    )

    # Parent-field patch assembled outside the write: display name is new,
    # entries and revision are still the values read before the add committed.
    stale = _record(
        "cl_live", "order_status", ("base",), display_name="Renamed", revision=1
    )
    saved = store.modify(
        "cl_live",
        lambda current: replace(
            current,
            display_name=stale.display_name,
            description=stale.description,
            deprecated_at=stale.deprecated_at,
            updated_at=_LATER,
        ),
    )

    assert saved.display_name == "Renamed"
    assert saved.revision == 2
    assert [entry.code for entry in saved.entries] == ["base", "held"]
    probe.expire_all()
    parent = probe.get(DictionaryRow, "cl_live")
    assert parent is not None
    assert parent.revision == 2
    assert parent.display_name == "Renamed"
    codes = probe.scalars(
        select(DictionaryEntryRow.code)
        .where(DictionaryEntryRow.dictionary_id == "cl_live")
        .order_by(DictionaryEntryRow.position)
    ).all()
    assert codes == ["base", "held"]


def test_parent_only_patch_keeps_committed_entries_in_memory() -> None:
    store = MemoryDictionaryStore()
    store.create(_record("cl_live", "order_status", ("base",)))
    store.modify(
        "cl_live",
        lambda _current: _record(
            "cl_live", "order_status", ("base", "held"), revision=2
        ),
    )

    stale = _record(
        "cl_live", "order_status", ("base",), display_name="Renamed", revision=1
    )
    saved = store.modify(
        "cl_live",
        lambda current: replace(
            current,
            display_name=stale.display_name,
            description=stale.description,
            deprecated_at=stale.deprecated_at,
            updated_at=_LATER,
        ),
    )

    assert saved.display_name == "Renamed"
    assert saved.revision == 2
    assert [entry.code for entry in saved.entries] == ["base", "held"]


def test_modify_replaces_entries_of_existing_parent(sql_store) -> None:
    store, probe = sql_store
    store.create(_record("cl_live", "order_status", ("open", "closed")))

    saved = store.modify(
        "cl_live",
        lambda _current: _record(
            "cl_live", "order_status", ("held",), display_name="Held"
        ),
    )

    assert saved.display_name == "Held"
    assert [entry.code for entry in saved.entries] == ["held"]
    probe.expire_all()
    codes = probe.scalars(
        select(DictionaryEntryRow.code).where(DictionaryEntryRow.dictionary_id == "cl_live")
    ).all()
    assert codes == ["held"]


def test_list_treats_percent_and_underscore_as_literal(sql_store) -> None:
    store, _probe = sql_store
    _seed_literal_search(store)
    _assert_literal_search(store)


def test_memory_list_treats_percent_and_underscore_as_literal() -> None:
    store = MemoryDictionaryStore()
    _seed_literal_search(store)
    _assert_literal_search(store)


def test_create_maps_only_the_named_unique_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record("cl_new", "order_status", ("open",))
    monkeypatch.setattr(
        "backend.entity.dictionaries.store.session_scope",
        _raising_scope(_integrity("uq_dictionaries_name")),
    )
    with pytest.raises(DictionaryNameDup):
        SqlDictionaryStore().create(record)

    monkeypatch.setattr(
        "backend.entity.dictionaries.store.session_scope",
        _raising_scope(_integrity(None)),
    )
    with pytest.raises(IntegrityError):
        SqlDictionaryStore().create(record)


def test_delete_removes_parent_and_entries(sql_store) -> None:
    store, probe = sql_store
    store.create(_record("cl_gone", "order_status", ("open",)))

    assert store.delete("cl_gone") is True
    probe.expire_all()
    assert probe.get(DictionaryRow, "cl_gone") is None
    remaining = probe.scalar(
        select(func.count())
        .select_from(DictionaryEntryRow)
        .where(DictionaryEntryRow.dictionary_id == "cl_gone")
    )
    assert remaining == 0


def _seed_literal_search(store: MemoryDictionaryStore | SqlDictionaryStore) -> None:
    store.create(_record("cl_wildx", "wildx", ("open",)))
    store.create(_record("cl_wild_mark", "wild_mark", ("open",)))
    store.create(_record("cl_pct", "other", ("open",), display_name="100% done"))


def _assert_literal_search(store: MemoryDictionaryStore | SqlDictionaryStore) -> None:
    underscore, underscore_total = store.list_dictionaries(
        q="wild_", statuses=None, limit=50, offset=0
    )
    assert underscore_total == 1
    assert [item.name for item in underscore] == ["wild_mark"]

    percent, percent_total = store.list_dictionaries(
        q="%", statuses=None, limit=50, offset=0
    )
    assert percent_total == 1
    assert [item.id for item in percent] == ["cl_pct"]

    _unfiltered, unfiltered_total = store.list_dictionaries(
        q=None, statuses=None, limit=50, offset=0
    )
    assert unfiltered_total == 3
    assert percent_total != unfiltered_total


def _integrity(constraint: str | None) -> IntegrityError:
    orig = SimpleNamespace(pgcode="23505", sqlstate="23505", constraint_name=constraint)
    orig.diag = SimpleNamespace(constraint_name=constraint)
    return IntegrityError("INSERT", {}, orig)


def _raising_scope(exc: IntegrityError):
    @contextmanager
    def session_scope() -> Iterator[object]:
        class Session:
            def add(self, _row: object) -> None:
                return None

            def flush(self) -> None:
                raise exc

        yield Session()

    return session_scope


def test_sql_list_filters_by_status(sql_store) -> None:
    store, _probe = sql_store
    store.create(_record("cl_live", "live_codes", ("open",)))
    store.create(
        _record("cl_old", "old_codes", ("open",), deprecated_at=_LATER)
    )

    available, available_total = store.list_dictionaries(
        q=None, statuses=frozenset({"available"}), limit=50, offset=0
    )
    assert available_total == 1
    assert [item.id for item in available] == ["cl_live"]

    deprecated, deprecated_total = store.list_dictionaries(
        q=None, statuses=frozenset({"deprecated"}), limit=50, offset=0
    )
    assert deprecated_total == 1
    assert [item.id for item in deprecated] == ["cl_old"]

    named, named_total = store.list_dictionaries(
        q="live", statuses=frozenset({"deprecated"}), limit=50, offset=0
    )
    assert named_total == 0
    assert named == []


def _record(
    dictionary_id: str,
    name: str,
    codes: tuple[str, ...],
    *,
    display_name: str = "Order status",
    revision: int = 1,
    deprecated_at: datetime | None = None,
) -> DictionaryRecord:
    return DictionaryRecord(
        id=dictionary_id,
        name=name,
        display_name=display_name,
        description=None,
        revision=revision,
        deprecated_at=deprecated_at,
        entries=tuple(
            DictionaryEntryRecord(code=code, label=code, active=True, position=index)
            for index, code in enumerate(codes)
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )
