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


def test_sql_node_during_a_channel_run_stays_unattributed() -> None:
    probe = None
    try:
        probe = create_engine(_MAINTENANCE)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"entity database is not available: {exc}")
    finally:
        if probe is not None:
            probe.dispose()
    from backend.channel.nodes import list_node_types
    from backend.entity.change_log import (
        ChangeLogEffective,
        ensure_shared_relations,
        install_triggers,
        list_entries,
        write_effective,
    )
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.ids import new_entity_id
    from backend.entity.records import AttributeRecord
    from backend.tests.channel_hooks_fake import FakeHooks

    table = "material__v1__0123456789abcdef"
    attributes = [AttributeRecord(name="code", type="text")]
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_chsqlu") as urls:
        admin = create_engine(urls.admin_url)
        with admin.begin() as conn:
            conn.execute(
                text(
                    f"CREATE TABLE entity_data.{table} (row_id bigint, code text)"
                )
            )
            conn.execute(
                text(
                    f"ALTER TABLE entity_data.{table} OWNER TO \"{ENTITY_OWNER_ROLE}\""
                )
            )
        admin.dispose()
        os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
        reset_settings_cache()
        reset_entity_engine()
        try:
            entity_id = new_entity_id()
            engine = get_entity_engine()
            with engine.begin() as conn:
                ensure_shared_relations(conn)
                write_effective(
                    conn,
                    ChangeLogEffective(
                        entity_id=entity_id,
                        recording=True,
                        retention_days=None,
                        applied_version_id=None,
                    ),
                )
                install_triggers(conn, entity_id, [table])
            execute = next(
                item.execute for item in list_node_types() if item.type_id == "read.sql"
            )
            hooks = FakeHooks(run_id="job_sql_run", channel_id="chn_sql")
            result = execute(
                {
                    "id": "nd_sql",
                    "type": "read.sql",
                    "config": {
                        "source": {"kind": "entity"},
                        "sql": (
                            f"INSERT INTO {table} (row_id, code) VALUES (3, 'C')"
                        ),
                        "statement_timeout_sec": 30,
                    },
                },
                hooks,
            )
            assert result.status == "succeeded", result.error_message
            assert result.output["rowcount"] == 1
            with engine.begin() as conn:
                entries = list_entries(conn, entity_id, attributes)
            assert [(entry.operation, entry.source, entry.subject) for entry in entries] == [
                ("insert", None, None)
            ]
        finally:
            reset_entity_engine()
            reset_settings_cache()
