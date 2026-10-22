"""Dataset tables in the entity database and the channel registry."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from sqlalchemy import create_engine, text

from backend.admin.system_parameters import IntConstraint
from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRecord,
    DatasetRegistry,
    MemoryDatasetStore,
    SqlDatasetStore,
)
from backend.channel.parameters import CHANNEL_PARAMETER_SPECS
from backend.core.time import utc_now
from backend.entity.bootstrap import schema_statements
from backend.entity.datasets import (
    create_table_from_query,
    normalized_type_of,
    physical_relation,
    postgres_type,
)
from backend.entity.ddl import ENTITY_OWNER_ROLE, READER_ROLE, ident
from backend.metadata.catalog.normalized_type import CLOSED_NORMALIZED_TYPES
from backend.tests.entity_pg import bootstrapped_entity_database

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)


def test_bootstrap_schema_statements_isolate_channel_dataset() -> None:
    statements = schema_statements()
    schema = ident("channel_dataset")
    owner = ident(ENTITY_OWNER_ROLE)
    reader = ident(READER_ROLE)
    text = "\n".join(statements)
    assert f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {owner}" in statements
    assert f"ALTER SCHEMA {schema} OWNER TO {owner}" in statements
    assert f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC" in statements
    assert f"REVOKE ALL ON SCHEMA {schema} FROM {reader}" in statements
    assert f"GRANT USAGE ON SCHEMA {schema}" not in text
    assert "ROW LEVEL SECURITY" not in text
    assert "entity_data" in text


def test_postgres_type_maps_every_normalized_type() -> None:
    mapped = {
        "string": "text",
        "integer": "bigint",
        "number": "double precision",
        "boolean": "boolean",
        "date": "date",
        "interval": "interval",
        "binary": "bytea",
        "json": "jsonb",
        "array": "jsonb",
        "unknown": "text",
    }
    assert set(mapped) | {"decimal", "timestamp", "time"} == set(CLOSED_NORMALIZED_TYPES)
    for normalized, physical in mapped.items():
        assert postgres_type(normalized) == physical
    assert postgres_type("decimal") == "numeric"
    assert postgres_type("decimal", precision=10, scale=2) == "numeric(10,2)"
    assert postgres_type("decimal", precision=12) == "numeric(12,0)"
    assert postgres_type("timestamp") == "timestamp without time zone"
    assert postgres_type("timestamp", with_time_zone=True) == "timestamp with time zone"
    assert postgres_type("time") == "time without time zone"
    assert postgres_type("time", with_time_zone=True) == "time with time zone"
    with pytest.raises(ValueError):
        postgres_type("not-a-type")
    with pytest.raises(ValueError):
        postgres_type("decimal", precision=10, scale=11)


def test_physical_type_folds_back_to_a_normalized_type() -> None:
    expected = {
        "text": "string",
        "character varying": "string",
        "character varying(40)": "string",
        "varchar(40)": "string",
        "smallint": "integer",
        "integer": "integer",
        "bigint": "integer",
        "real": "number",
        "double precision": "number",
        "numeric": "decimal",
        "numeric(12)": "decimal",
        "numeric(10,2)": "decimal",
        "boolean": "boolean",
        "date": "date",
        "timestamp with time zone": "timestamp",
        "timestamp without time zone": "timestamp",
        "timestamp(3) without time zone": "timestamp",
        "timestamp(0) with time zone": "timestamp",
        "time with time zone": "time",
        "time without time zone": "time",
        "time(3) without time zone": "time",
        "interval": "interval",
        "bytea": "binary",
        "json": "json",
        "jsonb": "json",
    }
    for physical, normalized in expected.items():
        assert normalized_type_of(physical) == normalized
    assert normalized_type_of("geometry") == "unknown"


def test_one_select_strips_every_trailing_semicolon() -> None:
    from backend.entity.datasets import _one_select

    assert _one_select("SELECT 1 AS n;;") == "SELECT 1 AS n"
    assert _one_select("SELECT 1 AS n;") == "SELECT 1 AS n"
    assert _one_select("  SELECT 1 AS n ; ; ") == "SELECT 1 AS n"
    with pytest.raises(ValueError):
        _one_select("SELECT 1; SELECT 2")
    with pytest.raises(ValueError):
        _one_select("SELECT 1; /* c */")
    assert _one_select("VALUES (1)") == "VALUES (1)"
    with pytest.raises(ValueError, match="dataset query must be one SELECT"):
        _one_select(
            "WITH t AS (INSERT INTO x VALUES (1) RETURNING *) SELECT * FROM t"
        )


def test_create_table_from_query_rejects_data_modifying_statements() -> None:
    relation = physical_relation("dwrite")
    for query in (
        "WITH t AS (INSERT INTO x VALUES (1) RETURNING *) SELECT * FROM t",
        "INSERT INTO x VALUES (1)",
        "UPDATE x SET n = 1",
        "DELETE FROM x",
        "MERGE INTO x USING y ON true WHEN MATCHED THEN DELETE",
    ):
        with pytest.raises(ValueError, match="dataset query must be one SELECT"):
            create_table_from_query(relation, query)


def test_physical_relation_quotes_a_bounded_identifier() -> None:
    assert physical_relation("d" + "a" * 8) == '"channel_dataset"."ds_daaaaaaaa"'
    with pytest.raises(ValueError):
        physical_relation("1bad")
    with pytest.raises(ValueError):
        physical_relation("has-dash")
    with pytest.raises(ValueError):
        physical_relation("a" * 61)


def test_dataset_reference_schema_names_id_columns_and_count() -> None:
    assert DATASET_REFERENCE_SCHEMA["x-refraq-dataset-reference"] is True
    assert "relation" not in DATASET_REFERENCE_SCHEMA["properties"]
    value = dataset_reference(
        dataset_id="dabc",
        columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
        count=2,
    )
    assert value == {
        "dataset_id": "dabc",
        "columns": [{"name": "n", "type": "integer"}],
        "count": 2,
    }
    Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate(value)
    with pytest.raises(ValidationError):
        Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate({**value, "relation": "channel_dataset.ds_dabc"})


_PARAMETER_BOUNDS = {
    "channel_dataset_retention_days": (7, 1, 3650),
    "channel_dataset_success_retention_hours": (24, 0, 720),
    "channel_dataset_max_total_gb": (100, 1, 100000),
}


def test_dataset_parameters_match_the_plan_and_both_locales() -> None:
    specs = {spec.key: spec for spec in CHANNEL_PARAMETER_SPECS}
    for key, (seed, minimum, maximum) in _PARAMETER_BOUNDS.items():
        spec = specs[key]
        assert spec.seed == seed
        assert spec.owner == "channel"
        assert spec.group == "data_channel"
        assert isinstance(spec.constraint, IntConstraint)
        assert spec.constraint.minimum == minimum
        assert spec.constraint.maximum == maximum
        assert spec.label_key == f"settings.parameter.{key}.label"
        assert spec.help_key == f"settings.parameter.{key}.help"
        assert spec.apply_note_key == f"settings.parameter.{key}.apply"
    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "locales"
    for locale in ("en-US", "zh-CN"):
        catalog = json.loads((root / locale / "common.json").read_text(encoding="utf-8"))
        assert catalog["settings.group.data_channel"]
        for key in _PARAMETER_BOUNDS:
            assert catalog[f"settings.parameter.{key}.label"]
            assert catalog[f"settings.parameter.{key}.help"]
            assert catalog[f"settings.parameter.{key}.apply"]


def _record(dataset_id: str, *, status: str, size_bytes: int) -> DatasetRecord:
    return DatasetRecord(
        id=dataset_id,
        job_id="job_1",
        node_id="node_1",
        seq=1,
        relation=physical_relation(dataset_id),
        columns=[{"name": "n", "type": "bigint"}],
        row_count=3,
        size_bytes=size_bytes,
        status=status,
        created_at=utc_now(),
        expires_at=None,
    )


def test_memory_registry_sums_loading_and_ready_bytes() -> None:
    store = MemoryDatasetStore()
    store.save(_record("dready", status="ready", size_bytes=10))
    store.save(_record("dloading", status="loading", size_bytes=5))
    store.save(_record("ddropped", status="dropped", size_bytes=100))
    loaded = store.get("dready")
    assert loaded is not None
    assert loaded.status == "ready"
    assert loaded.expires_at is None
    assert loaded.relation == '"channel_dataset"."ds_dready"'
    assert store.used_bytes() == 15
    loaded.status = "dropped"
    assert store.used_bytes() == 15


def test_create_from_query_stops_at_capacity_before_a_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )

    def forbid(relation: str, query: str) -> tuple[int, int]:
        raise AssertionError(f"table create {relation} {query}")

    monkeypatch.setattr("backend.channel.dataset_registry.create_table_from_query", forbid)
    store = MemoryDatasetStore()
    store.save(_record("dplanted", status="ready", size_bytes=1024**3))
    registry = DatasetRegistry(store)
    with pytest.raises(DatasetQuotaExceeded) as caught:
        registry.create_from_query(
            job_id="job_1",
            node_id="node_2",
            seq=2,
            query="SELECT 1 AS n",
        )
    assert caught.value.code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert list(store._rows) == ["dplanted"]


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def dataset_registry(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_ds") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        from backend.core.config import reset_settings_cache
        from backend.entity.entity_db import reset_entity_engine

        reset_settings_cache()
        reset_entity_engine()
        from backend.worker.parameters import assemble_system_parameters

        assemble_system_parameters()
        store = MemoryDatasetStore()
        registry = DatasetRegistry(store)
        try:
            yield registry, store
        finally:
            reset_entity_engine()
            reset_settings_cache()


@pytest.mark.integration
def test_ctas_resolves_unqualified_names_in_entity_data(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    from backend.entity.datasets import read_keyset_page
    from backend.entity.entity_db import get_entity_engine

    _registry, _store = dataset_registry
    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql("CREATE TABLE entity_data.ds_probe (label text)")
        conn.exec_driver_sql("INSERT INTO entity_data.ds_probe (label) VALUES ('kept')")
    relation = physical_relation("dpath")
    row_count, _size = create_table_from_query(relation, "SELECT label FROM ds_probe")
    assert row_count == 1
    page = read_keyset_page(relation, after_ord=0, limit=10)
    assert [row["label"] for row in page] == ["kept"]


@pytest.mark.integration
def test_ctas_round_trip_stores_rows_without_rls(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, _store = dataset_registry
    record = registry.create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS t(n, label)",
    )
    assert record.status == "ready"
    assert record.row_count == 2
    assert record.size_bytes > 0
    assert record.expires_at is None
    assert record.relation == physical_relation(record.id)
    assert {column["name"]: column["type"] for column in record.columns} == {
        "n": "integer",
        "label": "text",
    }
    assert {column["name"]: column["normalized_type"] for column in record.columns} == {
        "n": "integer",
        "label": "string",
    }
    reference = dataset_reference(
        dataset_id=record.id, columns=record.columns, count=record.row_count
    )
    assert reference["columns"] == [
        {"name": "n", "type": "integer"},
        {"name": "label", "type": "string"},
    ]
    assert "relation" not in reference
    page = registry.read_page(record.id, after_ord=0, limit=10)
    assert {(row["n"], row["label"]) for row in page} == {(1, "a"), (2, "b")}
    assert registry.is_lost(record.id) is False
    from backend.entity.entity_db import get_entity_engine

    table = f"ds_{record.id}"
    with get_entity_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT n.nspname, c.relrowsecurity, c.relpersistence, r.rolname
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                JOIN pg_roles AS r ON r.oid = c.relowner
                WHERE c.relname = :name
                """
            ),
            {"name": table},
        ).one()
    assert row.nspname == "channel_dataset"
    assert row.relrowsecurity is False
    assert row.relpersistence == "u"
    assert row.rolname == ENTITY_OWNER_ROLE


