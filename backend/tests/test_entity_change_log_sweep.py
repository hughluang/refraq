"""Retention sweep for entity change-log entries.

The sweep is the public duty. Entries are planted with known timestamps.
Reads go through the change-log list. Postgres is required.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from backend.core.config import reset_settings_cache
from backend.core.time import FixedClock, reset_clock, set_clock
from backend.entity.change_log import (
    CHANGE_LOG_SCHEMA,
    ENTRY_TABLE,
    ChangeLogEffective,
    ensure_shared_relations,
    list_entries,
    read_effective,
    write_effective,
)
from backend.entity.ddl import qualified_table
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.ids import new_entity_id
from backend.entity.records import AttributeRecord
from backend.entity.tasks import purge_expired_change_logs
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
_OLDER = datetime(2026, 8, 8, 23, 59, 59, tzinfo=timezone.utc)
_CUTOFF = datetime(2026, 8, 9, tzinfo=timezone.utc)
_INSIDE = datetime(2026, 8, 15, tzinfo=timezone.utc)
_VERSION = "ver_0123456789abcd"
_ATTRIBUTES = (AttributeRecord(name="sku", type="string", max_length=32),)


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
    with bootstrapped_entity_database(
        _MAINTENANCE_DATABASE_URL, "refraq_clsweep"
    ) as urls:
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


def _plant(
    entity_id: str,
    *,
    recording: bool,
    retention_days: int | None,
    stamps: tuple[datetime, ...],
) -> None:
    engine = get_entity_engine()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity_id,
                recording=recording,
                retention_days=retention_days,
                applied_version_id=_VERSION,
            ),
        )
        for seq, occurred_at in enumerate(stamps, start=1):
            conn.execute(
                text(
                    f"INSERT INTO {qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)} "
                    "(entity_id, physical_table, operation, seq, occurred_at, "
                    "source, subject, image) "
                    "VALUES (:entity_id, :physical_table, 'insert', :seq, "
                    ":occurred_at, NULL, NULL, CAST(:image AS jsonb))"
                ),
                {
                    "entity_id": entity_id,
                    "physical_table": "entity_data.sweep",
                    "seq": seq,
                    "occurred_at": occurred_at,
                    "image": json.dumps(
                        {"after": {"row_id": seq, "sku": f"row-{seq}"}}
                    ),
                },
            )


def test_sweep_drops_entries_older_than_retention_and_keeps_the_cutoff(
    change_log_database,
) -> None:
    del change_log_database
    entity_id = new_entity_id()
    _plant(
        entity_id,
        recording=True,
        retention_days=7,
        stamps=(_OLDER, _CUTOFF, _INSIDE),
    )
    set_clock(FixedClock(_NOW))
    try:
        purge_expired_change_logs()
        engine = get_entity_engine()
        with engine.begin() as conn:
            entries = list_entries(conn, entity_id, _ATTRIBUTES)
            effective = read_effective(conn, entity_id)
    finally:
        reset_clock()

    assert {entry.occurred_at for entry in entries} == {_CUTOFF, _INSIDE}
    assert effective == ChangeLogEffective(
        entity_id=entity_id,
        recording=True,
        retention_days=7,
        applied_version_id=_VERSION,
    )


def test_never_expire_removes_nothing(change_log_database) -> None:
    del change_log_database
    entity_id = new_entity_id()
    _plant(
        entity_id,
        recording=True,
        retention_days=None,
        stamps=(_OLDER,),
    )
    set_clock(FixedClock(_NOW))
    try:
        purge_expired_change_logs()
        engine = get_entity_engine()
        with engine.begin() as conn:
            entries = list_entries(conn, entity_id, _ATTRIBUTES)
            effective = read_effective(conn, entity_id)
    finally:
        reset_clock()

    assert [entry.occurred_at for entry in entries] == [_OLDER]
    assert effective == ChangeLogEffective(
        entity_id=entity_id,
        recording=True,
        retention_days=None,
        applied_version_id=_VERSION,
    )


def test_recording_off_removes_nothing(change_log_database) -> None:
    del change_log_database
    entity_id = new_entity_id()
    _plant(
        entity_id,
        recording=False,
        retention_days=7,
        stamps=(_OLDER,),
    )
    set_clock(FixedClock(_NOW))
    try:
        purge_expired_change_logs()
        engine = get_entity_engine()
        with engine.begin() as conn:
            entries = list_entries(conn, entity_id, _ATTRIBUTES)
            effective = read_effective(conn, entity_id)
    finally:
        reset_clock()

    assert [entry.occurred_at for entry in entries] == [_OLDER]
    assert effective == ChangeLogEffective(
        entity_id=entity_id,
        recording=False,
        retention_days=7,
        applied_version_id=_VERSION,
    )


def test_sweep_task_drops_expired_entries_without_minting_a_job(
    change_log_database,
) -> None:
    del change_log_database
    from dataclasses import replace

    from backend.jobs.store import get_job_store
    from backend.worker.api import ensure_system_schedules
    from backend.worker.app import celery_app
    from backend.worker.schedules import get_schedule_store
    from backend.worker.tasks import purge_change_logs

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    entity_id = new_entity_id()
    _plant(
        entity_id,
        recording=True,
        retention_days=7,
        stamps=(_OLDER, _OLDER, _CUTOFF),
    )
    set_clock(FixedClock(_NOW))
    try:
        ensure_system_schedules()
        seeded = get_schedule_store().get_by_key("entity_change_log_retention")
        assert seeded is not None
        get_schedule_store().upsert(
            replace(seeded, last_run_at=_INSIDE, next_run_at=_NOW)
        )
        result = purge_change_logs()
        engine = get_entity_engine()
        with engine.begin() as conn:
            entries = list_entries(conn, entity_id, _ATTRIBUTES)
            effective = read_effective(conn, entity_id)
        _jobs, total = get_job_store().list()
        refreshed = get_schedule_store().get_by_key("entity_change_log_retention")
        assert refreshed is not None
        purge_change_logs()
        again = get_schedule_store().get_by_key("entity_change_log_retention")
    finally:
        reset_clock()

    assert result == {"deleted": 2}
    assert [entry.occurred_at for entry in entries] == [_CUTOFF]
    assert effective == ChangeLogEffective(
        entity_id=entity_id,
        recording=True,
        retention_days=7,
        applied_version_id=_VERSION,
    )
    assert total == 0
    assert refreshed.last_run_at == _NOW
    assert refreshed.next_run_at == datetime(2026, 8, 17, tzinfo=timezone.utc)
    assert again is not None
    assert again.next_run_at == refreshed.next_run_at
    assert again.last_run_at == refreshed.last_run_at
