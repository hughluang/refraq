"""Write Entity projects source objects through the node type execute."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.channel.nodes import list_node_types
from backend.tests.channel_hooks_fake import FakeHooks


def _execute():
    return next(item.execute for item in list_node_types() if item.type_id == "write.entity")


def _target() -> SimpleNamespace:
    return SimpleNamespace(
        attributes=(SimpleNamespace(name="sku", unique=True, business_key=False),)
    )


def _counts() -> SimpleNamespace:
    return SimpleNamespace(inserted=0, updated=0, unchanged=0, deleted=0, unmatched=0)


def _run(monkeypatch, source: str, mapping: list, seen: dict):
    def write_rows(entity_id, **kwargs):
        del entity_id
        seen["rows"] = kwargs["rows"]
        return _counts()

    monkeypatch.setattr("backend.channel.nodes.write.entity.head_target", lambda entity_id: _target())
    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", write_rows)
    return _execute()(
        {
            "id": "nd_write",
            "type": "write.entity",
            "config": {
                "entity_id": "ent_sku",
                "mode": "upsert",
                "match_key": "sku",
                "source": source,
                "mapping": mapping,
                "on_incompatible_head": "fail",
            },
        },
        FakeHooks(),
    )


def test_unmapped_keys_pass_through_and_mapped_keys_are_renamed(monkeypatch) -> None:
    seen: dict = {}
    result = _run(
        monkeypatch,
        '[{"product_code": "a", "name": "n"}]',
        [{"attribute": "sku", "key": "product_code"}],
        seen,
    )
    assert result.status == "succeeded"
    assert seen["rows"] == [{"name": "n", "sku": "a"}]


def test_mapping_wins_over_same_named_source_key(monkeypatch) -> None:
    seen: dict = {}
    result = _run(
        monkeypatch,
        '[{"sku": "old", "code": "new"}]',
        [{"attribute": "sku", "key": "code"}],
        seen,
    )
    assert result.status == "succeeded"
    assert seen["rows"] == [{"sku": "new"}]


def test_empty_mapping_writes_source_as_is(monkeypatch) -> None:
    seen: dict = {}
    result = _run(monkeypatch, '[{"sku": "a"}]', [], seen)
    assert result.status == "succeeded"
    assert seen["rows"] == [{"sku": "a"}]


def test_list_over_the_item_limit_fails_before_write(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr("backend.channel.nodes.write.entity.ITEM_LIMIT", 1)
    result = _run(
        monkeypatch,
        '[{"sku": "a"}, {"sku": "b"}]',
        [],
        seen,
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
    assert result.error_message == "Use Materialize or Dataset Query, then Batch Read."
    assert "rows" not in seen


def test_statement_timeout_sec_defaults_between_one_and_3600() -> None:
    from jsonschema import Draft202012Validator

    spec = next(item for item in list_node_types() if item.type_id == "write.entity")
    prop = spec.config_schema["properties"]["statement_timeout_sec"]
    assert prop["type"] == "integer"
    assert prop["minimum"] == 1
    assert prop["maximum"] == 3600
    assert prop["default"] == 300
    assert prop["title"] == "Statement timeout"
    assert "statement_timeout_sec" not in spec.config_schema["required"]
    config = {
        "entity_id": "ent_sku",
        "mode": "upsert",
        "match_key": "sku",
        "source": "[]",
        "mapping": [],
        "on_incompatible_head": "fail",
    }
    validator = Draft202012Validator(spec.config_schema)
    assert list(validator.iter_errors(config)) == []
    assert list(validator.iter_errors({**config, "statement_timeout_sec": 300})) == []
    assert list(validator.iter_errors({**config, "statement_timeout_sec": 0}))
    assert list(validator.iter_errors({**config, "statement_timeout_sec": 3601}))


def test_source_template_accepts_a_list_or_a_dataset_reference() -> None:
    import json

    from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
    from backend.channel.template import TemplateTypeError, render, static_check, parse
    from backend.channel.values import LIST_OF_OBJECTS

    spec = next(item for item in list_node_types() if item.type_id == "write.entity")
    schema = spec.config_schema["properties"]["source"]["x-refraq-template"]
    assert schema["type"] == ["array", "object"]
    assert schema["items"] == LIST_OF_OBJECTS["items"]
    assert schema["properties"] is DATASET_REFERENCE_SCHEMA["properties"]
    assert schema["required"] is DATASET_REFERENCE_SCHEMA["required"]
    assert schema["additionalProperties"] is DATASET_REFERENCE_SCHEMA["additionalProperties"]
    assert schema["x-refraq-dataset-reference"] is True

    listed = '[{"sku": "a", "qty": 1}]'
    assert static_check(parse(listed), schema) == "ok"
    assert render(listed, lambda body: body, schema) == [{"sku": "a", "qty": 1}]

    reference = dataset_reference(
        dataset_id="dabc",
        columns=[{"name": "sku", "normalized_type": "string"}],
        count=1,
    )
    rendered = render(json.dumps(reference), lambda body: body, schema)
    assert rendered == reference

    with pytest.raises(TemplateTypeError):
        render('{"sku": "a"}', lambda body: body, schema)


def _record(dataset_id: str, **overrides):
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetRecord
    from backend.entity.datasets import physical_relation

    body = {
        "id": dataset_id,
        "job_id": "run",
        "node_id": "nd_load",
        "seq": 1,
        "relation": physical_relation(dataset_id),
        "columns": [{"name": "product_code", "type": "text", "normalized_type": "string"}],
        "row_count": 2,
        "size_bytes": 1,
        "status": "ready",
        "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "expires_at": None,
    }
    body.update(overrides)
    return DatasetRecord(**body)


def _dataset_source(dataset_id: str) -> str:
    import json

    return json.dumps(
        {
            "dataset_id": dataset_id,
            "columns": [{"name": "ignored", "type": "string"}],
            "count": 0,
        }
    )


def test_dataset_mapping_renames_columns_and_keeps_ord(monkeypatch) -> None:
    from backend.channel.dataset_registry import DatasetRegistry, MemoryDatasetStore

    store = MemoryDatasetStore()
    record = _record("dmap")
    store.save(record)
    seen: dict = {}

    def chunks(relation: str, **kwargs):
        del kwargs
        assert relation == record.relation
        yield [(4, {"product_code": "a", "name": "n"})]

    def write_rows(entity_id, **kwargs):
        del entity_id
        seen["rows"] = list(kwargs["rows"])
        return _counts()

    monkeypatch.setattr("backend.channel.nodes.write.entity.get_dataset_store", lambda: store)
    monkeypatch.setattr("backend.channel.nodes.write.entity.head_target", lambda entity_id: _target())
    monkeypatch.setattr("backend.channel.nodes.write.entity.iter_dataset_chunks", chunks)
    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", write_rows)
    monkeypatch.setattr(
        "backend.channel.dataset_registry.any_row_exists",
        lambda relation: True,
    )
    result = _execute()(
        {
            "id": "nd_write",
            "type": "write.entity",
            "config": {
                "entity_id": "ent_sku",
                "mode": "upsert",
                "match_key": "sku",
                "source": _dataset_source(record.id),
                "mapping": [{"attribute": "sku", "key": "product_code"}],
                "on_incompatible_head": "fail",
            },
        },
        FakeHooks(),
    )
    assert result.status == "succeeded"
    assert seen["rows"] == [[(4, {"name": "n", "sku": "a"})]]


def test_dataset_missing_mapped_key_uses_the_row_ord(monkeypatch) -> None:
    from backend.channel.dataset_registry import MemoryDatasetStore

    store = MemoryDatasetStore()
    record = _record("dmiss")
    store.save(record)
    seen: dict = {}

    def chunks(relation: str, **kwargs):
        del relation, kwargs
        yield [(4, {"product_code": "a"})]
        yield [(9, {"other": 1})]

    def write_rows(entity_id, **kwargs):
        del entity_id
        seen["rows"] = list(kwargs["rows"])
        return _counts()

    monkeypatch.setattr("backend.channel.nodes.write.entity.get_dataset_store", lambda: store)
    monkeypatch.setattr("backend.channel.nodes.write.entity.head_target", lambda entity_id: _target())
    monkeypatch.setattr("backend.channel.nodes.write.entity.iter_dataset_chunks", chunks)
    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", write_rows)
    monkeypatch.setattr(
        "backend.channel.dataset_registry.any_row_exists",
        lambda relation: True,
    )
    result = _execute()(
        {
            "id": "nd_write",
            "type": "write.entity",
            "config": {
                "entity_id": "ent_sku",
                "mode": "upsert",
                "match_key": "sku",
                "source": _dataset_source(record.id),
                "mapping": [{"attribute": "sku", "key": "product_code"}],
                "on_incompatible_head": "fail",
            },
        },
        FakeHooks(),
    )
    assert result.status == "failed"
    assert result.error_message == "Source object 9 has no key 'product_code' for attribute 'sku'"
    assert result.error_detail == {"row_index": 9, "attribute": "sku"}
    assert "rows" not in seen


_PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("dataset_id", "overrides", "present", "reason"),
    [
        ("dabsent", None, True, "not_found"),
        (
            "dforeign",
            {"job_id": "other", "status": "dropped", "expires_at": _PAST},
            True,
            "foreign_run",
        ),
        ("dexpired", {"expires_at": _PAST}, True, "expired"),
        ("ddropped", {"status": "dropped", "row_count": 3}, True, "not_found"),
        ("dlost", {"row_count": 4}, False, "lost"),
    ],
)
def test_unreadable_dataset_fails_and_does_not_write(
    monkeypatch,
    dataset_id: str,
    overrides: dict | None,
    present: bool,
    reason: str,
) -> None:
    from backend.channel.dataset_registry import MemoryDatasetStore

    store = MemoryDatasetStore()
    if overrides is not None:
        store.save(_record(dataset_id, **overrides))
    seen: dict = {}

    def chunks(relation: str, **kwargs):
        del relation, kwargs
        raise AssertionError("dataset rows were read")

    def write_rows(entity_id, **kwargs):
        del entity_id, kwargs
        seen["called"] = True
        return _counts()

    monkeypatch.setattr("backend.channel.nodes.write.entity.get_dataset_store", lambda: store)
    monkeypatch.setattr("backend.channel.nodes.write.entity.head_target", lambda entity_id: _target())
    monkeypatch.setattr("backend.channel.nodes.write.entity.iter_dataset_chunks", chunks)
    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", write_rows)
    monkeypatch.setattr(
        "backend.channel.dataset_registry.any_row_exists",
        lambda relation: present,
    )
    result = _execute()(
        {
            "id": "nd_write",
            "type": "write.entity",
            "config": {
                "entity_id": "ent_sku",
                "mode": "upsert",
                "match_key": "sku",
                "source": _dataset_source(dataset_id),
                "mapping": [],
                "on_incompatible_head": "fail",
            },
        },
        FakeHooks(),
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_DATASET_UNAVAILABLE"
    assert result.error_detail == {"reason": reason}
    assert "called" not in seen


def test_missing_mapped_key_names_object_and_key(monkeypatch) -> None:
    seen: dict = {}
    result = _run(
        monkeypatch,
        '[{"code": "a"}, {"other": 1}]',
        [{"attribute": "sku", "key": "code"}],
        seen,
    )
    assert result.status == "failed"
    assert result.error_message == "Source object 1 has no key 'code' for attribute 'sku'"
    assert "rows" not in seen
