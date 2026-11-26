"""Unit tests for staged write SQL shapes and validation invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.entity import rows as entity_rows
from backend.entity.data import sql as data_sql


def test_uniform_upsert_and_replace_emit_no_stage_subqueries() -> None:
    cols = ["sku", "qty", "note", "extra"]
    present = {"sku": True, "qty": True, "note": True, "extra": True}
    for mode in ("upsert", "replace"):
        sql = data_sql._staged_sql(
            '"entity_data"."t"',
            '"entity_data"."wstage_1"',
            mode,
            "sku",
            cols,
            present,
        )
        assert 'FROM "entity_data"."wstage_1" AS g' not in sql
        assert '"qty" = excluded."qty"' in sql
        assert '"note" = excluded."note"' in sql
        assert '"extra" = excluded."extra"' in sql
        assert 't."qty" IS DISTINCT FROM excluded."qty"' in sql
        assert "IS NOT DISTINCT FROM" not in sql


def test_heterogeneous_upsert_and_replace_collapse_into_one_multi_column_subquery() -> None:
    cols = ["sku", "qty", "note", "extra", "absent"]
    present = {"sku": True, "qty": True, "note": False, "extra": False}
    for mode in ("upsert", "replace"):
        sql = data_sql._staged_sql(
            '"entity_data"."t"',
            '"entity_data"."wstage_1"',
            mode,
            "sku",
            cols,
            present,
        )
        # Exactly one assignment subquery and one guard subquery against wstage_1 AS g.
        assert sql.count('FROM "entity_data"."wstage_1" AS g') == 2
        assert '("note", "extra") = (SELECT CASE WHEN' in sql
        assert '"qty" = excluded."qty"' in sql
        assert '"absent"' not in sql.split("ON CONFLICT", 1)[1]
        assert "IS NOT DISTINCT FROM" not in sql


def test_heterogeneous_single_column_uses_scalar_assignment() -> None:
    cols = ["sku", "note"]
    sql_single = data_sql._staged_sql(
        '"entity_data"."t"',
        '"entity_data"."wstage_1"',
        "upsert",
        "sku",
        cols,
        {"sku": True, "note": False},
    )
    assert '"note" = (SELECT CASE WHEN' in sql_single
    assert '("note")' not in sql_single


def test_duplicate_and_replace_delete_rule_sql_do_not_use_is_not_distinct_from() -> None:
    dup_sql = entity_rows._duplicate_sql('"entity_data"."wstage_1"', "sku")
    assert "IS NOT DISTINCT FROM" not in dup_sql
    assert "GROUP BY" in dup_sql
    assert "JOIN" not in dup_sql

    grant = SimpleNamespace(row_rule=None)
    access = SimpleNamespace(
        policy=SimpleNamespace(attributes=[], subject_values={}, restrictions=[]),
        person=SimpleNamespace(user_id="usr_1"),
        compiled=SimpleNamespace(broken_restrictions=set()),
    )
    target = SimpleNamespace(qualified_table='"entity_data"."t"')
    del_rule_sql = entity_rows._replace_delete_rule_sql(
        access, [grant], target, '"entity_data"."wstage_1"', "sku"
    )
    assert "IS NOT DISTINCT FROM" not in del_rule_sql
    assert 's."sku" = t."sku"' in del_rule_sql


def test_has_unconditional_grant_respects_row_rules_and_restrictions() -> None:
    unconditional = SimpleNamespace(row_rule=None)
    conditional = SimpleNamespace(row_rule={"eq": {"attr": "a1", "value": 1}})
    restriction = SimpleNamespace(
        id="rst_1",
        actions=("write",),
        mode="all",
    )
    broken_restriction = SimpleNamespace(
        id="rst_broken",
        actions=("write",),
        mode="all",
    )
    read_only_restriction = SimpleNamespace(
        id="rst_read",
        actions=("read",),
        mode="all",
    )

    def make_access(restrictions: list[Any], broken: set[str] | None = None) -> Any:
        return SimpleNamespace(
            policy=SimpleNamespace(restrictions=restrictions),
            compiled=SimpleNamespace(broken_restrictions=broken or set()),
            person=SimpleNamespace(user_id="usr_1"),
        )

    assert entity_rows._has_unconditional_grant(make_access([]), [unconditional]) is True
    assert entity_rows._has_unconditional_grant(make_access([]), [conditional]) is False
    assert (
        entity_rows._has_unconditional_grant(make_access([restriction]), [unconditional])
        is False
    )
    assert (
        entity_rows._has_unconditional_grant(
            make_access([broken_restriction], broken={"rst_broken"}), [unconditional]
        )
        is True
    )
    assert (
        entity_rows._has_unconditional_grant(
            make_access([read_only_restriction]), [unconditional]
        )
        is True
    )


def test_write_in_transaction_uses_analyze_for_create_and_index_for_upsert(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeConn:
        def execute(self, *args, **kwargs):
            return SimpleNamespace(first=lambda: None, scalar=lambda: None)

    monkeypatch.setattr(entity_rows.data_sql, "set_write_timeouts", lambda *a, **k: None)
    monkeypatch.setattr(
        entity_rows.data_sql,
        "create_write_stage",
        lambda conn, cols: '"entity_data"."wstage_test"',
    )
    monkeypatch.setattr(entity_rows.data_sql, "copy_write_stage", lambda *a, **k: None)
    monkeypatch.setattr(
        entity_rows.data_sql,
        "analyze_write_stage",
        lambda conn, table: calls.append(("analyze", table)),
    )
    monkeypatch.setattr(
        entity_rows.data_sql,
        "index_write_stage",
        lambda conn, table, key: calls.append(("index", key)),
    )
    monkeypatch.setattr(entity_rows.data_sql, "drop_write_stage", lambda *a, **k: None)
    monkeypatch.setattr(
        entity_rows.data_sql, "write_staged_counts", lambda *a, **k: (1, 0, 0, 0, 0)
    )
    monkeypatch.setattr(entity_rows, "_validate", lambda *a, **k: None)

    target = SimpleNamespace(
        qualified_table='"entity_data"."t"',
        attributes=[
            SimpleNamespace(
                name="sku",
                type="string",
                required=True,
                unique=True,
                business_key=True,
                max_length=32,
                precision=None,
                scale=None,
                dictionary_id=None,
            )
        ],
        head=SimpleNamespace(reference_snapshots={}),
    )
    access = SimpleNamespace()

    entity_rows._write_in_transaction(
        FakeConn(), access, target, "create", "sku", iter([[{"sku": "A"}]]), lambda: 5000
    )
    entity_rows._write_in_transaction(
        FakeConn(), access, target, "upsert", "sku", iter([[{"sku": "A"}]]), lambda: 5000
    )
    assert calls == [
        ("analyze", '"entity_data"."wstage_test"'),
        ("index", "sku"),
    ]
