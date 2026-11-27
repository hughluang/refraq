"""Which pages may run inside the profile query block. No database connection."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from backend.entity.access.compiler import Shape, predicate_depends_on_row
from backend.entity.access.facts import GrantSpec
from backend.entity.data.filters import CompiledFilter, compile_filters
from backend.entity.data.sql import query_keyset, query_offset
from backend.entity.data.head import HeadTarget
from backend.entity.data.paging import resolve_sort
from backend.entity.errors import EntityRequestInvalid, EntityRowInvalid
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


@pytest.mark.parametrize("raw", [
    None, [], [{"field": "sku", "direction": "asc"}], {"field": "sku"},
    {"field": None, "direction": "asc"}, {"field": "sku", "direction": ["asc"]},
    {"field": "sku", "direction": "ascending"}, {"field": "sku", "direction": "asc", "extra": True},
])
def test_sort_rejects_invalid_structure(raw: object) -> None:
    with pytest.raises(EntityRequestInvalid):
        resolve_sort({"sort": raw}, _target())


@pytest.mark.parametrize("name", ["doc", "__withheld", "missing"])
def test_sort_accepts_only_visible_scalar_fields(name: str) -> None:
    with pytest.raises(EntityRowInvalid):
        resolve_sort({"sort": {"field": name, "direction": "asc"}}, _target())


def test_large_profile_page_is_one_execution_and_keeps_cursor() -> None:
    class Rows:
        def all(self):
            return [(row_id,) for row_id in range(501, 10502)]
    class Connection:
        def __init__(self):
            self.calls = []
        def execute(self, statement, params):
            self.calls.append((str(statement), params))
            return Rows()
    conn = Connection()
    compiled = compile_filters({"field": "row_id", "op": "gt", "value": 500}, _target())
    items, after = query_keyset(
        conn, _target(), fields=["row_id"], compiled=compiled,
        row_dependent=False, limit=10000, after_row_id=500,
    )
    assert [row["row_id"] for row in items] == list(range(501, 10501))
    assert after == 10500
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert '"profile_page"' in sql
    assert params["_limit"] == 10001
    assert params["_offset"] == 0
    assert params["_after"] == 500
    assert params["_filter"] == '{"field":"row_id","op":"gt","value":500}'


def test_large_offset_projection_and_count_are_separate() -> None:
    class Rows:
        def all(self):
            return [("a",)] * 1000
        def scalar_one(self):
            return 1500
    class Connection:
        def __init__(self):
            self.calls = []
        def execute(self, statement, params):
            self.calls.append((str(statement), params))
            return Rows()
    conn = Connection()
    items, total = query_offset(
        conn, _target(), fields=["sku"], compiled=None,
        row_dependent=False, limit=1000, offset=250, include_total=True,
    )
    assert items == [{"sku": "a"}] * 1000
    assert total == 1500
    assert len(conn.calls) == 2
    assert '"profile_page"' in conn.calls[0][0]
    assert conn.calls[0][1]["_limit"] == 1000
    assert conn.calls[0][1]["_offset"] == 250
    assert conn.calls[0][1]["_columns"] == ["sku"]
    assert '"profile_count"' in conn.calls[1][0]


@pytest.mark.parametrize("count", [300, 301])
def test_internal_read_keeps_its_own_probe_limit(monkeypatch, count) -> None:
    from backend.admin.system_parameters import set_parameter
    from backend.entity import rows
    from backend.entity.errors import EntityRowLimitExceeded
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()
    set_parameter("entity_page_limit_max", 50, actor_user_id=None)
    target = _target()
    access = SimpleNamespace(
        target=replace(target, attributes=()), outcome=SimpleNamespace(shape=_shape(_grant(None))),
        log=lambda **kwargs: None,
    )
    monkeypatch.setattr(rows, "get_entity_store", lambda: SimpleNamespace(get_entity=lambda id: target.entity))
    monkeypatch.setattr(rows, "begin_data", lambda *args, **kwargs: access)
    monkeypatch.setattr(rows, "read_context", lambda access: None)
    class Result:
        def all(self):
            return [(i,) for i in range(1, count + 1)]
        def scalar_one(self):
            return count
    calls = []
    class Connection:
        def execute(self, statement, params):
            calls.append((str(statement), params))
            return Result()
    monkeypatch.setattr(rows.data_sql, "entity_read_connection", lambda ctx, **kwargs: nullcontext(Connection()))
    if count == 301:
        with pytest.raises(EntityRowLimitExceeded, match="Read returned more than 300 rows"):
            rows.read_rows("ent", filters=None, user=None, limit=300)
    else:
        items, total = rows.read_rows("ent", filters=None, user=None, limit=300)
        assert len(items) == total == 300
    assert len(calls) == 2
    assert calls[0][1]["_limit"] == 301


@pytest.mark.parametrize("size", [0, 250, 251])
def test_row_dependent_keyset_uses_one_direct_read(size) -> None:
    class Result:
        def all(self):
            return [(i,) for i in range(501, 501 + size)]
    calls = []
    class Connection:
        def execute(self, statement, params):
            calls.append((str(statement), params))
            return Result()
    items, after = query_keyset(
        Connection(), _target(), fields=["row_id"],
        compiled=CompiledFilter(
            sql='"sku" ILIKE :p0',
            params={"p0": "%a%"},
            profile_json='{"field":"sku","op":"contains","value":"a"}',
            leakproof=False,
        ),
        row_dependent=True, limit=250, after_row_id=500,
    )
    assert len(items) == min(250, size)
    assert after == (750 if size > 250 else None)
    assert len(calls) == 1
    assert "profile_page" not in calls[0][0]
    assert calls[0][1] == {"p0": "%a%", "_after": 500, "_limit": 251}


@pytest.mark.parametrize("raw", [True, False, 0, -1, 1.5, "50"])
def test_limit_rejects_non_positive_or_non_integer(raw) -> None:
    from backend.entity.data.paging import resolve_limit
    from backend.entity.errors import EntityRequestInvalid

    with pytest.raises(EntityRequestInvalid, match="limit must be an integer >= 1"):
        resolve_limit(raw, maximum=200)


@pytest.mark.parametrize("maximum", [50, 200, 1000, 10000])
def test_paging_helpers_use_the_explicit_maximum(maximum) -> None:
    from backend.entity.data.paging import (
        resolve_keyset_query,
        resolve_limit,
        resolve_offset_query,
    )
    from backend.entity.errors import EntityRequestInvalid

    assert resolve_limit(None, maximum=maximum) == 50
    assert resolve_limit(1, maximum=maximum) == 1
    assert resolve_limit(maximum, maximum=maximum) == maximum
    assert resolve_offset_query({}, maximum=maximum) == (50, 0, True)
    assert resolve_keyset_query({}, maximum=maximum) == (50, None)
    assert resolve_offset_query({"limit": maximum}, maximum=maximum) == (maximum, 0, True)
    assert resolve_keyset_query({"limit": maximum}, maximum=maximum) == (maximum, None)
    with pytest.raises(EntityRequestInvalid, match=f"limit must be <= {maximum}"):
        resolve_limit(maximum + 1, maximum=maximum)
    with pytest.raises(EntityRequestInvalid, match=f"limit must be <= {maximum}"):
        resolve_offset_query({"limit": maximum + 1}, maximum=maximum)
    with pytest.raises(EntityRequestInvalid, match=f"limit must be <= {maximum}"):
        resolve_keyset_query({"limit": maximum + 1}, maximum=maximum)


def test_offset_total_uses_the_same_inline_gate() -> None:
    target = _target()
    open_conn = _Recording()
    query_offset(
        open_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id"],
        compiled=None,
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
        compiled=CompiledFilter(
            sql=" AND (sku ILIKE :p0)",
            params={"p0": "%a%"},
            profile_json='{"field":"sku","op":"contains","value":"a"}',
            leakproof=False,
        ),
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


def test_custom_sort_routing_for_non_row_dependent_and_row_dependent() -> None:
    from backend.entity.data.paging import RowSort

    target = _target()
    # Non-row-dependent: any sort + any filter uses profile_page and profile_count.
    open_conn = _Recording()
    query_offset(
        open_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id", "sku"],
        compiled=CompiledFilter(
            sql='"sku" ILIKE :p0',
            params={"p0": "%a%"},
            profile_json='{"field":"sku","op":"contains","value":"a"}',
            leakproof=False,
        ),
        row_dependent=False,
        limit=10,
        offset=0,
        include_total=True,
        sort=RowSort("sku", descending=True),
    )
    assert '"profile_page"' in open_conn.statements[0]
    assert '"profile_count"' in open_conn.statements[1]

    # Row-dependent + leakproof filter + row_id DESC: uses profile_page and profile_count.
    id_desc_conn = _Recording()
    query_offset(
        id_desc_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id"],
        compiled=compile_filters({"field": "sku", "op": "eq", "value": "a"}, target),
        row_dependent=True,
        limit=10,
        offset=0,
        include_total=True,
        sort=RowSort("row_id", descending=True),
    )
    assert '"profile_page"' in id_desc_conn.statements[0]
    assert '"profile_count"' in id_desc_conn.statements[1]

    # Row-dependent + leakproof filter + attribute sort: barrier view for rows, profile_count for total.
    attr_conn = _Recording()
    query_offset(
        attr_conn,  # type: ignore[arg-type]
        target,
        fields=["row_id", "sku"],
        compiled=compile_filters({"field": "sku", "op": "eq", "value": "a"}, target),
        row_dependent=True,
        limit=10,
        offset=0,
        include_total=True,
        sort=RowSort("sku", descending=False),
    )
    assert "profile_page" not in attr_conn.statements[0]
    assert '"entity_access"."widget_v"' in attr_conn.statements[0]
    assert '"profile_count"' in attr_conn.statements[1]


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
    assert compile_filters(None, target) is None
    assert compile_filters({}, target) is None
    assert compile_filters({"field": "sku", "op": "eq", "value": "a"}, target).leakproof
    assert compile_filters({"field": "sku", "op": "gte", "value": "a"}, target).leakproof
    assert compile_filters({"field": "sku", "op": "between", "value": ["a", "z"]}, target).leakproof
    assert compile_filters({"field": "row_id", "op": "gt", "value": 1}, target).leakproof
    assert compile_filters({"field": "qty", "op": "is_null"}, target).leakproof
    assert compile_filters({"field": "qty", "op": "is_not_null"}, target).leakproof
    assert compile_filters({"field": "ref", "op": "eq", "value": 1}, target).leakproof
    assert compile_filters(
        {
            "all": [
                {"field": "sku", "op": "eq", "value": "a"},
                {"field": "row_id", "op": "gte", "value": 1},
            ]
        },
        target,
    ).leakproof
    assert compile_filters(
        {"not": {"field": "sku", "op": "eq", "value": "a"}}, target
    ).leakproof
    assert not compile_filters(
        {"field": "sku", "op": "contains", "value": "a"}, target
    ).leakproof
    assert not compile_filters(
        {"field": "sku", "op": "starts_with", "value": "a"}, target
    ).leakproof
    assert not compile_filters(
        {"field": "sku", "op": "ieq", "value": "a"}, target
    ).leakproof
    assert not compile_filters({"field": "qty", "op": "eq", "value": "1.00"}, target).leakproof
    assert not compile_filters({"field": "doc", "op": "eq", "value": {}}, target).leakproof
    assert not compile_filters(
        {"field": "doc", "op": "has_key", "value": "k"}, target
    ).leakproof
    assert not compile_filters(
        {
            "any": [
                {"field": "sku", "op": "eq", "value": "a"},
                {"field": "sku", "op": "contains", "value": "a"},
            ]
        },
        target,
    ).leakproof


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
