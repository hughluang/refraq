"""Entity list ``q`` is a literal substring on both store adapters.

The SQL case uses sqlite. Default pytest never opens Postgres.
``entity_versions`` uses JSONB, which sqlite cannot compile, and
``list_entities`` does not read that table, so the SQL fixture creates
``business_entities`` only. The memory case uses the same expected names.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.core.db import Base
from backend.entity.models import BusinessEntityRow
from backend.entity.records import BusinessEntityRecord, EntityVersionRecord
from backend.entity.store import MemoryEntityStore, SqlEntityStore

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def sql_store(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[SqlEntityStore, Session]]:
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

    Base.metadata.create_all(engine, tables=[BusinessEntityRow.__table__])

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

    monkeypatch.setattr("backend.entity.store.session_scope", session_scope)
    probe = Session(engine, autoflush=False, autocommit=False)
    try:
        yield SqlEntityStore(), probe
    finally:
        probe.close()
        engine.dispose()


def test_list_treats_percent_and_underscore_as_literal(sql_store) -> None:
    store, probe = sql_store
    probe.add(_row("ent_wildx", "wildx", "Alpha"))
    probe.add(_row("ent_wild_mark", "wild_mark", "Beta"))
    probe.add(_row("ent_pct", "other", "100% done"))
    probe.commit()

    _assert_literal_search(store)


def test_memory_list_treats_percent_and_underscore_as_literal() -> None:
    store = MemoryEntityStore()
    store.create_entity(
        _entity("ent_wildx", "wildx", "Alpha"),
        _version("ver_wildx", "ent_wildx"),
    )
    store.create_entity(
        _entity("ent_wild_mark", "wild_mark", "Beta"),
        _version("ver_wild_mark", "ent_wild_mark"),
    )
    store.create_entity(
        _entity("ent_pct", "other", "100% done"),
        _version("ver_pct", "ent_pct"),
    )
    _assert_literal_search(store)


def _assert_literal_search(store: MemoryEntityStore | SqlEntityStore) -> None:
    underscore, underscore_total = store.list_entities(
        q="wild_", statuses=None, limit=50, offset=0
    )
    assert underscore_total == 1
    assert [item.table_name for item in underscore] == ["wild_mark"]

    percent, percent_total = store.list_entities(
        q="%", statuses=None, limit=50, offset=0
    )
    assert percent_total == 1
    assert [item.id for item in percent] == ["ent_pct"]

    _unfiltered, unfiltered_total = store.list_entities(
        q=None, statuses=None, limit=50, offset=0
    )
    assert unfiltered_total == 3
    assert percent_total != unfiltered_total


def _entity(entity_id: str, table_name: str, name: str) -> BusinessEntityRecord:
    return BusinessEntityRecord(
        id=entity_id,
        table_name=table_name,
        name=name,
        description="A stock-keeping material.",
        deprecated_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _version(version_id: str, entity_id: str) -> EntityVersionRecord:
    return EntityVersionRecord(
        id=version_id,
        entity_id=entity_id,
        version=1,
        attributes=[],
        materialized_attributes=[],
        publish_status="unpublished",
        latest_reconcile_job_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _row(entity_id: str, table_name: str, name: str) -> BusinessEntityRow:
    return BusinessEntityRow(
        id=entity_id,
        table_name=table_name,
        name=name,
        description="A stock-keeping material.",
        deprecated_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