@pytest.mark.integration
def test_ctas_embeds_a_trailing_comment_and_extra_semicolons(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, _store = dataset_registry
    commented = registry.create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT 1 AS n -- tail",
    )
    assert commented.status == "ready"
    assert commented.row_count == 1
    assert registry.read_page(commented.id, after_ord=0, limit=5)[0]["n"] == 1
    doubled = registry.create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=2,
        query="SELECT 2 AS n;;",
    )
    assert doubled.row_count == 1
    assert registry.read_page(doubled.id, after_ord=0, limit=5)[0]["n"] == 2


@pytest.mark.integration
def test_keyset_page_continues_after_ord(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, _store = dataset_registry
    record = registry.create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT * FROM (VALUES (10), (20), (30)) AS t(n)",
    )
    first = registry.read_page(record.id, after_ord=0, limit=2)
    assert len(first) == 2
    assert first[0]["_ord"] < first[1]["_ord"]
    second = registry.read_page(record.id, after_ord=first[-1]["_ord"], limit=2)
    assert [row["_ord"] for row in second] == [first[-1]["_ord"] + 1]
    assert {row["n"] for row in first + second} == {10, 20, 30}


@pytest.mark.integration
def test_truncated_table_with_a_row_count_is_lost(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, _store = dataset_registry
    record = registry.create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT * FROM (VALUES (1), (2)) AS t(n)",
    )
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE {record.relation}")
    assert registry.is_lost(record.id) is True


