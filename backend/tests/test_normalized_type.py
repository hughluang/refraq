"""Normalized Type mapping from native data_type strings."""

from __future__ import annotations

from backend.metadata.catalog.normalized_type import normalize_type


def test_varchar_length_change_is_still_string() -> None:
    assert normalize_type("varchar(50)") == "string"
    assert normalize_type("varchar(100)") == "string"
    assert normalize_type("character varying(50)") == "string"


def test_integer_and_bigint_are_integer() -> None:
    assert normalize_type("integer") == "integer"
    assert normalize_type("bigint") == "integer"
    assert normalize_type("int") == "integer"


def test_integer_to_text_changes_normalized_type() -> None:
    assert normalize_type("integer") != normalize_type("text")
    assert normalize_type("text") == "string"


def test_numeric_and_float_are_number() -> None:
    assert normalize_type("numeric(10,2)") == "number"
    assert normalize_type("double precision") == "number"
    assert normalize_type("NUMBER(10,2)") == "number"


def test_timestamp_and_json_and_binary() -> None:
    assert normalize_type("timestamp with time zone") == "timestamp"
    assert normalize_type("jsonb") == "json"
    assert normalize_type("bytea") == "binary"
    assert normalize_type("boolean") == "boolean"
    assert normalize_type("date") == "date"


def test_unknown_native_type() -> None:
    assert normalize_type("geometry") == "unknown"
    assert normalize_type("") == "unknown"
