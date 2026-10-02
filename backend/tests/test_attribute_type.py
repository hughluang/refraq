"""Attribute Type is one object: clean, physical column, operators, codec, changes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from psycopg.types.json import Jsonb

from backend.entity.attribute_type import resolve
from backend.entity.errors import EntityAttributeInvalid, EntityRowInvalid
from backend.entity.records import AttributeRecord


def _attr(attribute_type: str, **kwargs) -> AttributeRecord:
    return AttributeRecord(name="col", type=attribute_type, **kwargs)


def test_resolve_rejects_unknown_and_blank_types() -> None:
    with pytest.raises(EntityAttributeInvalid, match="is required"):
        resolve("")
    with pytest.raises(EntityAttributeInvalid, match="is required"):
        resolve(None)
    with pytest.raises(EntityAttributeInvalid, match="not in the closed set"):
        resolve("many2one")


def test_clean_enforces_config_for_each_type() -> None:
    string = resolve("string")
    cleaned = string.clean(_attr("string", max_length=32))
    assert cleaned.max_length == 32
    assert cleaned.precision is None
    with pytest.raises(EntityAttributeInvalid, match="requires max_length"):
        string.clean(_attr("string"))
    with pytest.raises(EntityAttributeInvalid, match="65535"):
        string.clean(_attr("string", max_length=65536))
    with pytest.raises(EntityAttributeInvalid, match="must be an integer"):
        string.clean(_attr("string", max_length=True))
    with pytest.raises(EntityAttributeInvalid, match="rejects config"):
        resolve("text").clean(_attr("text", max_length=8))

    decimal = resolve("decimal")
    amount = decimal.clean(_attr("decimal", precision=10, scale=2))
    assert (amount.precision, amount.scale) == (10, 2)
    with pytest.raises(EntityAttributeInvalid, match="precision and scale"):
        decimal.clean(_attr("decimal", precision=10))
    with pytest.raises(EntityAttributeInvalid, match="between 0 and precision"):
        decimal.clean(_attr("decimal", precision=10, scale=12))

    listed = resolve("dictionary").clean(_attr("dictionary", dictionary_id=" cl "))
    assert listed.dictionary_id == "cl"
    with pytest.raises(EntityAttributeInvalid, match="requires dictionary_id"):
        resolve("dictionary").clean(_attr("dictionary"))

    ref = resolve("reference").clean(_attr("reference", target_entity_id=" ent "))
    assert ref.target_entity_id == "ent"
    with pytest.raises(EntityAttributeInvalid, match="requires target_entity_id"):
        resolve("reference").clean(_attr("reference", target_entity_id=""))


def test_stored_fields_ignore_unknown_keys_and_reject_bad_types() -> None:
    ignored = resolve("dictionary").stored_fields({"entries": "ACTIVE"})
    assert ignored == {}
    kept = resolve("dictionary").stored_fields(
        {"dictionary_id": "cl_status", "entries": [{"code": "ACTIVE"}]}
    )
    assert kept == {"dictionary_id": "cl_status"}
    with pytest.raises(TypeError, match="dictionary_id"):
        resolve("dictionary").stored_fields({"dictionary_id": 1})
    with pytest.raises(TypeError, match="integer"):
        resolve("decimal").stored_fields({"precision": True, "scale": 2})


def test_parse_config_uses_http_sentences() -> None:
    with pytest.raises(EntityAttributeInvalid, match="max_length must be an integer"):
        resolve("string").parse_config("sku", {"max_length": True})
    parsed = resolve("reference").parse_config("supplier", {"target_entity_id": " ent "})
    assert parsed == {"target_entity_id": "ent"}
    assert resolve("reference").parse_config("supplier", {"target_entity_id": None}) == {
        "target_entity_id": None
    }


def test_physical_sql_and_dictionary_check_predicate() -> None:
    assert resolve("string").physical_sql(_attr("string", max_length=32)) == "VARCHAR(32)"
    assert (
        resolve("decimal").physical_sql(_attr("decimal", precision=10, scale=2))
        == "NUMERIC(10,2)"
    )
    fixed = {
        "text": "TEXT",
        "integer": "BIGINT",
        "number": "DOUBLE PRECISION",
        "boolean": "BOOLEAN",
        "date": "DATE",
        "timestamp": "TIMESTAMPTZ",
        "time": "TIME",
        "json": "JSONB",
        "dictionary": "VARCHAR(64)",
        "reference": "BIGINT",
    }
    for name, sql in fixed.items():
        assert resolve(name).physical_sql(_attr(name)) == sql
        assert resolve(name).physical_template == sql
    predicate = resolve("dictionary").check_predicate(
        _attr("dictionary", codes=("a", "o'b")),
        column='"status"',
    )
    assert predicate == "\"status\" IS NULL OR \"status\" IN ('a', 'o''b')"
    assert resolve("string").check_predicate(_attr("string"), column='"col"') is None
    with pytest.raises(ValueError, match="no codes"):
        resolve("dictionary").check_predicate(_attr("dictionary"), column='"status"')


def test_operators_and_upsert_key_come_from_the_type() -> None:
    compared = ("eq", "ne", "in", "gt", "gte", "lt", "lte", "is_null")
    assert resolve("integer").operators == compared
    assert resolve("reference").operators == resolve("integer").operators
    assert resolve("string").operators == ("eq", "ne", "in", "contains", "is_null")
    assert resolve("dictionary").operators == ("eq", "ne", "in", "is_null")
    assert resolve("boolean").operators == ("eq", "ne", "is_null")
    assert resolve("boolean").allows_upsert_key is True
    assert resolve("number").allows_upsert_key is False
    assert resolve("json").allows_upsert_key is False
    assert resolve("reference").reads == frozenset({"target"})
    assert "dictionary" in resolve("dictionary").reads


def test_encode_and_decode_follow_the_row_rules() -> None:
    sku = _attr("string", max_length=3)
    assert resolve("string").encode(sku, "ab") == "ab"
    with pytest.raises(EntityRowInvalid, match="exceeds max_length"):
        resolve("string").encode(sku, "abcd")
    assert resolve("integer").encode(_attr("integer"), 4) == 4
    assert resolve("reference").encode(_attr("reference"), 4) == 4
    with pytest.raises(EntityRowInvalid, match="BIGINT"):
        resolve("integer").encode(_attr("integer"), 2**63)
    amount = resolve("decimal").encode(_attr("decimal", precision=10, scale=2), "1.2")
    assert amount == Decimal("1.20")
    wrapped = resolve("json").encode(_attr("json"), {"a": 1})
    assert isinstance(wrapped, Jsonb)
    assert wrapped.obj == {"a": 1}
    listed = _attr("dictionary")
    assert resolve("dictionary").encode(listed, "open", codes=frozenset({"open"})) == "open"
    with pytest.raises(EntityRowInvalid, match="not writable"):
        resolve("dictionary").encode(listed, "shut", codes=frozenset({"open"}))
    with pytest.raises(EntityRowInvalid, match="head snapshot"):
        resolve("dictionary").encode(
            listed, "shut", codes=frozenset({"open"}), as_filter=True
        )

    assert resolve("decimal").decode(_attr("decimal"), Decimal("1.20")) == "1.20"
    assert resolve("number").decode(_attr("number"), float("nan")) is None
    assert resolve("date").decode(_attr("date"), date(2026, 10, 2)) == "2026-10-02"
    stamped = datetime(2026, 10, 2, 3, 4, tzinfo=timezone.utc)
    assert resolve("timestamp").decode(_attr("timestamp"), stamped) == "2026-10-02T03:04:00Z"
    assert resolve("integer").decode(_attr("integer"), 7) == 7
    assert resolve("json").decode(_attr("json"), {"a": 1}) == {"a": 1}


def test_config_changes_classify_width_decimal_codes_and_target() -> None:
    wider = resolve("string").config_changes(
        _attr("string", max_length=8), _attr("string", max_length=16)
    )
    assert wider[0].suffix == "config.max_length"
    assert wider[0].change_class == "non_breaking"
    narrower = resolve("string").config_changes(
        _attr("string", max_length=8), _attr("string", max_length=4)
    )
    assert narrower[0].change_class == "breaking"
    assert resolve("text").config_changes(_attr("text"), _attr("text")) == ()

    decimal = resolve("decimal").config_changes(
        _attr("decimal", precision=10, scale=2),
        _attr("decimal", precision=12, scale=2),
    )
    assert [item.suffix for item in decimal] == ["config.precision"]
    assert decimal[0].change_class == "breaking"

    codes = resolve("dictionary").config_changes(
        _attr("dictionary", dictionary_id="cl", codes=("a",)),
        _attr("dictionary", dictionary_id="cl", codes=("a", "b")),
    )
    assert codes[0].suffix == "config.dictionary"
    assert codes[0].change_class == "non_breaking"
    assert codes[0].new_value["added"] == ["b"]
    assert codes[0].new_value["removed"] == []
    same_codes = resolve("dictionary").config_changes(
        _attr("dictionary", dictionary_id="cl", codes=("a",)),
        _attr("dictionary", dictionary_id="other", codes=("a",)),
    )
    assert same_codes[0].change_class == "unchanged"

    target = resolve("reference").config_changes(
        _attr("reference", target_entity_id="a"),
        _attr("reference", target_entity_id="b"),
    )
    assert target[0].suffix == "config.target_entity_id"
    assert target[0].change_class == "breaking"