@pytest.mark.integration
def test_failed_load_marks_dropped_and_leaves_no_table(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, store = dataset_registry
    with pytest.raises(ValueError):
        registry.create_from_query(
            job_id="job_1",
            node_id="node_1",
            seq=1,
            query="THIS IS NOT SQL",
        )
    rows = list(store._rows.values())
    assert len(rows) == 1
    assert rows[0].status == "dropped"
    assert rows[0].expires_at is None
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        present = conn.execute(
            text(
                """
                SELECT EXISTS (
                  SELECT 1 FROM pg_class AS c
                  JOIN pg_namespace AS n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'channel_dataset' AND c.relkind = 'r'
                )
                """
            )
        ).scalar_one()
    assert present is False


@pytest.mark.integration
def test_chunked_copy_round_trip_uses_normalized_types(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
) -> None:
    registry, _store = dataset_registry
    seen = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    record = registry.create_from_chunks(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        columns=[
            DatasetColumnSpec("n", "integer"),
            DatasetColumnSpec("label", "string"),
            DatasetColumnSpec("amount", "decimal", precision=10, scale=2),
            DatasetColumnSpec("seen", "timestamp", with_time_zone=True),
        ],
        chunks=[
            [(1, "a", Decimal("1.50"), seen), (2, "b", Decimal("2.00"), seen)],
            [(3, "c", Decimal("3.25"), seen)],
        ],
    )
    assert record.status == "ready"
    assert record.row_count == 3
    assert record.size_bytes > 0
    assert record.expires_at is None
    assert {column["name"]: column["type"] for column in record.columns} == {
        "n": "bigint",
        "label": "text",
        "amount": "numeric(10,2)",
        "seen": "timestamp with time zone",
    }
    assert {column["name"]: column["normalized_type"] for column in record.columns} == {
        "n": "integer",
        "label": "string",
        "amount": "decimal",
        "seen": "timestamp",
    }
    reference = dataset_reference(
        dataset_id=record.id, columns=record.columns, count=record.row_count
    )
    assert reference["columns"] == [
        {"name": "n", "type": "integer"},
        {"name": "label", "type": "string"},
        {"name": "amount", "type": "decimal"},
        {"name": "seen", "type": "timestamp"},
    ]
    first = registry.read_page(record.id, after_ord=0, limit=2)
    assert [row["_ord"] for row in first] == [1, 2]
    assert [row["n"] for row in first] == [1, 2]
    second = registry.read_page(record.id, after_ord=2, limit=2)
    assert [(row["_ord"], row["n"], row["label"]) for row in second] == [(3, 3, "c")]
    assert second[0]["amount"] == Decimal("3.25")
    assert registry.is_lost(record.id) is False


def _plant(store: MemoryDatasetStore, dataset_id: str, size_bytes: int) -> None:
    store.save(_record(dataset_id, status="ready", size_bytes=size_bytes))


@pytest.mark.integration
def test_create_from_query_does_not_leave_a_table_at_capacity(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )
    registry, store = dataset_registry
    _plant(store, "dplanted", 1024**3)
    with pytest.raises(DatasetQuotaExceeded) as caught:
        registry.create_from_query(
            job_id="job_1",
            node_id="node_2",
            seq=2,
            query="SELECT 1 AS n",
        )
    assert caught.value.code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert list(store._rows) == ["dplanted"]
    assert _dataset_table_exists() is False


@pytest.mark.integration
def test_ctas_stays_ready_when_finished_size_crosses_capacity(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )
    registry, store = dataset_registry
    _plant(store, "dplanted", 1024**3 - 1)
    record = registry.create_from_query(
        job_id="job_1",
        node_id="node_2",
        seq=2,
        query="SELECT 1 AS n",
    )
    assert record.status == "ready"
    assert store.used_bytes() >= 1024**3
    assert _dataset_table_exists() is True


@pytest.mark.integration
def test_chunked_load_drops_the_table_when_a_chunk_crosses_capacity(
    dataset_registry: tuple[DatasetRegistry, MemoryDatasetStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )
    registry, store = dataset_registry
    _plant(store, "dplanted", 1024**3 - 1)
    with pytest.raises(DatasetQuotaExceeded) as caught:
        registry.create_from_chunks(
            job_id="job_1",
            node_id="node_2",
            seq=2,
            columns=[DatasetColumnSpec("n", "integer"), DatasetColumnSpec("label", "string")],
            chunks=[[(1, "a")]],
        )
    assert caught.value.code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    created = [row for row in store._rows.values() if row.id != "dplanted"]
    assert len(created) == 1
    assert created[0].status == "dropped"
    assert _dataset_table_exists() is False


def _dataset_table_exists() -> bool:
    from backend.entity.entity_db import get_entity_engine

    with get_entity_engine().connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM pg_class AS c
                      JOIN pg_namespace AS n ON n.oid = c.relnamespace
                      WHERE n.nspname = 'channel_dataset' AND c.relkind = 'r'
                    )
                    """
                )
            ).scalar_one()
        )


@pytest.mark.integration
def test_bootstrap_revokes_channel_dataset_from_public_and_reader() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_dsacl") as urls:
        engine = create_engine(urls.admin_url)
        try:
            with engine.connect() as conn:
                owner = conn.execute(
                    text(
                        """
                        SELECT r.rolname
                        FROM pg_namespace AS n
                        JOIN pg_roles AS r ON r.oid = n.nspowner
                        WHERE n.nspname = 'channel_dataset'
                        """
                    )
                ).scalar_one()
                public_usage = conn.execute(
                    text("SELECT has_schema_privilege('public', 'channel_dataset', 'USAGE')")
                ).scalar_one()
                reader_usage = conn.execute(
                    text(
                        "SELECT has_schema_privilege('refraq_reader', 'channel_dataset', 'USAGE')"
                    )
                ).scalar_one()
                reader_create = conn.execute(
                    text(
                        "SELECT has_schema_privilege('refraq_reader', 'channel_dataset', 'CREATE')"
                    )
                ).scalar_one()
        finally:
            engine.dispose()
    assert owner == ENTITY_OWNER_ROLE
    assert public_usage is False
    assert reader_usage is False
    assert reader_create is False


@pytest.fixture
def sql_dataset_registry(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    try:
        engine = create_engine(_INTEGRATION_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        pytest.skip("platform integration database not available")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_dssql") as urls:
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
        monkeypatch.setenv("DATABASE_URL", _INTEGRATION_DATABASE_URL)
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        from backend.core.config import reset_settings_cache
        from backend.core.db import reset_db_singletons
        from backend.core.entry import migrate_with_advisory_lock
        from backend.entity.entity_db import reset_entity_engine

        reset_settings_cache()
        reset_db_singletons()
        reset_entity_engine()
        monkeypatch.setattr(
            "backend.channel.dataset_registry.channel_dataset_max_total_gb",
            lambda: 100,
        )
        migrate_with_advisory_lock(_INTEGRATION_DATABASE_URL)
        store = SqlDatasetStore()
        try:
            yield DatasetRegistry(store), store
        finally:
            try:
                from sqlalchemy import delete

                from backend.channel.models import ChannelDatasetRow
                from backend.core.db import session_scope

                with session_scope() as session:
                    session.execute(
                        delete(ChannelDatasetRow).where(
                            ChannelDatasetRow.job_id == "job_ds_sql"
                        )
                    )
                    session.execute(
                        delete(ChannelDatasetRow).where(ChannelDatasetRow.id == "ddroppedsql")
                    )
            finally:
                reset_entity_engine()
                reset_db_singletons()
                reset_settings_cache()


@pytest.mark.integration
def test_sql_registry_persists_a_ready_dataset_and_ignores_dropped_bytes(
    sql_dataset_registry: tuple[DatasetRegistry, SqlDatasetStore],
) -> None:
    registry, store = sql_dataset_registry
    store.save(_record("ddroppedsql", status="dropped", size_bytes=50_000))
    assert store.used_bytes() == 0
    record = registry.create_from_query(
        job_id="job_ds_sql",
        node_id="node_1",
        seq=1,
        query="SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS t(n, label)",
    )
    assert record.status == "ready"
    assert record.expires_at is None
    assert record.relation == physical_relation(record.id)
    loaded = SqlDatasetStore().get(record.id)
    assert loaded is not None
    assert loaded.status == "ready"
    assert loaded.job_id == "job_ds_sql"
    assert loaded.row_count == 2
    assert loaded.size_bytes == record.size_bytes
    assert loaded.relation == record.relation
    assert store.used_bytes() == record.size_bytes
    page = registry.read_page(record.id, after_ord=0, limit=10)
    assert {(row["n"], row["label"]) for row in page} == {(1, "a"), (2, "b")}
