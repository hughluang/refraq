"""Change classifier coverage for docs/business-entity.md §3.2 / §3.3."""

from __future__ import annotations

import pytest

from backend.entity.classify import DefinitionShape, classify_shapes
from backend.entity.errors import EntityAttributeInvalid, EntityTableNameInvalid
from backend.entity.records import AttributeRecord, EnumerationEntry
from backend.entity.validate import (
    ATTRIBUTE_NAME_MAX_LEN,
    TABLE_NAME_MAX_LEN,
    require_attribute_name,
    require_table_name,
    validate_shape,
)


def _attr(
    name: str,
    attribute_type: str = "string",
    *,
    required: bool = True,
    unique: bool = False,
    indexed: bool = False,
    description: str | None = None,
    max_length: int | None = None,
    precision: int | None = None,
    scale: int | None = None,
    entries: tuple[EnumerationEntry, ...] | None = None,
    target_entity_id: str | None = None,
) -> AttributeRecord:
    return AttributeRecord(
        name=name,
        type=attribute_type,
        required=required,
        unique=unique,
        indexed=indexed,
        description=description,
        max_length=32 if attribute_type == "string" and max_length is None else max_length,
        precision=precision,
        scale=scale,
        entries=entries,
        target_entity_id=target_entity_id,
    )


def _shape(*attrs: AttributeRecord) -> DefinitionShape:
    return DefinitionShape(attributes=attrs)


def test_validate_shape_allows_empty() -> None:
    assert validate_shape(attributes=[]) == []


def test_empty_shapes_are_unchanged() -> None:
    result = classify_shapes(_shape(), _shape())
    assert result.change_class == "unchanged"
    assert result.changes == ()


def test_add_first_optional_attribute_to_empty_is_non_breaking() -> None:
    result = classify_shapes(_shape(), _shape(_attr("note", required=False)))
    assert result.change_class == "non_breaking"


def test_unchanged_empty_delta() -> None:
    shape = _shape(_attr("sku"))
    result = classify_shapes(shape, shape)
    assert result.change_class == "unchanged"
    assert result.changes == ()


def test_add_optional_attribute_is_non_breaking() -> None:
    before = _shape(_attr("sku"))
    after = _shape(_attr("sku"), _attr("note", required=False))
    result = classify_shapes(before, after)
    assert result.change_class == "non_breaking"
    assert result.changes[0].field == "attributes.note"
    assert result.changes[0].change_class == "non_breaking"


def test_add_required_attribute_is_breaking() -> None:
    before = _shape(_attr("sku"))
    after = _shape(_attr("sku"), _attr("lot_id", required=True))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"
    assert result.changes[0].change_class == "breaking"


def test_string_to_text_is_breaking() -> None:
    before = _shape(_attr("note", "string"))
    after = _shape(_attr("note", "text"))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.note.type"


def test_integer_to_number_is_breaking() -> None:
    before = _shape(_attr("sku"), _attr("qty", "integer", required=False))
    after = _shape(_attr("sku"), _attr("qty", "number", required=False))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.qty.type"


def test_widen_max_length_is_non_breaking_and_narrow_is_breaking() -> None:
    before = _shape(_attr("sku", max_length=16))
    wider = classify_shapes(before, _shape(_attr("sku", max_length=32)))
    assert wider.change_class == "non_breaking"
    assert wider.changes[0].field == "attributes.sku.config.max_length"
    narrower = classify_shapes(before, _shape(_attr("sku", max_length=8)))
    assert narrower.change_class == "breaking"


