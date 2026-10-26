"""Dataset temporal declarations on channel ports, reads, and filters."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.channel.dataset_registry import DatasetRecord, MemoryDatasetStore
from backend.channel.nodes.volume import batch_read
from backend.channel.nodes.volume.batch_read import NODE_TYPE
from backend.channel.routers import runs
from backend.channel.template import render
from backend.tests.channel_hooks_fake import FakeHooks, _user

_OFFSET = timezone(timedelta(hours=8))
_FRACTIONAL = datetime(2024, 6, 1, 1, 2, 3, 450000, tzinfo=_OFFSET)
_DECLARED_TEXT = "2024-06-01T01:02:03.45+08:00"
_SECOND_Z = "2024-05-31T17:02:03Z"


def test_batch_read_port_carries_temporal_kind_and_precision() -> None:
    columns = {
        "type": "object",
        "x-refraq-dataset-reference": True,
        "properties": {
            "columns": {
                "const": [
                    {
                        "name": "seen",
                        "type": "timestamp",
                        "temporal_kind": "timestamp_with_time_zone",
                        "precision": 3,
                        "nullable": True,
                    },
                    {"name": "label", "type": "string"},
                    {
                        "name": "zoned",
                        "type": "timestamp",
                        "with_time_zone": True,
                    },
                ]
            }
        },
    }
    refined = NODE_TYPE.refine(
        {"dataset": "{{ self.query.output.dataset }}"},
        {"query": {"main": {"type": "object", "properties": {"dataset": columns}}}},
        None,
    )
    properties = refined["each"]["properties"]["rows"]["items"]["properties"]
    seen = properties["seen"]
    assert seen["type"] == ["string", "null"]
    assert "required" not in seen
    assert seen["temporal_kind"] == "timestamp_with_time_zone"
    assert seen["precision"] == 3
    assert seen["nullable"] is True
    assert properties["label"] == {"type": ["string", "null"]}
    zoned = properties["zoned"]
    assert zoned["type"] == ["string", "null"]
    assert "temporal_kind" not in zoned
    assert "precision" not in zoned
    assert "with_time_zone" not in zoned


def test_batch_read_keeps_fractional_offset_on_a_declared_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    _plant(
        monkeypatch,
        columns=[
            {
                "name": "seen",
                "type": "timestamp with time zone",
                "normalized_type": "timestamp",
                "with_time_zone": True,
            },
            {
                "name": "legacy",
                "type": "timestamp with time zone",
                "normalized_type": "timestamp",
                "with_time_zone": True,
            },
            {"name": "note", "type": "text", "normalized_type": "string"},
        ],
        page=[
            {
                "_ord": 1,
                "seen": _FRACTIONAL,
                "note": "2024-06-01",
                "legacy": legacy,
            }
        ],
    )
    result = NODE_TYPE.execute(
        {
            "id": "batch",
            "type": "volume.batch_read",
            "config": {
                "dataset": json.dumps(
                    {
                        "dataset_id": "dset",
                        "columns": [
                            {
                                "name": "seen",
                                "type": "timestamp",
                                "temporal_kind": "timestamp_with_time_zone",
                                "precision": 3,
                                "nullable": True,
                            },
                            {"name": "note", "type": "string"},
                            {"name": "legacy", "type": "timestamp"},
                        ],
                        "count": 1,
                    }
                )
            },
        },
        FakeHooks(),
    )
    assert result.status == "succeeded"
    row = next(result.iterations)["rows"][0]
    assert row["seen"] == _DECLARED_TEXT
    assert row["seen"] != _SECOND_Z
    assert isinstance(row["seen"], str)
    assert row["note"] == "2024-06-01"
    assert row["legacy"] == "2026-10-22T12:00:00Z"


def test_filter_compares_a_shared_temporal_kind_at_its_precision() -> None:
    from backend.channel.nodes.transform.filter import NODE_TYPE as filter_node

    seen = {
        "type": ["string", "null"],
        "temporal_kind": "timestamp_with_time_zone",
        "precision": 3,
    }
    upstream = {
        "src": {
            "main": {
                "type": "object",
                "properties": {
                    "rows": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"seen": seen}},
                    }
                },
            }
        },
        "bound": {"main": {"type": "object", "properties": {"at": dict(seen)}}},
    }
    config = {
        "items": "{{ self.src.output.rows }}",
        "conditions": [
            {
                "key": "seen",
                "operator": "eq",
                "value": "{{ self.bound.output.at }}",
            }
        ],
    }
    filter_node.refine(config, upstream, None)
    rows = [
        {"seen": "2024-06-01T01:02:03.123400+08:00"},
        {"seen": "2024-06-01T01:02:03.123900+08:00"},
        {"seen": "2024-06-01T01:02:03.124000+08:00"},
        {"seen": "2024-05-31T17:02:03.123000Z"},
    ]
    result = filter_node.execute(
        {"id": "filter", "type": "transform.filter", "config": config},
        _hooks(
            {
                "self.src.output.rows": rows,
                "self.bound.output.at": "2024-06-01T01:02:03.123000+08:00",
            }
        ),
    )
    assert result.status == "succeeded"
    assert result.output["rows"] == [rows[0], rows[1], rows[3]]
    config["conditions"][0]["operator"] = "gt"
    greater = filter_node.execute(
        {"id": "filter", "type": "transform.filter", "config": config},
        _hooks(
            {
                "self.src.output.rows": rows,
                "self.bound.output.at": "2024-06-01T01:02:03.123000+08:00",
            }
        ),
    )
    assert greater.output["rows"] == [rows[2]]


def test_filter_keeps_string_comparison_without_a_shared_temporal_kind() -> None:
    from backend.channel.nodes.transform.filter import NODE_TYPE as filter_node

    declared = {
        "type": ["string", "null"],
        "temporal_kind": "timestamp_with_time_zone",
        "precision": 3,
    }
    local = {
        "type": ["string", "null"],
        "temporal_kind": "local_datetime",
        "precision": 3,
    }
    plain = {"type": ["string", "null"]}
    rows = [
        {"seen": "2024-06-01T01:02:03.123000+08:00"},
        {"seen": "2024-06-01T01:02:03.123400+08:00"},
    ]
    exact = {
        "items": "{{ self.src.output.rows }}",
        "conditions": [
            {
                "key": "seen",
                "operator": "eq",
                "value": "{{ self.bound.output.at }}",
            }
        ],
    }
    filter_node.refine(
        exact,
        {
            "src": _rows_schema(plain),
            "bound": {"main": {"type": "object", "properties": {"at": plain}}},
        },
        None,
    )
    undecorated = filter_node.execute(
        {"id": "filter", "type": "transform.filter", "config": exact},
        _hooks(
            {
                "self.src.output.rows": rows,
                "self.bound.output.at": "2024-06-01T01:02:03.123000+08:00",
            }
        ),
    )
    assert undecorated.output["rows"] == [rows[0]]

    literal = {
        "items": "{{ self.src.output.rows }}",
        "conditions": [
            {
                "key": "seen",
                "operator": "eq",
                "value": '"2024-06-01T01:02:03.123000+08:00"',
            }
        ],
    }
    filter_node.refine(literal, {"src": _rows_schema(declared)}, None)
    typed_literal = filter_node.execute(
        {"id": "filter", "type": "transform.filter", "config": literal},
        _hooks({"self.src.output.rows": rows}),
    )
    assert typed_literal.output["rows"] == [rows[0]]

    mismatched = {
        "items": "{{ self.src.output.rows }}",
        "conditions": [
            {
                "key": "seen",
                "operator": "eq",
                "value": "{{ self.bound.output.at }}",
            }
        ],
    }
    filter_node.refine(
        mismatched,
        {
            "src": _rows_schema(declared),
            "bound": {"main": {"type": "object", "properties": {"at": local}}},
        },
        None,
    )
    different_kind = filter_node.execute(
        {"id": "filter", "type": "transform.filter", "config": mismatched},
        _hooks(
            {
                "self.src.output.rows": rows,
                "self.bound.output.at": "2024-06-01T01:02:03.123000+08:00",
            }
        ),
    )
    assert different_kind.output["rows"] == [rows[0]]


def _rows_schema(seen: dict) -> dict:
    return {
        "main": {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"seen": seen}},
                }
            },
        }
    }


def test_date_like_template_text_stays_literal() -> None:
    assert render("due on 2024-06-01", lambda _body: None, {"type": "string"}) == (
        "due on 2024-06-01"
    )


def test_sql_read_without_a_column_declaration_keeps_the_driver_json_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.channel.sql_read import run_channel_sql
    from backend.metadata.connectors.base import StatementResult

    def execute(source_id: str, sql: str, *, timeout_sec: int, max_rows: int) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        return StatementResult(
            columns=["when", "note"],
            rows=[
                [
                    datetime(2020, 1, 2, 3, 4, 5, 450000, tzinfo=timezone.utc),
                    "2024-06-01",
                ]
            ],
            rowcount=1,
            truncated=False,
        )

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    assert run_channel_sql(
        "SELECT when, note FROM t",
        source={"kind": "source", "source_id": "src_live"},
        statement_timeout_sec=30,
    )["rows"] == [
        {"when": "2020-01-02T03:04:05.450000Z", "note": "2024-06-01"}
    ]


def test_dataset_rows_encode_a_declared_timestamp_like_batch_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    record = _dataset_record(
        columns=[
            {
                "name": "seen",
                "type": "timestamp with time zone",
                "normalized_type": "timestamp",
                "temporal_kind": "timestamp_with_time_zone",
                "precision": 3,
                "nullable": True,
            },
            {
                "name": "legacy",
                "type": "timestamp with time zone",
                "normalized_type": "timestamp",
                "with_time_zone": True,
            },
            {"name": "note", "type": "text", "normalized_type": "string"},
        ]
    )
    _plant_rows(
        monkeypatch,
        record,
        [
            {
                "_ord": 1,
                "seen": _FRACTIONAL,
                "note": "2024-06-01",
                "legacy": legacy,
            }
        ],
    )
    body = runs.http_dataset_rows(
        "chn",
        "job",
        "dset",
        _user(),
        after_ord=0,
        limit=50,
    )
    item = body["items"][0]
    assert item["seen"] == _DECLARED_TEXT
    assert item["seen"] != _SECOND_Z
    assert item["note"] == "2024-06-01"
    assert item["legacy"] is legacy
    assert item["_ord"] == 1


def _hooks(values: dict):
    def evaluate(expression: str):
        if expression not in values:
            raise RuntimeError(expression)
        return values[expression]

    return FakeHooks(evaluate=evaluate)


def _plant(monkeypatch: pytest.MonkeyPatch, *, columns: list[dict], page: list[dict]) -> None:
    store = MemoryDatasetStore()
    store.save(
        DatasetRecord(
            id="dset",
            job_id="run",
            node_id="load",
            seq=1,
            relation='"channel_dataset"."ds_dset"',
            columns=columns,
            row_count=1,
            size_bytes=1,
            status="ready",
            created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr(batch_read, "get_dataset_store", lambda: store)
    monkeypatch.setattr(
        batch_read,
        "read_keyset_page",
        lambda relation, *, after_ord, limit: page,
    )
    monkeypatch.setattr(batch_read, "any_row_exists", lambda relation: True)


def _dataset_record(*, columns: list[dict]) -> DatasetRecord:
    return DatasetRecord(
        id="dset",
        job_id="job",
        node_id="load",
        seq=1,
        relation='"channel_dataset"."ds_dset"',
        columns=columns,
        row_count=1,
        size_bytes=1,
        status="ready",
        created_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
    )


def _plant_rows(
    monkeypatch: pytest.MonkeyPatch, record: DatasetRecord, page: list[dict]
) -> None:
    class _Datasets:
        def get(self, dataset_id: str) -> DatasetRecord | None:
            return record if dataset_id == record.id else None

    class _Runs:
        def get_run(self, job_id: str):
            if job_id != record.job_id:
                return None
            return type("Run", (), {"channel_id": "chn", "job_id": job_id})()

    monkeypatch.setattr(runs, "get_dataset_store", lambda: _Datasets())
    monkeypatch.setattr(runs, "get_run_store", lambda: _Runs())
    monkeypatch.setattr(
        runs,
        "read_keyset_page",
        lambda relation, *, after_ord, limit: page,
    )
    monkeypatch.setattr(runs, "any_row_exists", lambda relation: True)
