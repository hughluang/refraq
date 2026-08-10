"""Locator format/parse roundtrips and segment encoding."""

from __future__ import annotations

import pytest

from backend.metadata.errors import LocatorInvalid
from backend.metadata.locators import (
    format_column_locator,
    format_object_locator,
    format_source_locator,
    parse_column_locator,
    parse_object_locator,
    parse_source_locator,
    source_locator_segment,
)


def test_source_locator_roundtrip() -> None:
    key = format_source_locator(engine="postgresql", kind="database", key="mes-prod")
    assert key == "src/postgresql/mes-prod"
    parsed = parse_source_locator(key)
    assert parsed.engine_or_kind == "postgresql"
    assert parsed.source_key == "mes-prod"


def test_source_locator_uses_kind_when_no_engine() -> None:
    key = format_source_locator(engine=None, kind="file", key="uploads")
    assert key == "src/file/uploads"
    assert source_locator_segment(engine=None, kind="file") == "file"


def test_object_and_column_roundtrip() -> None:
    obj = format_object_locator(
        engine="mssql",
        kind="database",
        source_key="erp",
        schema_name="dbo",
        object_type="table",
        name="orders",
    )
    assert obj == "obj/mssql/erp/dbo/table/orders"
    parsed_obj = parse_object_locator(obj)
    assert parsed_obj.schema_name == "dbo"
    assert parsed_obj.name == "orders"

    col = format_column_locator(
        engine="mssql",
        kind="database",
        source_key="erp",
        schema_name="dbo",
        object_type="table",
        name="orders",
        column_name="id",
    )
    assert col == "col/mssql/erp/dbo/table/orders/column/id"
    parsed_col = parse_column_locator(col)
    assert parsed_col.field_kind == "column"
    assert parsed_col.column_name == "id"


def test_slash_in_segments_is_percent_encoded() -> None:
    key = format_source_locator(
        engine="postgresql", kind="database", key="a/b"
    )
    assert key == "src/postgresql/a%2Fb"
    parsed = parse_source_locator(key)
    assert parsed.source_key == "a/b"

    obj = format_object_locator(
        engine="postgresql",
        kind="database",
        source_key="src/x",
        schema_name="sch/ema",
        object_type="table",
        name="n/ame",
    )
    assert "%2F" in obj
    parsed_obj = parse_object_locator(obj)
    assert parsed_obj.source_key == "src/x"
    assert parsed_obj.schema_name == "sch/ema"
    assert parsed_obj.name == "n/ame"

    col = format_column_locator(
        engine="oracle",
        kind="database",
        source_key="k",
        schema_name="S",
        object_type="view",
        name="V",
        column_name="c/ol",
        field_kind="column",
    )
    parsed_col = parse_column_locator(col)
    assert parsed_col.column_name == "c/ol"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "src/only-one",
        "obj/a/b",
        "col/a/b/c/d/e/f",
        "xyz/postgresql/k",
    ],
)
def test_parse_rejects_invalid(bad: str) -> None:
    with pytest.raises(LocatorInvalid):
        if bad.startswith("obj") or bad.count("/") == 5:
            parse_object_locator(bad)
        elif bad.startswith("col"):
            parse_column_locator(bad)
        else:
            parse_source_locator(bad)
