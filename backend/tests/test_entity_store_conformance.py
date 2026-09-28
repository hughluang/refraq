"""One set of assertions, both EntityStore adapters.

Default `pytest` exercises Memory only. The SQL parameter needs Compose
Postgres and skips without it, so the fast path stays fast while the
production adapter still has a way to be checked against the same contract.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.core.time import utc_now
from backend.entity.errors import EntityTableNameDup
from backend.entity.ids import new_entity_id, new_version_id
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)
from backend.entity.store import _is_entity_table_name_dup

INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_ENTITY_TABLES = "business_entities, entity_versions"

SKU = AttributeRecord(
    name="sku",
    type="string",
    required=True,
    unique=True,
    indexed=False,
    description="SKU code",
    max_length=32,
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


@pytest.fixture(params=["memory", "sql"])
def entity_store(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """An EntityStore of each flavour, empty, ready to write."""
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.entity.store import get_entity_store, reset_entity_store

    if request.param == "sql":
        if not _postgres_available():
            pytest.skip("Postgres not available (start: docker compose up -d)")
        from backend.core.entry import migrate_with_advisory_lock

        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
        monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
        reset_settings_cache()
        reset_db_singletons()
        reset_entity_store()
        migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)
        engine = create_engine(INTEGRATION_DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {_ENTITY_TABLES} RESTART IDENTITY CASCADE"))
        engine.dispose()
    else:
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        monkeypatch.setenv("DATABASE_URL", "")
        reset_settings_cache()
        reset_db_singletons()
        reset_entity_store()

    yield get_entity_store()
    reset_entity_store()
    reset_db_singletons()
    reset_settings_cache()


def _table_name() -> str:
    return f"e{uuid.uuid4().hex[:12]}"


def _entity(table_name: str) -> BusinessEntityRecord:
    now = utc_now()
    return BusinessEntityRecord(
        id=new_entity_id(),
        table_name=table_name,
        name="Material",
        description="A stock-keeping material at SKU grain.",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )


def _version(entity_id: str, number: int) -> EntityVersionRecord:
    now = utc_now()
    return EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity_id,
        version=number,
        attributes=[SKU],
        materialized_attributes=[],
        publish_status="unpublished",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )


def test_create_entity_persists_and_is_readable(entity_store) -> None:
    table_name = _table_name()
    entity = _entity(table_name)
    version = _version(entity.id, 1)
    created, saved_version = entity_store.create_entity(entity, version)
    assert created.id == entity.id
    assert saved_version.version == 1
    loaded = entity_store.get_entity(entity.id)
    assert loaded is not None
    assert loaded.table_name == table_name
    current = entity_store.current_version(entity.id)
    assert current is not None
    assert current.id == version.id


def test_create_version_unchanged_overlay(entity_store) -> None:
    entity = _entity(_table_name())
    v1 = _version(entity.id, 1)
    entity_store.create_entity(entity, v1)
    v2 = _version(entity.id, 2)
    saved = entity_store.create_version(v2)
    assert saved.version == 2
    current = entity_store.current_version(entity.id)
    assert current is not None
    assert current.id == v2.id


def test_duplicate_table_name_is_entity_table_name_dup(entity_store) -> None:
    table_name = _table_name()
    first = _entity(table_name)
    first_version = _version(first.id, 1)
    entity_store.create_entity(first, first_version)
    second = _entity(table_name)
    second_version = _version(second.id, 1)
    with pytest.raises(EntityTableNameDup):
        entity_store.create_entity(second, second_version)


def test_integrity_classifier_is_table_name_unique_only() -> None:
    assert _is_entity_table_name_dup(
        _integrity("23505", "uq_business_entities_table_name")
    )
    assert _is_entity_table_name_dup(_integrity("23505", None))
    assert not _is_entity_table_name_dup(
        _integrity("23505", "uq_entity_versions_entity_version")
    )
    assert not _is_entity_table_name_dup(
        _integrity("23503", "entity_versions_entity_id_fkey")
    )


def _integrity(pgcode: str, constraint: str | None) -> IntegrityError:
    orig = SimpleNamespace(pgcode=pgcode, sqlstate=pgcode, constraint_name=constraint)
    orig.diag = SimpleNamespace(constraint_name=constraint)
    return IntegrityError("INSERT", {}, orig)


def test_duplicate_version_number_is_not_code_conflict(entity_store) -> None:
    from backend.entity.store import SqlEntityStore

    if not isinstance(entity_store, SqlEntityStore):
        pytest.skip("version uniqueness is a SQL constraint")
    entity = _entity(_table_name())
    first = _version(entity.id, 1)
    entity_store.create_entity(entity, first)
    clash = _version(entity.id, 1)
    with pytest.raises(IntegrityError):
        entity_store.create_version(clash)
