"""Pure structure-row assembler (no engine, no store)."""

from __future__ import annotations

import pytest

from backend.metadata.connectors.oracle import _object_key
from backend.metadata.connectors.structure_rows import (
    ColumnRow,
    DefinitionRow,
    ForeignKeyColumnRow,
    IndexColumnRow,
    KeyColumnRow,
    ObjectRow,
    StructureRows,
    assemble,
)


class _Progress:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []

    def listing_objects(self, schema: str) -> None:
        self.events.append(("listing", schema))

    def listed_objects(self, total: int) -> None:
        self.events.append(("listed", total))

    def fetched(self, part: str, rows: int) -> None:
        self.events.append(("fetched", part, rows))

    def assembled(self, total: int) -> None:
        self.events.append(("assembled", total))


def test_assemble_groups_six_row_sets_and_reports_progress() -> None:
    progress = _Progress()
    collected = assemble(
        StructureRows(
            objects=[
                ObjectRow("1", "dbo", "orders", "table", comment="Orders"),
                ObjectRow("2", "dbo", "v_open", "view"),
            ],
            columns=[
                ColumnRow("1", "id", 1, "int", False),
                ColumnRow("1", "customer_id", 2, "int", True),
                ColumnRow("2", "id", 1, "int", False),
            ],
            primary_keys=[KeyColumnRow("1", "id", 1)],
            foreign_keys=[
                ForeignKeyColumnRow(
                    "1", "fk_orders_customer", "customer_id",
                    "dbo", "customers", "id", 1,
                )
            ],
            indexes=[
                IndexColumnRow("1", "ix_orders_customer", "customer_id", 1, False)
            ],
            definitions=[DefinitionRow("2", "SELECT id FROM dbo.orders")],
        ),
        progress=progress,
    )
    assert [obj.name for obj in collected.objects] == ["orders", "v_open"]
    orders = collected.objects[0]
    assert orders.comment == "Orders"
    assert [col.name for col in orders.columns] == ["id", "customer_id"]
    assert orders.primary_key == ["id"]
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].columns == ["customer_id"]
    assert orders.foreign_keys[0].ref_columns == ["id"]
    assert orders.indexes[0].name == "ix_orders_customer"
    assert collected.objects[1].ddl == "SELECT id FROM dbo.orders"
    assert progress.events == [
        ("fetched", "columns", 3),
        ("fetched", "primary_keys", 1),
        ("fetched", "foreign_keys", 1),
        ("fetched", "indexes", 1),
        ("fetched", "definitions", 1),
        ("assembled", 2),
    ]


def test_assemble_ignores_orphan_detail_rows() -> None:
    collected = assemble(
        StructureRows(
            objects=[ObjectRow("1", "dbo", "t", "table")],
            columns=[ColumnRow("missing", "x", 1, "int", True)],
            primary_keys=[KeyColumnRow("missing", "x", 1)],
        )
    )
    assert collected.objects[0].columns == []
    assert collected.objects[0].primary_key == []


def test_assemble_rejects_duplicate_object_keys() -> None:
    with pytest.raises(ValueError, match="duplicate object_key"):
        assemble(
            StructureRows(
                objects=[
                    ObjectRow("table:HR.SALES", "HR", "SALES", "table"),
                    ObjectRow("table:HR.SALES", "HR", "SALES", "table"),
                ]
            )
        )


def test_assemble_keeps_same_name_distinct_types() -> None:
    table_key = _object_key("HR", "MV", "table")
    mview_key = _object_key("HR", "MV", "materialized_view")
    collected = assemble(
        StructureRows(
            objects=[
                ObjectRow(table_key, "HR", "MV", "table"),
                ObjectRow(mview_key, "HR", "MV", "materialized_view"),
            ],
            columns=[
                ColumnRow(table_key, "id", 1, "NUMBER", False),
                ColumnRow(mview_key, "id", 1, "NUMBER", False),
            ],
            definitions=[
                DefinitionRow(mview_key, "CREATE MATERIALIZED VIEW HR.MV AS SELECT 1"),
            ],
        )
    )
    by_type = {obj.object_type: obj for obj in collected.objects}
    assert set(by_type) == {"table", "materialized_view"}
    assert [col.name for col in by_type["table"].columns] == ["id"]
    assert [col.name for col in by_type["materialized_view"].columns] == ["id"]
    assert by_type["table"].ddl is None
    assert by_type["materialized_view"].ddl is not None


def test_oracle_object_key_includes_object_type() -> None:
    assert _object_key("HR", "SALES", "table") == "table:HR.SALES"
    assert _object_key("HR", "SALES", "materialized_view") == (
        "materialized_view:HR.SALES"
    )
    assert _object_key("HR", "SALES", "table") != _object_key(
        "HR", "SALES", "materialized_view"
    )


def test_assemble_routines_are_ddl_only() -> None:
    collected = assemble(
        StructureRows(
            objects=[
                ObjectRow("proc:1", "dbo", "refresh_orders", "procedure"),
                ObjectRow("fn:1", "dbo", "fn_open()", "function"),
            ],
            columns=[],
            definitions=[
                DefinitionRow("proc:1", "CREATE PROCEDURE refresh_orders AS SELECT 1"),
                DefinitionRow("fn:1", None),
            ],
        )
    )
    by_type = {obj.object_type: obj for obj in collected.objects}
    assert by_type["procedure"].columns == []
    assert by_type["procedure"].primary_key == []
    assert by_type["procedure"].foreign_keys == []
    assert by_type["procedure"].indexes == []
    assert by_type["procedure"].ddl is not None
    assert by_type["function"].ddl is None
    assert by_type["function"].columns == []