def test_enumeration_code_add_is_non_breaking_and_label_is_unchanged() -> None:
    before = _shape(
        _attr(
            "status",
            "enumeration",
            entries=(EnumerationEntry(code="draft", label="Draft"),),
        )
    )
    added = classify_shapes(
        before,
        _shape(
            _attr(
                "status",
                "enumeration",
                entries=(
                    EnumerationEntry(code="draft", label="Draft"),
                    EnumerationEntry(code="live", label="Live"),
                ),
            )
        ),
    )
    assert added.change_class == "non_breaking"
    assert added.changes[0].field == "attributes.status.config.entries"
    removed = classify_shapes(
        before,
        _shape(
            _attr(
                "status",
                "enumeration",
                entries=(EnumerationEntry(code="live", label="Live"),),
            )
        ),
    )
    assert removed.change_class == "breaking"
    relabeled = classify_shapes(
        before,
        _shape(
            _attr(
                "status",
                "enumeration",
                entries=(EnumerationEntry(code="draft", label="New"),),
            )
        ),
    )
    assert relabeled.change_class == "unchanged"


def test_relax_required_is_non_breaking() -> None:
    before = _shape(_attr("sku"), _attr("note", "string", required=True))
    after = _shape(_attr("sku"), _attr("note", "string", required=False))
    result = classify_shapes(before, after)
    assert result.change_class == "non_breaking"
    assert result.changes[0].field == "attributes.note.required"


def test_rename_attribute_is_breaking() -> None:
    before = _shape(_attr("sku"))
    after = _shape(_attr("sku_code"))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"
    fields = {change.field for change in result.changes}
    assert "attributes.sku" in fields
    assert "attributes.sku_code" in fields


def test_drop_attribute_is_breaking() -> None:
    before = _shape(_attr("sku"), _attr("note", required=False))
    after = _shape(_attr("sku"))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.note"


def test_other_type_change_is_breaking() -> None:
    before = _shape(_attr("sku"), _attr("qty", "number", required=False))
    after = _shape(_attr("sku"), _attr("qty", "integer", required=False))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"


def test_tighten_required_is_breaking() -> None:
    before = _shape(_attr("sku"), _attr("note", required=False))
    after = _shape(_attr("sku"), _attr("note", required=True))
    result = classify_shapes(before, after)
    assert result.change_class == "breaking"


def test_unique_and_indexed_are_non_breaking() -> None:
    before = _shape(_attr("sku"))
    after = _shape(_attr("sku", unique=True, indexed=True))
    result = classify_shapes(before, after)
    assert result.change_class == "non_breaking"
    fields = {change.field: change.change_class for change in result.changes}
    assert fields["attributes.sku.unique"] == "non_breaking"
    assert fields["attributes.sku.indexed"] == "non_breaking"


def test_description_only_is_unchanged() -> None:
    before = _shape(_attr("sku", description="old"))
    after = _shape(_attr("sku", description="new"))
    result = classify_shapes(before, after)
    assert result.change_class == "unchanged"
    assert result.changes[0].field == "attributes.sku.description"


def test_table_name_length_boundary() -> None:
    require_table_name("a" + "x" * (TABLE_NAME_MAX_LEN - 1))
    with pytest.raises(EntityTableNameInvalid):
        require_table_name("a" + "x" * TABLE_NAME_MAX_LEN)
    with pytest.raises(EntityTableNameInvalid):
        require_table_name("1bad")
    with pytest.raises(EntityTableNameInvalid):
        require_table_name("Bad")
    with pytest.raises(EntityTableNameInvalid):
        require_table_name("material__rfq_v1")


def test_row_id_is_reserved() -> None:
    with pytest.raises(EntityAttributeInvalid, match="row_id"):
        require_attribute_name("row_id")


def test_attribute_name_rules_are_specific() -> None:
    with pytest.raises(EntityAttributeInvalid, match="required"):
        require_attribute_name("  ")
    with pytest.raises(EntityAttributeInvalid, match="at most 63"):
        require_attribute_name("a" + "x" * ATTRIBUTE_NAME_MAX_LEN)
    with pytest.raises(EntityAttributeInvalid, match="must start with a letter"):
        require_attribute_name("1bad")
    require_attribute_name("a" + "x" * (ATTRIBUTE_NAME_MAX_LEN - 1))
