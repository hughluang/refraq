"""Focused real target counters and lock ordering; requires a disposable target."""

from dataclasses import asdict, replace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from backend.metadata.mirrors.bootstrap import create_generation
from backend.metadata.mirrors.types import Authority, Record
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn, target_request


@pytest.mark.integration
def test_distinct_live_events_include_noops_and_exclude_replay_and_snapshot(target_dsn):
    authority = Authority("source-" + uuid4().hex, "binding", 1, "runtime", 1, 1, "capture")
    mid, gid = "mir_" + uuid4().hex, uuid4().hex
    request = dict(target_request(authority), mirror_id=mid, generation_id=gid, operation_id=uuid4().hex)
    with psycopg.connect(target_dsn, autocommit=True) as admin:
        create_generation(admin, **request)
        with psycopg.connect(target_dsn) as applier:
            applier.execute("SET ROLE refraq_mirror_applier")
            def apply(records):
                return applier.execute("SELECT source_mirror_state.apply_batch(%s,%s,%s,%s)",
                    (Jsonb(asdict(authority)), gid, Jsonb(asdict(request["partition_identity"])),
                     Jsonb([asdict(record) for record in records]))).fetchone()[0]
            row = dict(tenant="test", id=1, amount=7.5, seen=None)
            first = Record(0, "orders", "capture", "upsert", "baseline", {"tenant": "test", "id": 1}, row, payload_bytes=100)
            apply([first])
            records = [replace(first, offset=1, origin="live"), replace(first, offset=2, origin="live"),
                       Record(3, "orders", "capture", "delete", "live", {"tenant": "missing", "id": 2}, None, payload_bytes=20),
                       Record(4, "orders", "capture", "control", "live", {}, None),
                       Record(5, "orders", "capture", "tombstone", "live", {}, None)]
            apply(records)
            apply(records)
            progress = applier.execute("SELECT source_mirror_state.diagnostic_progress(%s)", (gid,)).fetchone()[0]
            assert (progress["processed_events"], progress["processed_batches"], progress["processed_bytes"]) == (3, 1, 220)
            assert progress["applied_offset"] == 5 and progress["last_target_commit_at"]
            apply([replace(first, offset=6, origin="live", payload_bytes=None)])
            assert applier.execute("SELECT source_mirror_state.diagnostic_progress(%s)", (gid,)).fetchone()[0]["processed_bytes"] is None
            applier.commit()
        admin.execute("UPDATE source_mirror_state.generations SET status='published' WHERE id=%s", (gid,))
        admin.execute("UPDATE source_mirror_state.mirrors SET published_generation_id=%s WHERE id=%s", (gid, mid))
        table = admin.execute("SELECT table_name FROM source_mirror_state.generations WHERE id=%s", (gid,)).fetchone()[0]
        # A lifecycle writer can hold generation rows while a diagnostic count
        # takes AccessShare: no reverse acquisition of generation row locks.
        with psycopg.connect(target_dsn) as lifecycle, psycopg.connect(target_dsn) as reader:
            lifecycle.execute("SELECT id FROM source_mirror_state.generations WHERE id=%s FOR UPDATE", (gid,))
            reader.execute("SET ROLE refraq_mirror_applier")
            reader.execute("SET TRANSACTION READ ONLY")
            reader.execute("SET LOCAL statement_timeout='500ms'")
            reader.execute("SET LOCAL lock_timeout='50ms'")
            measured = reader.execute("SELECT source_mirror_state.diagnostic_row_count(%s)", (mid,)).fetchone()[0]
            assert measured["generation_id"] == gid and measured["row_count"] == 1
            reader.commit()
            # DML also proceeds while a count transaction retains AccessShare.
            reader.execute("SELECT source_mirror_state.diagnostic_row_count(%s)", (mid,))
            lifecycle.execute(sql.SQL("INSERT INTO source_mirror.{}(tenant,id) VALUES ('next',2)").format(sql.Identifier(table)))
            reader.rollback()
            lifecycle.rollback()
        # A concurrent DDL lock produces a bounded unavailable sample.
        with psycopg.connect(target_dsn) as ddl, psycopg.connect(target_dsn) as reader:
            ddl.execute(sql.SQL("LOCK TABLE source_mirror.{} IN ACCESS EXCLUSIVE MODE").format(sql.Identifier(table)))
            reader.execute("SET ROLE refraq_mirror_applier")
            reader.execute("SET LOCAL lock_timeout='50ms'")
            reader.execute("SET LOCAL statement_timeout='500ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                reader.execute("SELECT source_mirror_state.diagnostic_row_count(%s)", (mid,))
            reader.rollback()
            ddl.rollback()


@pytest.mark.integration
def test_diagnostic_store_migration_and_atomic_persistence(target_dsn):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from backend.metadata.mirrors import diagnostic_store

    engine = create_engine(target_dsn.replace("postgresql://", "postgresql+psycopg://"))
    migration = import_module("backend.alembic.versions.0105_source_diagnostics")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert "source_mirror_diagnostics" in inspect(connection).get_table_names()
    from contextlib import contextmanager
    from sqlalchemy.orm import Session
    @contextmanager
    def session_scope():
        with Session(engine) as session, session.begin():
            yield session
    try:
        store = diagnostic_store.DiagnosticStore(memory=False, transaction=session_scope)
        store.update("source", "source", lambda old: {"history": []})
        store.update("source", "source", lambda old: {"history": old["history"] + ["round"]})
        assert store.read("source", "source")["history"] == ["round"]
        assert store.all("source")["source"]["history"] == ["round"]
    finally:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
        engine.dispose()
