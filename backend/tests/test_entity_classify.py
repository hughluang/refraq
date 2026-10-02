"""Change classifier coverage for docs/business-entity.md §3.2 / §3.3."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.entity.classify import classify_shapes
from backend.entity.dictionaries.records import DictionaryEntryRecord, DictionaryRecord
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import EntityAttributeInvalid, EntityTableNameInvalid
from backend.entity.lifecycle import PUBLISHED
from backend.entity.records import AttributeRecord, EntityVersionRecord
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
    dictionary_id: str | None = None,
    codes: tuple[str, ...] | None = None,
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
        dictionary_id=dictionary_id,
        codes=codes,
        target_entity_id=target_entity_id,
    )


def _dictionary(
    dictionary_id: str,
    *codes: str,
    inactive: tuple[str, ...] = (),
) -> None:
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    entries = [
        DictionaryEntryRecord(code=code, label=None, active=True, position=index)
        for index, code in enumerate(codes)
    ]
    offset = len(entries)
    entries.extend(
        DictionaryEntryRecord(
            code=code, label=None, active=False, position=offset + index
        )
        for index, code in enumerate(inactive)
    )
    get_dictionary_store().create(
        DictionaryRecord(
            id=dictionary_id,
            name=dictionary_id,
            display_name=dictionary_id,
            description=None,
            revision=1,
            deprecated_at=None,
            entries=tuple(entries),
            created_at=now,
            updated_at=now,
        )
    )


def _published(*snapshots: tuple[str, str, list[str]]) -> EntityVersionRecord:
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    return EntityVersionRecord(
        id="ver_published",
        entity_id="ent_1",
        version=1,
        attributes=[],
        materialized_attributes=[],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
        dictionary_snapshots={
            name: {"dictionary_id": dictionary_id, "revision": 1, "codes": codes}
            for name, dictionary_id, codes in snapshots
        },
    )


def test_validate_shape_allows_empty() -> None:
    assert validate_shape(attributes=[]) == []


def test_empty_shapes_are_unchanged() -> None:
    result = classify_shapes((), (), versions=())
    assert result.change_class == "unchanged"
    assert result.changes == ()


def test_add_first_optional_attribute_to_empty_is_non_breaking() -> None:
    result = classify_shapes((), (_attr("note", required=False),), versions=())
    assert result.change_class == "non_breaking"


def test_unchanged_empty_delta() -> None:
    shape = (_attr("sku"),)
    result = classify_shapes(shape, shape, versions=())
    assert result.change_class == "unchanged"
    assert result.changes == ()


def test_add_optional_attribute_is_non_breaking() -> None:
    before = (_attr("sku"),)
    after = (_attr("sku"), _attr("note", required=False))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "non_breaking"
    assert result.changes[0].field == "attributes.note"
    assert result.changes[0].change_class == "non_breaking"


def test_add_required_attribute_is_breaking() -> None:
    before = (_attr("sku"),)
    after = (_attr("sku"), _attr("lot_id", required=True))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"
    assert result.changes[0].change_class == "breaking"


def test_string_to_text_is_breaking() -> None:
    before = (_attr("note", "string"),)
    after = (_attr("note", "text"),)
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.note.type"


def test_integer_to_number_is_breaking() -> None:
    before = (_attr("sku"), _attr("qty", "integer", required=False))
    after = (_attr("sku"), _attr("qty", "number", required=False))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.qty.type"


def test_widen_max_length_is_non_breaking_and_narrow_is_breaking() -> None:
    before = (_attr("sku", max_length=16),)
    wider = classify_shapes(before, (_attr("sku", max_length=32),), versions=())
    assert wider.change_class == "non_breaking"
    assert wider.changes[0].field == "attributes.sku.config.max_length"
    narrower = classify_shapes(before, (_attr("sku", max_length=8),), versions=())
    assert narrower.change_class == "breaking"


def test_snapshot_code_add_is_non_breaking() -> None:
    _dictionary("cl_status", "draft", "live")
    status = (_attr("status", "dictionary", dictionary_id="cl_status"),)
    added = classify_shapes(
        status,
        status,
        versions=(_published(("status", "cl_status", ["draft"])),),
    )
    assert added.change_class == "non_breaking"
    assert added.changes[0].field == "attributes.status.config.dictionary"
    assert added.changes[0].new_value["added"] == ["live"]
    assert added.changes[0].new_value["removed"] == []


def test_inactive_snapshot_code_is_breaking() -> None:
    _dictionary("cl_status", "live", inactive=("draft",))
    status = (_attr("status", "dictionary", dictionary_id="cl_status"),)
    removed = classify_shapes(
        status,
        status,
        versions=(_published(("status", "cl_status", ["draft"])),),
    )
    assert removed.change_class == "breaking"
    assert removed.changes[0].new_value["removed"] == ["draft"]


def test_same_codes_on_another_dictionary_are_unchanged() -> None:
    _dictionary("cl_status", "draft")
    _dictionary("cl_other", "draft")
    result = classify_shapes(
        (_attr("status", "dictionary", dictionary_id="cl_status"),),
        (_attr("status", "dictionary", dictionary_id="cl_other"),),
        versions=(),
    )
    assert result.change_class == "unchanged"
    assert result.changes[0].field == "attributes.status.config.dictionary"
    assert result.changes[0].new_value["added"] == []
    assert result.changes[0].new_value["removed"] == []


def test_without_snapshot_each_side_reads_its_dictionary() -> None:
    _dictionary("cl_saved", "draft")
    _dictionary("cl_proposed", "draft", "live")
    result = classify_shapes(
        (_attr("status", "dictionary", dictionary_id="cl_saved"),),
        (_attr("status", "dictionary", dictionary_id="cl_proposed"),),
        versions=(),
    )
    assert result.change_class == "non_breaking"
    assert result.changes[0].new_value["added"] == ["live"]
    assert result.changes[0].new_value["removed"] == []


def test_stuffed_codes_on_the_same_dictionary_are_ignored() -> None:
    _dictionary("cl_status", "draft")
    result = classify_shapes(
        (
            _attr(
                "status", "dictionary", dictionary_id="cl_status", codes=("draft",)
            ),
        ),
        (
            _attr(
                "status",
                "dictionary",
                dictionary_id="cl_status",
                codes=("draft", "live"),
            ),
        ),
        versions=(),
    )
    assert result.change_class == "unchanged"
    assert result.changes == ()


def test_unknown_dictionary_is_invalid() -> None:
    status = (_attr("status", "dictionary", dictionary_id="missing"),)
    with pytest.raises(EntityAttributeInvalid, match="does not name a dictionary"):
        classify_shapes(status, status, versions=())


def test_relax_required_is_non_breaking() -> None:
    before = (_attr("sku"), _attr("note", "string", required=True))
    after = (_attr("sku"), _attr("note", "string", required=False))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "non_breaking"
    assert result.changes[0].field == "attributes.note.required"


def test_rename_attribute_is_breaking() -> None:
    before = (_attr("sku"),)
    after = (_attr("sku_code"),)
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"
    fields = {change.field for change in result.changes}
    assert "attributes.sku" in fields
    assert "attributes.sku_code" in fields


def test_drop_attribute_is_breaking() -> None:
    before = (_attr("sku"), _attr("note", required=False))
    after = (_attr("sku"),)
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"
    assert result.changes[0].field == "attributes.note"


def test_other_type_change_is_breaking() -> None:
    before = (_attr("sku"), _attr("qty", "number", required=False))
    after = (_attr("sku"), _attr("qty", "integer", required=False))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"


def test_tighten_required_is_breaking() -> None:
    before = (_attr("sku"), _attr("note", required=False))
    after = (_attr("sku"), _attr("note", required=True))
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "breaking"


def test_unique_and_indexed_are_non_breaking() -> None:
    before = (_attr("sku"),)
    after = (_attr("sku", unique=True, indexed=True),)
    result = classify_shapes(before, after, versions=())
    assert result.change_class == "non_breaking"
    fields = {change.field: change.change_class for change in result.changes}
    assert fields["attributes.sku.unique"] == "non_breaking"
    assert fields["attributes.sku.indexed"] == "non_breaking"


def test_description_only_is_unchanged() -> None:
    before = (_attr("sku", description="old"),)
    after = (_attr("sku", description="new"),)
    result = classify_shapes(before, after, versions=())
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
        require_table_name("material__v1__0123456789abcdef")
    require_table_name("encv_0123456789ab")


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
