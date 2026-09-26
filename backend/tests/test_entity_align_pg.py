"""Postgres accepts generated Entity Table DDL (narrow integration)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.entity.records import AttributeRecord
from backend.entity.table_port import PostgresEntityTablePort

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


def test_generated_ddl_accepted_by_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")

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

    port = PostgresEntityTablePort()
    table = f"entity_ddl_{uuid.uuid4().hex[:10]}"
    schema = "public"
    port.publish_table(
        schema,
        table,
        [
            AttributeRecord("sku", "string", False, None, True, False),
            AttributeRecord("note", "string", True, None, False, True),
        ],
        archive_as=None,
        archive_attributes=None,
    )
    assert port.table_exists(schema, table)
    port.drop_table(schema, table)
    assert port.table_exists(schema, table) is False
    reset_entity_engine()
    reset_settings_cache()
