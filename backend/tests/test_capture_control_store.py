"""Offline SQL persistence contracts; PostgreSQL locking still needs qualification."""

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session

from backend.metadata.capture.store import (
    load_binding,
    load_operation,
    save_binding,
    save_operation,
)
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.models import SourceCaptureBindingRow, SourceCaptureOperationRow


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("sources", metadata, Column("id", String(64), primary_key=True))
    SourceCaptureBindingRow.__table__.to_metadata(metadata)
    SourceCaptureOperationRow.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables["sources"].insert().values(id="source"))
    yield engine
    engine.dispose()


def test_migration_reserves_previously_cleared_capture_credentials(monkeypatch):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Integer, Text, select

    migration = importlib.import_module("backend.alembic.versions.0093_source_capture_control")
    engine = create_engine("sqlite://")
    metadata = MetaData()
    sources = Table(
        "sources", metadata,
        Column("id", String(64), primary_key=True),
        Column("capture_revision", Integer, nullable=False),
        Column("capture_credential_ciphertext", Text),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sources.insert(), [
            {"id": "never", "capture_revision": 0, "capture_credential_ciphertext": None},
            {"id": "cleared", "capture_revision": 2, "capture_credential_ciphertext": None},
            {"id": "configured", "capture_revision": 1, "capture_credential_ciphertext": "sealed"},
        ])
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        rows = connection.execute(select(SourceCaptureBindingRow.__table__)).mappings().all()
        assert {row["source_id"] for row in rows} == {"cleared", "configured"}
        assert all(row["state"]["desired"] == "blocked" for row in rows)
        assert all(row["state"]["control_revision"] == 0 for row in rows)
        assert connection.execute(select(SourceCaptureOperationRow.__table__)).all() == []
        migration.downgrade()
    engine.dispose()


def test_binding_and_outbox_rollback_together_and_retry_reuses_identity(database):
    state = {"source_id": "source", "binding_id": "binding", "capture_generation": 1}
    command = {
        "source_id": "source",
        "operation_id": "operation",
        "control_revision": 1,
    }
    with Session(database) as session:
        save_binding(session, state)
        save_operation(session, command)
        session.rollback()
    with Session(database) as session:
        assert load_binding(session, "source") is None
        assert load_operation(session, "operation") is None
        save_binding(session, state)
        save_operation(session, command)
        session.commit()
    with Session(database) as session:
        assert load_binding(session, "source") == state
        assert load_operation(session, "operation")["command"] == command
        save_operation(session, command)
        session.commit()
        with pytest.raises(SourceCaptureControlConflict):
            save_operation(session, {**command, "control_revision": 2})
        with pytest.raises(SourceCaptureControlConflict):
            save_binding(session, {**state, "binding_id": "retargeted"})


def test_source_capture_and_redacted_audit_rollback_in_one_sql_transaction(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from sqlalchemy import JSON, select

    from backend.admin.audit_store import SqlAuditStore
    from backend.admin.models import AuditEventRow
    from backend.core.time import utc_now
    from backend.metadata.capture import control
    from backend.metadata.models import SourceRow
    from backend.metadata.sources import service
    from backend.metadata.sources.store import SourceRecord, SqlSourceStore
    from backend.tests.test_sources_jobs import _access

    engine = create_engine("sqlite://")
    metadata = MetaData()
    for table in (SourceRow.__table__, AuditEventRow.__table__,
                  SourceCaptureBindingRow.__table__, SourceCaptureOperationRow.__table__):
        copied = table.to_metadata(metadata)
        for column in copied.columns:
            if isinstance(column.type, JSON):
                column.type = JSON()
    metadata.create_all(engine)
    store = SqlSourceStore()
    now = utc_now()
    record = SourceRecord(
        id="source", key="source", locator_key="unused", name="Source", kind="database",
        status="active", description=None, engine="postgresql",
        access_ciphertext=service.seal_access("postgresql", _access()),
        access_updated_at=now, created_at=now, updated_at=now,
    )
    with Session(engine) as session:
        store.create_source_on(session, record)
        session.commit()

    @contextmanager
    def transaction():
        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(control, "get_settings", lambda: SimpleNamespace(store_backend="persistent"))
    monkeypatch.setattr(control, "session_scope", transaction)
    monkeypatch.setattr(control, "get_source_store", lambda: store)
    monkeypatch.setattr(service, "get_source_store", lambda: store)
    monkeypatch.setattr(service, "_maybe_seed_after_update", lambda *args, **kwargs: [])
    write = SqlAuditStore.create_on

    def fail_after_audit(self, session, event):
        write(self, session, event)
        if event.action == "source.update":
            raise RuntimeError("abort after source audit")

    monkeypatch.setattr(SqlAuditStore, "create_on", fail_after_audit)
    with pytest.raises(RuntimeError, match="abort after source audit"):
        service.update_source(
            "source", capture_credential={"username": "capture", "password": "private"},
            patch_fields={"capture_credential"},
        )
    with Session(engine) as session:
        assert session.get(SourceRow, "source").capture_revision == 0
        assert load_binding(session, "source") is None
        assert session.scalars(select(SourceCaptureOperationRow)).all() == []
        assert session.scalars(select(AuditEventRow)).all() == []
    monkeypatch.setattr(SqlAuditStore, "create_on", write)
    service.update_source(
        "source", capture_credential={"username": "capture", "password": "private"},
        patch_fields={"capture_credential"},
    )
    with Session(engine) as session:
        assert session.get(SourceRow, "source").capture_revision == 1
        assert load_binding(session, "source")["control_revision"] == 1
        assert len(session.scalars(select(SourceCaptureOperationRow)).all()) == 1
        events = session.scalars(select(AuditEventRow)).all()
        assert {event.action for event in events} == {"source.capture_intent", "source.update"}
        assert "private" not in str([event.detail for event in events])
    engine.dispose()
