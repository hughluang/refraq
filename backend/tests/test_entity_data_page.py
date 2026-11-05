"""Which pages may run inside the profile query block. No database connection."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from backend.entity.access.compiler import Shape, predicate_depends_on_row
from backend.entity.access.facts import GrantSpec
from backend.entity.data.filters import filter_is_leakproof
from backend.entity.data.head import HeadTarget
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)


def test_row_rule_marks_the_predicate_row_dependent() -> None:
    grant = _grant(None)
    shape = _shape(grant)
    assert predicate_depends_on_row(shape) is False
    assert predicate_depends_on_row(
        replace(shape, grants=(_grant({"eq": ["sku", "a"]}),))
    )
    assert predicate_depends_on_row(replace(shape, row_rules=({"eq": ["sku", "a"]},)))


def test_leakproof_filters_may_share_the_profile_query_block() -> None:
    target = _target()
    assert filter_is_leakproof(None, target)
    assert filter_is_leakproof({}, target)
    assert filter_is_leakproof({"field": "sku", "op": "eq", "value": "a"}, target)
    assert filter_is_leakproof({"field": "row_id", "op": "gt", "value": 1}, target)
    assert filter_is_leakproof({"field": "qty", "op": "is_null"}, target)
    assert filter_is_leakproof({"field": "ref", "op": "eq", "value": 1}, target)
    assert filter_is_leakproof(
        {
            "all": [
                {"field": "sku", "op": "eq", "value": "a"},
                {"field": "row_id", "op": "gte", "value": 1},
            ]
        },
        target,
    )
    assert not filter_is_leakproof(
        {"field": "sku", "op": "contains", "value": "a"}, target
    )
    assert not filter_is_leakproof({"field": "qty", "op": "eq", "value": "1.00"}, target)
    assert not filter_is_leakproof({"field": "doc", "op": "eq", "value": {}}, target)
    assert not filter_is_leakproof(
        {
            "any": [
                {"field": "sku", "op": "eq", "value": "a"},
                {"field": "note", "op": "contains", "value": "a"},
            ]
        },
        target,
    )


def _grant(row_rule: dict[str, object] | None) -> GrantSpec:
    return GrantSpec(
        id="g",
        subject_type="user",
        subject_id="u",
        profile_id="p",
        row_rule=row_rule,
        actions=frozenset({"read"}),
        status="active",
        valid_until=None,
    )


def _shape(grant: GrantSpec) -> Shape:
    return Shape(
        action="read",
        profile_ids=("p",),
        combo_key="p",
        shape_key="k",
        grants=(grant,),
        columns=(),
        row_rules=(),
        included_restrictions=(),
        excluded_restrictions=(),
        hide_restrictions=(),
        force_empty=False,
        withheld=False,
        view_name="v",
    )


def _target() -> HeadTarget:
    now = datetime.now(timezone.utc)
    attributes = (
        AttributeRecord(name="sku", type="string", max_length=8),
        AttributeRecord(name="qty", type="decimal", precision=10, scale=2),
        AttributeRecord(name="doc", type="json"),
        AttributeRecord(
            name="ref",
            type="reference",
            target_entity_id="ent_other",
            reference_key_type="integer",
        ),
    )
    entity = BusinessEntityRecord(
        id="ent",
        table_name="widget",
        name="Widget",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    head = EntityVersionRecord(
        id="ver",
        entity_id="ent",
        version=1,
        attributes=list(attributes),
        materialized_attributes=[],
        publish_status="published",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
        reference_snapshots={"ref": {"type": "integer"}},
    )
    return HeadTarget(
        entity=entity,
        head=head,
        attributes=attributes,
        physical_table="widget__v1__0123456789abcdef",
        qualified_table='"entity_data"."widget__v1__0123456789abcdef"',
        writable=False,
        read_relation='"entity_access"."widget_v"',
    )
