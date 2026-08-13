"""Structure Diff classification from existing vs incoming catalog."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.structure_diff import compute_structure_diff


def _now() -> datetime:
    return datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


def _col(
    object_id: str,
    name: str,
    *,
    data_type: str = "integer",
    nullable: bool = False,
    comment: str | None = None,
    default_value: str | None = None,
    is_present: bool = True,
) -> CatalogColumnRecord:
    now = _now()
    return CatalogColumnRecord(
        id=f"col_{object_id}_{name}",
        object_id=object_id,
        locator_key=f"col/postgresql/demo/public/table/{object_id}/column/{name}",
        name=name,
        ordinal=0,
        data_type=data_type,
        nullable=nullable,
        is_present=is_present,
        default_value=default_value,
        comment=comment,
        business_name=None,
        business_description=None,
        column_semantics=None,
        enum_catalog=None,
        semantic_source=None,
        field_kind="column",
        created_at=now,
        updated_at=now,
    )


def _table(
    object_id: str,
    name: str,
    *,
    columns: list[CatalogColumnRecord] | None = None,
    primary_key: list[str] | None = None,
    schema_name: str = "public",
    is_present: bool = True,
    foreign_keys: list[CatalogForeignKeyRecord] | None = None,
    indexes: list[CatalogIndexRecord] | None = None,
) -> CatalogObjectRecord:
    now = _now()
    cols = columns or [_col(object_id, "id")]
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_demo",
        locator_key=f"obj/postgresql/demo/{schema_name}/table/{name}",
        object_type="table",
        schema_name=schema_name,
        name=name,
        ddl=None,
        comment=None,
        primary_key=primary_key if primary_key is not None else ["id"],
        is_present=is_present,
        business_name=None,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=False,
        semantics_updated_at=None,
        last_structure_job_id="job_old",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=cols,
        foreign_keys=foreign_keys or [],
        indexes=indexes or [],
    )


def test_unchanged_when_collect_matches() -> None:
    existing = [_table("obj_a", "orders", columns=[_col("obj_a", "id")])]
    incoming = [_table("obj_new", "orders", columns=[_col("obj_new", "id")])]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "unchanged"
    assert facts.counts["objects_added"] == 0
    assert facts.counts["objects_removed"] == 0


def test_first_collect_is_non_breaking() -> None:
    incoming = [_table("obj_a", "orders")]
    facts = compute_structure_diff(
        existing=[], incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "non_breaking"
    assert facts.counts["objects_added"] == 1
    assert facts.counts["objects_removed"] == 0


def test_removed_column_is_breaking() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "qty")],
        )
    ]
    incoming = [_table("obj_a", "orders", columns=[_col("obj_a", "id")])]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["columns_removed"] == 1
    assert any(c.change == "column_removed" for c in facts.changes)


def test_added_column_is_non_breaking() -> None:
    existing = [_table("obj_a", "orders", columns=[_col("obj_a", "id")])]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "note", data_type="text")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "non_breaking"
    assert facts.counts["columns_added"] == 1


def test_varchar_length_is_type_changed() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "sku", data_type="varchar(50)")],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "sku", data_type="varchar(100)")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["type_changed"] == 1
    assert facts.changes[0].extra == {"from": "varchar(50)", "to": "varchar(100)"}


def test_integer_to_text_is_type_changed() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "qty", data_type="integer")],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "qty", data_type="text")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["type_changed"] == 1


def test_integer_to_bigint_is_type_changed() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "qty", data_type="integer")],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "qty", data_type="bigint")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.counts["type_changed"] == 1
    assert facts.diff_class == "breaking"


def test_same_native_data_type_is_unchanged() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "sku", data_type="varchar(50)")],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "sku", data_type="varchar(50)")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.counts["type_changed"] == 0
    assert facts.diff_class == "unchanged"


def test_nullable_tighten_is_breaking() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "note", data_type="text", nullable=True)],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "note", data_type="text", nullable=False)],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["nullable_tightened"] == 1


def test_pk_change_is_breaking() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "site_id")],
            primary_key=["id"],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "site_id")],
            primary_key=["id", "site_id"],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["pk_changed"] == 1


def test_fk_change_does_not_raise_class() -> None:
    fk = CatalogForeignKeyRecord(
        name="fk_orders_customer",
        columns=["customer_id"],
        ref_schema="public",
        ref_table="customers",
        ref_columns=["id"],
    )
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "customer_id")],
            foreign_keys=[fk],
        )
    ]
    incoming = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "customer_id")],
            foreign_keys=[],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.diff_class == "unchanged"
    assert any(c.change == "fk_removed" for c in facts.changes)


def test_out_of_scope_object_is_not_removed() -> None:
    existing = [
        _table("obj_a", "orders", schema_name="public"),
        _table("obj_b", "legacy", schema_name="other"),
    ]
    incoming = [_table("obj_a", "orders", schema_name="public")]
    facts = compute_structure_diff(
        existing=existing, incoming=incoming, schema_scope="public"
    )
    assert facts.counts["objects_removed"] == 0
    assert facts.diff_class == "unchanged"


def test_removed_object_does_not_count_nested_columns() -> None:
    existing = [
        _table(
            "obj_a",
            "orders",
            columns=[_col("obj_a", "id"), _col("obj_a", "qty")],
        )
    ]
    facts = compute_structure_diff(
        existing=existing, incoming=[], schema_scope="public"
    )
    assert facts.diff_class == "breaking"
    assert facts.counts["objects_removed"] == 1
    assert facts.counts["columns_removed"] == 0
