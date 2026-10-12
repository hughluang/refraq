"""SQL node against a bootstrapped entity database."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from backend.channel.sql_read import SqlReadError, run_channel_sql
from backend.core.config import reset_settings_cache
from backend.entity.ddl import ENTITY_OWNER_ROLE
from backend.entity.entity_db import reset_entity_engine
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_ENTITY = {"kind": "entity"}


def test_sql_returns_rows_and_write_results() -> None:
    probe = None
    try:
        from sqlalchemy import create_engine as _engine

        probe = _engine(_MAINTENANCE)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"entity database is not available: {exc}")
    finally:
        if probe is not None:
            probe.dispose()
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_chsql") as urls:
        admin = create_engine(urls.admin_url)
        with admin.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE entity_data.material__v1__0123456789abcdef "
                    "(row_id bigint, code text)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO entity_data.material__v1__0123456789abcdef "
                    "(row_id, code) VALUES (1, 'A')"
                )
            )
            conn.execute(
                text(
                    "CREATE VIEW entity_data.material AS "
                    "SELECT * FROM entity_data.material__v1__0123456789abcdef"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE entity_data.material__v1__0123456789abcdef "
                    f'OWNER TO "{ENTITY_OWNER_ROLE}"'
                )
            )
            conn.execute(
                text(f'ALTER VIEW entity_data.material OWNER TO "{ENTITY_OWNER_ROLE}"')
            )
        admin.dispose()
        os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
        reset_settings_cache()
        reset_entity_engine()
        try:
            read = run_channel_sql(
                "SELECT code FROM material",
                source=_ENTITY,
                statement_timeout_sec=30,
            )
            assert read["rows"] == [{"code": "A"}]
            assert read["count"] == 1
            written = run_channel_sql(
                "INSERT INTO material__v1__0123456789abcdef (row_id, code) VALUES (2, 'B')",
                source=_ENTITY,
                statement_timeout_sec=30,
            )
            assert written == {"rows": [], "count": 0, "rowcount": 1}
            with pytest.raises(SqlReadError):
                run_channel_sql(
                    "SELECT pg_sleep(2)",
                    source=_ENTITY,
                    statement_timeout_sec=1,
                )
            with pytest.raises(SqlReadError) as over:
                run_channel_sql(
                    "SELECT g FROM generate_series(1, 100001) AS g",
                    source=_ENTITY,
                    statement_timeout_sec=30,
                )
            assert over.value.code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
        finally:
            reset_entity_engine()
            reset_settings_cache()
