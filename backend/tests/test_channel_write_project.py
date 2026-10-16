"""Write Entity projects source objects through the node type execute."""

from __future__ import annotations

from types import SimpleNamespace

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
