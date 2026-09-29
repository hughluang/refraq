"""Postgres accepts generated Entity Table DDL (narrow integration)."""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.entity.ddl import qualified_table
from backend.entity.records import AttributeRecord
from backend.entity.table_port import EntityTableHasRows, PostgresEntityTablePort

pytestmark = pytest.mark.integration

INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
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


def _bind_entity_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import reset_entity_engine

    monkeypatch.setenv("ENTITY_DATABASE_URL", INTEGRATION_DATABASE_URL)
    reset_settings_cache()
    reset_entity_engine()
    url = make_url(INTEGRATION_DATABASE_URL)
    if url.database:
        admin = create_engine(
            url.set(database=make_url(_MAINTENANCE_DATABASE_URL).database),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with admin.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": url.database},
                ).scalar()
                if not exists:
                    conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        finally:
            admin.dispose()


def _relation_present(schema: str, name: str) -> bool:
    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    with engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :name"
            ),
            {"schema": schema, "name": name},
        ).scalar()
    return found is not None


def _force_drop(schema: str, view: str, table: str) -> None:
    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP VIEW IF EXISTS {qualified_table(schema, view)}"))
        conn.execute(text(f"DROP TABLE IF EXISTS {qualified_table(schema, table)}"))


def test_generated_ddl_accepted_by_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import reset_entity_engine

    _bind_entity_database(monkeypatch)
    port = PostgresEntityTablePort()
    table = f"entity_ddl_{uuid.uuid4().hex[:10]}"
    schema = "public"
    port.create_physical_table(
        schema,
        table,
        [
            AttributeRecord(
                name="sku",
                type="string",
                required=True,
                unique=True,
                indexed=False,
                max_length=32,
            ),
            AttributeRecord(
                name="note",
                type="text",
                required=False,
                unique=False,
                indexed=True,
            ),
        ],
    )
    assert port.table_exists(schema, table)
    port.drop_table(schema, table)
    assert port.table_exists(schema, table) is False
    reset_entity_engine()
    reset_settings_cache()


def test_drop_head_removes_view_then_table(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import reset_entity_engine

    _bind_entity_database(monkeypatch)
    port = PostgresEntityTablePort()
    schema = "public"
    suffix = uuid.uuid4().hex[:10]
    table = f"entity_head_{suffix}"
    view = f"entity_stem_{suffix}"
    try:
        port.create_physical_table(schema, table, [])
        port.swap_stem_view(schema, view, physical=table, expected_target=None)
        port.drop_head(schema, table, view)
        assert port.table_exists(schema, table) is False
        assert _relation_present(schema, view) is False
    finally:
        _force_drop(schema, view, table)
        reset_entity_engine()
        reset_settings_cache()


def test_drop_head_keeps_view_when_table_has_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import get_entity_engine, reset_entity_engine

    _bind_entity_database(monkeypatch)
    port = PostgresEntityTablePort()
    schema = "public"
    suffix = uuid.uuid4().hex[:10]
    table = f"entity_head_{suffix}"
    view = f"entity_stem_{suffix}"
    try:
        port.create_physical_table(schema, table, [])
        port.swap_stem_view(schema, view, physical=table, expected_target=None)
        engine = get_entity_engine()
        with engine.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {qualified_table(schema, table)} DEFAULT VALUES")
            )
        with pytest.raises(EntityTableHasRows):
            port.drop_head(schema, table, view)
        assert port.table_exists(schema, table) is True
        assert _relation_present(schema, view) is True
    finally:
        _force_drop(schema, view, table)
        reset_entity_engine()
        reset_settings_cache()


def _row_count(schema: str, table: str) -> int:
    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text(f"SELECT count(*) FROM {qualified_table(schema, table)}")
        ).scalar()
    return int(count or 0)


def _drop_while_insert_open(
    port: PostgresEntityTablePort,
    path: str,
    schema: str,
    table: str,
    view: str,
) -> BaseException | None:
    """Run one drop path on another thread while a row insert stays uncommitted."""
    from backend.entity.entity_db import get_entity_engine

    engine = get_entity_engine()
    holder = engine.connect()
    caught: list[BaseException] = []
    finished = threading.Event()

    def run() -> None:
        try:
            if path == "revert":
                port.revert_physical_table(schema, table)
            elif path == "drop":
                port.drop_table(schema, table)
            else:
                port.drop_head(schema, table, view)
        except BaseException as exc:  # noqa: BLE001
            caught.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=run)
    try:
        transaction = holder.begin()
        holder.execute(
            text(f"INSERT INTO {qualified_table(schema, table)} DEFAULT VALUES")
        )
        worker.start()
        assert not finished.wait(0.5), "drop returned before the insert committed"
        transaction.commit()
        worker.join(timeout=10)
    finally:
        if holder.in_transaction():
            holder.rollback()
        holder.close()
        if worker.is_alive():
            worker.join(timeout=10)
    assert not worker.is_alive()
    return caught[0] if caught else None


@pytest.mark.parametrize("path", ["revert", "drop", "drop_head"])
def test_open_insert_keeps_rows_across_empty_drop(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

    from backend.core.config import reset_settings_cache
    from backend.entity.entity_db import reset_entity_engine

    _bind_entity_database(monkeypatch)
    port = PostgresEntityTablePort()
    schema = "public"
    suffix = uuid.uuid4().hex[:10]
    table = f"entity_race_{suffix}"
    view = f"entity_stem_{suffix}"
    try:
        port.create_physical_table(schema, table, [])
        if path == "drop_head":
            port.swap_stem_view(schema, view, physical=table, expected_target=None)
        error = _drop_while_insert_open(port, path, schema, table, view)
        assert isinstance(error, EntityTableHasRows)
        assert table in str(error)
        assert port.table_exists(schema, table) is True
        assert _row_count(schema, table) == 1
        if path == "drop_head":
            assert _relation_present(schema, view) is True
    finally:
        _force_drop(schema, view, table)
        reset_entity_engine()
        reset_settings_cache()
