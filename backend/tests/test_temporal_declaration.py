"""Temporal declarations that travel from a Source stream to a dataset reference."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.metadata.connectors.base import SourceEndpoint
from backend.metadata.connectors.runtime import PreparedEngine
from backend.metadata.type_mappings.seeds import ensure_product_type_mappings


def _plant(monkeypatch, engine: str) -> None:
    record = SimpleNamespace(
        status="active",
        engine=engine,
        access_ciphertext="sealed",
    )

    class _Store:
        def get_source(self, source_id: str) -> SimpleNamespace:
            del source_id
            return record

    monkeypatch.setattr(
        "backend.metadata.source_statements.get_source_store", lambda: _Store()
    )
    monkeypatch.setattr(
        "backend.metadata.source_statements.decrypt_access_blob", lambda _blob: {}
    )


def _stream(monkeypatch, engine: str, native_type: str, *, nullable: bool | None = None):
    from backend.metadata.source_statements import stream_source_statement

    _plant(monkeypatch, engine)
    ensure_product_type_mappings()

    class _Column:
        def __init__(self) -> None:
            self.name = "ts"
            self.native_type = native_type
            if nullable is not None:
                self.nullable = nullable

    class _Stream:
        columns = [_Column()]

        def close(self) -> None:
            return None

        @property
        def chunks(self):
            return iter(())

    class _Connector:
        def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
            del endpoint, sql, chunk_rows, deadline
            return _Stream()

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del engine, access
        endpoint = SourceEndpoint(
            engine="postgresql",
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
        )
        return PreparedEngine(connector=_Connector(), endpoint=endpoint)

    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)
    streamed = stream_source_statement(
        "src_live", "SELECT ts FROM t", chunk_rows=10, deadline=1
    )
    try:
        return streamed.columns[0]
    finally:
        streamed.close()


def test_timestamp_with_precision_keeps_kind_and_normalized_type(monkeypatch) -> None:
    column = _stream(monkeypatch, "postgresql", "timestamp(3) with time zone")
    assert column.temporal_kind == "timestamp_with_time_zone"
    assert column.precision == 3
    assert column.normalized_type == "timestamp"
    assert column.nullable is None


def test_engine_and_native_type_choose_the_temporal_kind(monkeypatch) -> None:
    cases = (
        ("postgresql", "date", "date", "date", None),
        ("postgresql", "time", "time", "time", None),
        ("postgresql", "time(4) without time zone", "time", "time", 4),
        ("postgresql", "timetz", "time_with_offset", "time", None),
        ("postgresql", "time with time zone", "time_with_offset", "time", None),
        ("postgresql", "timestamp", "local_datetime", "timestamp", None),
        ("postgresql", "timestamptz", "timestamp_with_time_zone", "timestamp", None),
        ("postgresql", "interval", "interval", "interval", None),
        ("oracle", "TIMESTAMP", "local_datetime", "timestamp", None),
        ("oracle", "TIMESTAMP WITH TIME ZONE", "timestamp_with_time_zone", "timestamp", None),
        ("oracle", "INTERVAL YEAR TO MONTH", "interval_calendar", "interval", None),
        ("oracle", "INTERVAL DAY TO SECOND(6)", "interval_fixed", "interval", 6),
        ("oracle", "DSINTERVAL_UNLISTED", None, "unknown", None),
        ("mssql", "date", "date", "date", None),
        ("mssql", "datetime", "local_datetime", "timestamp", None),
        ("mssql", "datetime2(7)", "local_datetime", "timestamp", 7),
        ("mssql", "smalldatetime", "local_datetime", "timestamp", None),
        ("mssql", "datetimeoffset", "timestamp_with_time_zone", "timestamp", None),
        ("mssql", "time", "time", "time", None),
        ("mssql", "timestamp", None, "binary", None),
    )
    for engine, native, kind, normalized, precision in cases:
        column = _stream(monkeypatch, engine, native)
        assert (column.temporal_kind, column.normalized_type, column.precision) == (
            kind,
            normalized,
            precision,
        ), native


def test_extra_fractional_digits_fail_before_write(monkeypatch) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry, MemoryDatasetStore
    from backend.channel.errors import TemporalTargetIncompatible

    wrote: list[object] = []
    _fake_copy(monkeypatch, wrote)
    value = datetime(2020, 1, 2, 3, 4, 5, 123400, tzinfo=timezone.utc)
    with pytest.raises(TemporalTargetIncompatible) as raised:
        DatasetRegistry(MemoryDatasetStore()).create_from_chunks(
            job_id="job_1",
            node_id="node_1",
            seq=1,
            columns=[
                DatasetColumnSpec(
                    "ts",
                    "timestamp",
                    precision=3,
                    with_time_zone=True,
                    temporal_kind="timestamp_with_time_zone",
                )
            ],
            chunks=[[(value,)]],
        )
    assert wrote == []
    assert raised.value.extra_members() == {
        "declaration": {
            "temporal_kind": "timestamp_with_time_zone",
            "precision": 3,
        },
        "value": "2020-01-02T03:04:05.123400+00:00",
        "target_limit": 3,
    }


def test_trailing_zeros_fit_the_declared_precision(monkeypatch) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry, MemoryDatasetStore

    wrote: list[object] = []
    _fake_copy(monkeypatch, wrote)
    value = datetime(2020, 1, 2, 3, 4, 5, 123000, tzinfo=timezone.utc)
    record = DatasetRegistry(MemoryDatasetStore()).create_from_chunks(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        columns=[
            DatasetColumnSpec(
                "ts",
                "timestamp",
                precision=3,
                with_time_zone=True,
                temporal_kind="timestamp_with_time_zone",
            )
        ],
        chunks=[[(value,)]],
    )
    assert record.status == "ready"
    assert wrote == [[(value,)]]


def _fake_copy(monkeypatch, wrote: list[object]) -> None:
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()

    def copy_chunks(relation, columns, chunks, on_chunk_size=None):
        del relation, columns, on_chunk_size
        for chunk in chunks:
            wrote.append(list(chunk))
        return 1, 4

    def column_types(relation):
        del relation
        return [{"name": "ts", "type": "timestamp(3) with time zone"}]

    monkeypatch.setattr("backend.channel.dataset_registry.copy_chunks", copy_chunks)
    monkeypatch.setattr("backend.channel.dataset_registry.column_types", column_types)
    monkeypatch.setattr("backend.channel.dataset_registry.drop_relation", lambda _relation: None)


def test_oracle_date_is_a_local_datetime(monkeypatch) -> None:
    column = _stream(monkeypatch, "oracle", "DATE")
    assert column.temporal_kind == "local_datetime"
    assert column.normalized_type == "timestamp"


def test_local_time_zone_keeps_its_own_kind(monkeypatch) -> None:
    column = _stream(monkeypatch, "oracle", "TIMESTAMP WITH LOCAL TIME ZONE")
    assert column.temporal_kind == "timestamp_with_local_time_zone"
    assert column.with_time_zone is False
    assert column.normalized_type == "timestamp"


def _forbid_sql(monkeypatch) -> None:
    def sql(*_args, **_kwargs):
        raise AssertionError("sql")

    monkeypatch.setattr("backend.channel.dataset_registry.copy_chunks", sql)
    monkeypatch.setattr("backend.channel.dataset_registry.create_table_from_query", sql)
    monkeypatch.setattr("backend.entity.datasets.get_entity_engine", sql)


def _spec(column):
    from backend.channel.dataset_registry import DatasetColumnSpec

    return DatasetColumnSpec(
        column.name,
        column.normalized_type,
        precision=column.precision,
        scale=column.scale,
        with_time_zone=column.with_time_zone,
        temporal_kind=column.temporal_kind,
        nullable=column.nullable,
    )


def test_local_time_zone_fails_before_sql(monkeypatch) -> None:
    from backend.channel.dataset_registry import DatasetRegistry, MemoryDatasetStore
    from backend.channel.errors import TemporalTargetIncompatible

    _forbid_sql(monkeypatch)
    column = _stream(monkeypatch, "oracle", "TIMESTAMP WITH LOCAL TIME ZONE")
    with pytest.raises(TemporalTargetIncompatible) as raised:
        DatasetRegistry(MemoryDatasetStore()).create_from_chunks(
            job_id="job_1",
            node_id="node_1",
            seq=1,
            columns=[_spec(column)],
            chunks=[[("2020-01-02 03:04:05",)]],
        )
    assert raised.value.code == "TEMPORAL_TARGET_INCOMPATIBLE"
    assert raised.value.http_status == 422
    assert raised.value.extra_members() == {
        "declaration": {
            "temporal_kind": "timestamp_with_local_time_zone",
            "precision": None,
        },
        "value": None,
        "target_limit": (
            "PostgreSQL has no type that preserves TIMESTAMP WITH LOCAL TIME ZONE"
        ),
    }


def test_precision_above_six_fails_before_sql(monkeypatch) -> None:
    from backend.channel.dataset_registry import DatasetRegistry, MemoryDatasetStore
    from backend.channel.errors import TemporalTargetIncompatible

    _forbid_sql(monkeypatch)
    column = _stream(monkeypatch, "postgresql", "timestamp(9) with time zone")
    assert column.precision == 9
    assert column.temporal_kind == "timestamp_with_time_zone"
    with pytest.raises(TemporalTargetIncompatible) as raised:
        DatasetRegistry(MemoryDatasetStore()).create_from_chunks(
            job_id="job_1",
            node_id="node_1",
            seq=1,
            columns=[_spec(column)],
            chunks=[],
        )
    assert raised.value.extra_members() == {
        "declaration": {
            "temporal_kind": "timestamp_with_time_zone",
            "precision": 9,
        },
        "value": None,
        "target_limit": 6,
    }


def test_timestamp_precision_reaches_the_dataset_reference(monkeypatch) -> None:
    physical, columns, reference = _load_source(monkeypatch, "timestamp(3) with time zone")
    assert physical == [("ts", "timestamp(3) with time zone")]
    assert columns == [
        {
            "name": "ts",
            "type": "timestamp",
            "temporal_kind": "timestamp_with_time_zone",
            "precision": 3,
            "nullable": None,
        }
    ]
    from jsonschema import Draft202012Validator

    from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA

    Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate(reference)


def test_oracle_date_materializes_as_a_timestamp_without_time_zone(monkeypatch) -> None:
    physical, columns, _reference = _load_source(monkeypatch, "DATE", engine="oracle")
    assert physical == [("ts", "timestamp without time zone")]
    assert columns == [
        {
            "name": "ts",
            "type": "timestamp",
            "temporal_kind": "local_datetime",
            "precision": None,
            "nullable": None,
        }
    ]


def test_driver_nullable_is_not_replaced_with_true(monkeypatch) -> None:
    _physical, omitted, _reference = _load_source(monkeypatch, "timestamp with time zone")
    assert omitted[0]["nullable"] is None
    _physical, present, _reference = _load_source(
        monkeypatch, "timestamp with time zone", nullable=False
    )
    assert present[0]["nullable"] is False


def test_plain_timestamp_with_time_zone_stays_without_typmod(monkeypatch) -> None:
    physical, columns, _reference = _load_source(monkeypatch, "timestamp with time zone")
    assert physical == [("ts", "timestamp with time zone")]
    assert columns == [
        {
            "name": "ts",
            "type": "timestamp",
            "temporal_kind": "timestamp_with_time_zone",
            "precision": None,
            "nullable": None,
        }
    ]


def test_ctas_timestamp_reference_keeps_precision_without_a_source_engine(
    monkeypatch,
) -> None:
    from backend.channel.dataset_ref import dataset_reference
    from backend.channel.dataset_registry import DatasetRegistry, MemoryDatasetStore
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()

    def create_table_from_query(relation, query):
        del relation, query
        return 2, 16

    def column_types(relation):
        del relation
        return [{"name": "ts", "type": "timestamp(3) without time zone"}]

    monkeypatch.setattr(
        "backend.channel.dataset_registry.create_table_from_query",
        create_table_from_query,
    )
    monkeypatch.setattr("backend.channel.dataset_registry.column_types", column_types)
    record = DatasetRegistry(MemoryDatasetStore()).create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT ts FROM t",
    )
    assert record.columns[0]["type"] == "timestamp(3) without time zone"
    reference = dataset_reference(
        dataset_id=record.id, columns=record.columns, count=record.row_count
    )
    assert reference["columns"] == [
        {
            "name": "ts",
            "type": "timestamp",
            "temporal_kind": "local_datetime",
            "precision": 3,
            "nullable": None,
        }
    ]


def test_unknown_precision_does_not_reject_a_fraction(monkeypatch) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry, MemoryDatasetStore

    wrote: list[object] = []
    _fake_copy(monkeypatch, wrote)
    value = datetime(2020, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)
    record = DatasetRegistry(MemoryDatasetStore()).create_from_chunks(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        columns=[
            DatasetColumnSpec(
                "ts",
                "timestamp",
                with_time_zone=True,
                temporal_kind="timestamp_with_time_zone",
            )
        ],
        chunks=[[(value,)]],
    )
    assert record.status == "ready"
    assert wrote == [[(value,)]]


def test_materialized_postgres_type_is_not_local_time_zone(monkeypatch) -> None:
    from backend.channel.dataset_ref import dataset_reference
    from backend.channel.dataset_registry import DatasetRegistry, MemoryDatasetStore
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()

    def create_table_from_query(relation, query):
        del relation, query
        return 1, 4

    def column_types(relation):
        del relation
        return [{"name": "ts", "type": "timestamp with local time zone"}]

    monkeypatch.setattr(
        "backend.channel.dataset_registry.create_table_from_query",
        create_table_from_query,
    )
    monkeypatch.setattr("backend.channel.dataset_registry.column_types", column_types)
    record = DatasetRegistry(MemoryDatasetStore()).create_from_query(
        job_id="job_1",
        node_id="node_1",
        seq=1,
        query="SELECT ts FROM t",
    )
    reference = dataset_reference(
        dataset_id=record.id, columns=record.columns, count=record.row_count
    )
    assert reference["columns"][0]["temporal_kind"] is None
    assert reference["columns"][0]["type"] != "timestamp_with_local_time_zone"


def test_node_reports_local_time_zone_before_sql(monkeypatch) -> None:
    from backend.channel.nodes.volume.dataset_query import NODE_TYPE
    from backend.tests.channel_hooks_fake import FakeHooks

    _plant(monkeypatch, "oracle")
    ensure_product_type_mappings()
    _forbid_sql(monkeypatch)

    class _Column:
        name = "ts"
        native_type = "TIMESTAMP WITH LOCAL TIME ZONE"

    class _Stream:
        columns = [_Column()]

        def close(self) -> None:
            return None

        @property
        def chunks(self):
            return iter(())

    class _Connector:
        def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
            del endpoint, sql, chunk_rows, deadline
            return _Stream()

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del engine, access
        return PreparedEngine(connector=_Connector(), endpoint=_endpoint())

    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)
    result = NODE_TYPE.execute(
        {
            "id": "nd_query",
            "type": "volume.dataset_query",
            "config": {
                "source": {"kind": "source", "source_id": "src_live"},
                "sql": "SELECT ts FROM t",
            },
        },
        FakeHooks(run_id="job_ltz"),
    )
    assert result.status == "failed"
    assert result.error_code == "TEMPORAL_TARGET_INCOMPATIBLE"
    assert result.error_detail == {
        "declaration": {
            "temporal_kind": "timestamp_with_local_time_zone",
            "precision": None,
        },
        "value": None,
        "target_limit": (
            "PostgreSQL has no type that preserves TIMESTAMP WITH LOCAL TIME ZONE"
        ),
    }


_UNSET = object()


def _load_source(
    monkeypatch,
    native_type: str,
    *,
    engine: str = "postgresql",
    nullable: object = _UNSET,
):
    from backend.channel.nodes.volume.dataset_query import NODE_TYPE
    from backend.tests.channel_hooks_fake import FakeHooks
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()
    _plant(monkeypatch, engine)
    seen: dict[str, object] = {}

    class _Column:
        def __init__(self) -> None:
            self.name = "ts"
            self.native_type = native_type
            if nullable is not _UNSET:
                self.nullable = nullable

    class _Stream:
        columns = [_Column()]

        def close(self) -> None:
            return None

        @property
        def chunks(self):
            return iter(())

    class _Connector:
        def stream_statement(self, endpoint, sql, *, chunk_rows, deadline):
            del endpoint, sql, chunk_rows, deadline
            return _Stream()

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del engine, access
        return PreparedEngine(connector=_Connector(), endpoint=_endpoint())

    def copy_chunks(relation, columns, chunks, on_chunk_size=None):
        del relation, chunks, on_chunk_size
        seen["columns"] = columns
        return 1, 4

    def column_types(relation):
        del relation
        physical = seen["columns"][0][1]
        return [{"name": "ts", "type": physical}]

    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)
    monkeypatch.setattr("backend.channel.dataset_registry.copy_chunks", copy_chunks)
    monkeypatch.setattr("backend.channel.dataset_registry.column_types", column_types)
    ensure_product_type_mappings()
    result = NODE_TYPE.execute(
        {
            "id": "nd_query",
            "type": "volume.dataset_query",
            "config": {
                "source": {"kind": "source", "source_id": "src_live"},
                "sql": "SELECT ts FROM t",
            },
        },
        FakeHooks(run_id="job_temporal"),
    )
    assert result.status == "succeeded", result.error_message
    return seen["columns"], result.output["dataset"]["columns"], result.output["dataset"]


def _endpoint() -> SourceEndpoint:
    return SourceEndpoint(
        engine="postgresql",
        host="db.example",
        port=5432,
        username="reader",
        password="secret",
        database_name="app",
        schema_filter="public",
    )
