"""Which pages may run inside the profile query block. No database connection."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from backend.entity.access.compiler import Shape, predicate_depends_on_row
from backend.entity.access.facts import GrantSpec
from backend.entity.data.filters import CompiledFilter, filter_is_leakproof
from backend.entity.data.sql import query_offset
from backend.entity.data.head import HeadTarget
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)


class _Result:
    def all(self) -> list[object]:
        return []

    def scalar_one(self) -> int:
        return 0


class _Recording:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object, params: object = None) -> _Result:
        self.statements.append(str(statement))
        return _Result()


def test_offset_total_uses_the_same_inline_gate() -> None:
    target = _target()
    open_conn = _Recording()
    query_offset(
        open_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id"],
        compiled=None,
        filters=None,
        row_dependent=False,
        limit=2,
        offset=0,
        include_total=True,
    )
    open_sql = "\n".join(open_conn.statements)
    assert '"profile_page"' in open_sql
    assert '"profile_count"' in open_sql
    assert not any(sql.startswith("SELECT count(*) FROM") for sql in open_conn.statements)

    closed_conn = _Recording()
    query_offset(
        closed_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id"],
        compiled=CompiledFilter(sql=" AND (sku ILIKE :p0)", params={"p0": "%a%"}),
        filters={"field": "sku", "op": "contains", "value": "a"},
        row_dependent=True,
        limit=2,
        offset=0,
        include_total=True,
    )
    counts = [
        sql for sql in closed_conn.statements if sql.startswith("SELECT count(*) FROM")
    ]
    assert len(counts) == 1
    assert '"entity_access"."widget_v"' in counts[0]
    assert "profile_count" not in counts[0]


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
