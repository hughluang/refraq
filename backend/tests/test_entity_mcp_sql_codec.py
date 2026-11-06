"""Entity SQL result encoding and database-error identifier rewrite."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from backend.entity.mcp.sql_encode import encode_sql_value
from backend.entity.mcp.sql_errors import rewrite_sql_message

_UTC = timezone.utc
_PLUS_2 = timezone(timedelta(hours=2))


def test_encode_sql_value_uses_postgresql_type_names() -> None:
    moment = datetime(2024, 3, 4, 5, 6, 7, tzinfo=_PLUS_2)
    precise = datetime(2024, 3, 4, 5, 6, 7, 890000, tzinfo=_UTC)
    naive = datetime(2024, 3, 4, 5, 6, 7, 890000)
    naive_whole = datetime(2024, 3, 4, 5, 6, 7)

    assert encode_sql_value(None, "int8") is None
    assert encode_sql_value(20, "int8") == 20
    assert encode_sql_value(0, "int4") == 0
    assert encode_sql_value(True, "bool") is True
    assert encode_sql_value(False, "bool") is False
    assert encode_sql_value(Decimal("10.50"), "numeric") == "10.50"
    assert encode_sql_value(Decimal("1E+2"), "numeric") == "100"
    assert encode_sql_value(Decimal("-0.10"), "numeric") == "-0.10"
    assert encode_sql_value(1.5, "float8") == 1.5
    assert encode_sql_value(float("nan"), "float8") is None
    assert encode_sql_value(float("inf"), "float4") is None
    assert encode_sql_value(float("-inf"), "float8") is None
    assert encode_sql_value(moment, "timestamptz") == "2024-03-04T03:06:07Z"
    assert encode_sql_value(precise, "timestamptz") == "2024-03-04T05:06:07.890000Z"
    assert (
        encode_sql_value(
            datetime(2024, 3, 4, 5, 6, 7, tzinfo=_UTC),
            "timestamptz",
        )
        == "2024-03-04T05:06:07Z"
    )
    assert encode_sql_value(naive, "timestamp") == "2024-03-04T05:06:07.890000"
    assert encode_sql_value(naive_whole, "timestamp") == "2024-03-04T05:06:07"
    assert encode_sql_value(date(2024, 3, 4), "date") == "2024-03-04"
    assert encode_sql_value(time(5, 6, 7), "time") == "05:06:07"
    assert encode_sql_value(time(5, 6, 7, 890000), "timetz") == "05:06:07.890000"
    assert encode_sql_value({"a": [1, True, None]}, "jsonb") == {"a": [1, True, None]}
    assert encode_sql_value(["x", {"n": 1}], "json") == ["x", {"n": 1}]
    assert encode_sql_value([1, None, 3], "_int4") == [1, None, 3]
    assert encode_sql_value(
        [Decimal("1.50"), Decimal("2")],
        "_numeric",
    ) == ["1.50", "2"]
    assert encode_sql_value([1.5, float("nan")], "_float8") == [1.5, None]
    assert encode_sql_value([[1, None], [2]], "_int4") == [[1, None], [2]]
    assert encode_sql_value([precise], "_timestamptz") == ["2024-03-04T05:06:07.890000Z"]
    assert encode_sql_value("east", "varchar") == "east"
    assert encode_sql_value(b"ab", "bytea") == "ab"
    assert encode_sql_value(UUID("12345678-1234-5678-1234-567812345678"), "uuid") == (
        "12345678-1234-5678-1234-567812345678"
    )


def test_rewrite_sql_message_replaces_profile_view_identifiers() -> None:
    views = {
        "orders__p_ab12cd34": "orders",
        "lines__p_99887766": "lines",
    }
    samples = [
        (
            'relation "entity_access"."orders__p_ab12cd34" does not exist',
            "relation orders does not exist",
        ),
        (
            'relation "orders__p_ab12cd34" does not exist',
            "relation orders does not exist",
        ),
        (
            "relation entity_access.orders__p_ab12cd34 does not exist",
            "relation orders does not exist",
        ),
        (
            'column entity_access."lines__p_99887766".amount does not exist',
            "column lines.amount does not exist",
        ),
        (
            '"entity_access".orders__p_ab12cd34 and lines__p_99887766',
            "orders and lines",
        ),
        (
            "orders__p_ab12cd349 stays",
            "orders__p_ab12cd349 stays",
        ),
    ]
    for message, expected in samples:
        rewritten = rewrite_sql_message(message, views)
        assert rewritten == expected
        assert "orders__p_ab12cd34" not in rewritten or rewritten.endswith("stays")
        assert "lines__p_99887766" not in rewritten


def test_rewrite_sql_message_replaces_physical_names() -> None:
    message = (
        'relation "entity_data"."ord_v1_deadbeef" does not exist; '
        "see entity_data.ord_v1_deadbeef and lines__p_99887766"
    )
    rewritten = rewrite_sql_message(
        message,
        {"lines__p_99887766": "lines"},
        physical={"ord_v1_deadbeef": "orders"},
    )
    assert rewritten == (
        "relation orders does not exist; see orders and lines"
    )
    assert "ord_v1_deadbeef" not in rewritten
    assert "entity_data" not in rewritten
    assert "lines__p_99887766" not in rewritten
    assert "orders" in rewritten
    assert "lines" in rewritten


def test_rewrite_sql_message_leaves_unrelated_text() -> None:
    message = "division by zero"
    assert rewrite_sql_message(message, {"orders__p_ab12cd34": "orders"}) == message


def test_rewrite_sql_message_respects_identifier_boundaries() -> None:
    views = {"orders__p_ab12cd34": "orders", "lines__p_99887766": "lines"}
    physical = {"orders__v1__deadbeef": "orders"}
    assert rewrite_sql_message("_orders__p_ab12cd34", views) == "_orders"
    assert (
        rewrite_sql_message('type "_orders__p_ab12cd34" does not exist', views)
        == "type _orders does not exist"
    )
    assert rewrite_sql_message("entity_access._orders__p_ab12cd34", views) == "_orders"
    assert (
        rewrite_sql_message(
            'relation "entity_access.orders__p_ab12cd34" does not exist',
            views,
        )
        == 'relation "orders" does not exist'
    )
    assert rewrite_sql_message("orders__p_ab12cd349", views) == "orders__p_ab12cd349"
    assert rewrite_sql_message("x_orders__p_ab12cd34", views) == "x_orders__p_ab12cd34"
    assert rewrite_sql_message("__orders__p_ab12cd34", views) == "__orders__p_ab12cd34"
    assert (
        rewrite_sql_message("_orders__v1__deadbeef", views, physical=physical)
        == "_orders"
    )
    longer_first = {
        "orders__p_ab12cd34": "orders",
        "orders__p_ab12cd349": "lines",
    }
    assert rewrite_sql_message("orders__p_ab12cd349", longer_first) == "lines"
    assert rewrite_sql_message("orders__p_ab12cd34", longer_first) == "orders"
    assert rewrite_sql_message("orders__p_ab12cd3499", longer_first) == (
        "orders__p_ab12cd3499"
    )


@pytest.mark.parametrize(
    ("type_name", "value", "expected"),
    [
        ("int2", 4, 4),
        ("float4", 2.0, 2.0),
        ("text", "note", "note"),
    ],
)
def test_encode_sql_value_scalar_forms(
    type_name: str, value: object, expected: object
) -> None:
    assert encode_sql_value(value, type_name) == expected
