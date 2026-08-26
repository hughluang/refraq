"""One set of assertions, both CatalogStore adapters.

Default `pytest` exercises Memory only. The SQL parameter needs Compose
Postgres and skips without it, so the fast path stays fast while the
production adapter still has a way to be checked against the same contract.

Divergences found here are recorded, not patched in place: making the two
adapters agree is a behaviour change and belongs in its own commit.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, text

from backend.core.time import utc_now

INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_CATALOG_TABLES = (
    "sources, catalog_objects, catalog_columns, catalog_foreign_keys,"
    " catalog_indexes, catalog_joins, catalog_join_changes, structure_diffs,"
    " business_domains"
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _reset_metadata_singletons() -> None:
    from backend.metadata.business_domains.store import reset_business_domain_store
    from backend.metadata.catalog.store import reset_catalog_store
    from backend.metadata.sources.store import reset_source_store
    from backend.metadata.structure_diffs.store import reset_structure_diff_store

    reset_source_store()
    reset_catalog_store()
    reset_structure_diff_store()
    reset_business_domain_store()


@pytest.fixture(params=["memory", "sql"])
def catalog_store(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """A CatalogStore of each flavour, empty, ready to seed."""
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.metadata.catalog.store import get_catalog_store

    if request.param == "sql":
        if not _postgres_available():
            pytest.skip("Postgres not available (start: docker compose up -d)")
        from backend.core.entry import migrate_with_advisory_lock

        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
        monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
        reset_settings_cache()
        reset_db_singletons()
        migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)
        engine = create_engine(INTEGRATION_DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(
                text(f"TRUNCATE TABLE {_CATALOG_TABLES} RESTART IDENTITY CASCADE")
            )
        engine.dispose()
    else:
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        monkeypatch.setenv("DATABASE_URL", "")
        reset_settings_cache()
        reset_db_singletons()

    _reset_metadata_singletons()
    yield get_catalog_store()
    _reset_metadata_singletons()
    reset_db_singletons()
    reset_settings_cache()


SOURCE_ID = "src_conformance"
SOURCE_KEY = "conformance"


def _seed_source() -> None:
    from backend.metadata.sources.store import SourceRecord, get_source_store

    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=SOURCE_ID,
            key=SOURCE_KEY,
            locator_key=f"src/postgresql/{SOURCE_KEY}",
            name="Conformance",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )


def _object(name: str, *, ready: bool, business_name: str | None, columns: list[str]):
    from backend.metadata.catalog.store import (
        CatalogColumnRecord,
        CatalogObjectRecord,
        new_column_id,
        new_object_id,
    )

    now = utc_now()
    object_id = new_object_id()
    return CatalogObjectRecord(
        id=object_id,
        source_id=SOURCE_ID,
        locator_key=f"obj/postgresql/{SOURCE_KEY}/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl=f"CREATE TABLE {name} ();",
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=business_name,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=ready,
        semantics_updated_at=None,
        last_structure_job_id=None,
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=new_column_id(),
                object_id=object_id,
                locator_key=(
                    f"col/postgresql/{SOURCE_KEY}/public/table/{name}/column/{col}"
                ),
                name=col,
                ordinal=i,
                data_type="integer",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
            for i, col in enumerate(columns)
        ],
        foreign_keys=[],
        indexes=[],
    )


def _seed_catalog() -> None:
    """One Source, three Objects, applied through the real refresh path."""
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
    from backend.metadata.sources.service import require_source

    _seed_source()
    collected = [
        _object(
            "orders",
            ready=True,
            business_name="Order Header",
            columns=["id", "customer_id"],
        ),
        _object("customers", ready=False, business_name=None, columns=["id", "name"]),
        _object(
            "payments", ready=False, business_name="Payment", columns=["id", "order_id"]
        ),
        # Second "order" match so search ranking has something to order.
        _object("order_items", ready=False, business_name=None, columns=["id", "sku"]),
    ]
    apply_structure_snapshot(
        source=require_source(SOURCE_ID),
        job_id=f"job_{uuid.uuid4().hex[:12]}",
        collected=collected,
        schema_scope=None,
        fail_safe_threshold=1.0,
    )


def test_list_objects_filters_agree(catalog_store) -> None:
    _seed_catalog()

    everything, total = catalog_store.list_objects(SOURCE_ID)
    assert total == 4
    assert {o.name for o in everything} == {
        "orders",
        "customers",
        "payments",
        "order_items",
    }

    ready, ready_total = catalog_store.list_objects(
        SOURCE_ID, business_semantics_ready=True
    )
    assert ready_total == 1
    assert ready[0].name == "orders"

    typed, typed_total = catalog_store.list_objects(SOURCE_ID, object_type="table")
    assert typed_total == 4
    assert len(typed) == 4

    missing, missing_total = catalog_store.list_objects(SOURCE_ID, object_type="view")
    assert missing_total == 0
    assert missing == []

    customers = catalog_store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/customers"
    )
    assert customers is not None
    _persist_objects(catalog_store, [replace(customers, is_present=False)])

    present_only, present_total = catalog_store.list_objects(
        SOURCE_ID, include_absent=False
    )
    assert present_total == 3
    assert {o.name for o in present_only} == {"orders", "payments", "order_items"}

    with_tombstones, with_total = catalog_store.list_objects(
        SOURCE_ID, include_absent=True
    )
    assert with_total == 4
    assert {o.name for o in with_tombstones} == {
        "orders",
        "customers",
        "payments",
        "order_items",
    }


def test_list_objects_name_search_agrees(catalog_store) -> None:
    _seed_catalog()

    technical, technical_total = catalog_store.list_objects(
        SOURCE_ID, name_search="order"
    )
    assert technical_total == 2
    assert {o.name for o in technical} == {"orders", "order_items"}

    business, business_total = catalog_store.list_objects(
        SOURCE_ID, name_search="Payment"
    )
    assert business_total == 1
    assert business[0].name == "payments"

    nothing, nothing_total = catalog_store.list_objects(SOURCE_ID, name_search="zzz")
    assert nothing_total == 0
    assert nothing == []


def test_list_objects_name_search_treats_percent_and_underscore_as_literal(
    catalog_store,
) -> None:
    """User input is a literal substring, not a SQL LIKE pattern.

    SQL escapes ``%`` / ``_``; Memory uses Python ``in``. Both must agree.
    """
    _seed_catalog()
    now = utc_now()
    wild = _object("has%pct", ready=False, business_name=None, columns=["id"])
    under = _object("has_us", ready=False, business_name=None, columns=["id"])
    _persist_objects(
        catalog_store,
        [
            replace(wild, created_at=now, updated_at=now, collected_at=now),
            replace(under, created_at=now, updated_at=now, collected_at=now),
        ],
    )

    percent, percent_total = catalog_store.list_objects(SOURCE_ID, name_search="has%")
    assert percent_total == 1
    assert percent[0].name == "has%pct"

    underscore, underscore_total = catalog_store.list_objects(
        SOURCE_ID, name_search="has_"
    )
    assert underscore_total == 1
    assert underscore[0].name == "has_us"


def test_list_objects_paging_agrees(catalog_store) -> None:
    _seed_catalog()

    first, total = catalog_store.list_objects(SOURCE_ID, limit=3, offset=0)
    second, total_again = catalog_store.list_objects(SOURCE_ID, limit=3, offset=3)

    assert total == total_again == 4
    assert len(first) == 3
    assert len(second) == 1
    # total is the unpaged count, and pages must not overlap.
    assert {o.id for o in first}.isdisjoint({o.id for o in second})


def test_search_objects_and_columns_agree(catalog_store) -> None:
    _seed_catalog()

    # Result order is part of the contract, so it is asserted exactly. These
    # two names rank equally and fall back to the name tiebreak.
    objects, object_total = catalog_store.search_objects("order", source_id=SOURCE_ID)
    assert object_total == 2
    assert [o.name for o in objects] == ["order_items", "orders"]

    columns, column_total = catalog_store.search_columns(
        "customer_id", source_id=SOURCE_ID
    )
    assert column_total == 1
    assert columns[0].name == "customer_id"

    # Deliberately not an ordered assertion: the sort key ends in the record
    # id, which is a random uuid, so equally-ranked same-name columns have no
    # stable order to compare between adapters. Content parity is the contract.
    same_name, same_name_total = catalog_store.search_columns("id", source_id=SOURCE_ID)
    assert same_name_total == 6
    assert sorted(c.name for c in same_name) == [
        "customer_id",
        "id",
        "id",
        "id",
        "id",
        "order_id",
    ]

    paged, paged_total = catalog_store.search_objects(
        "order", source_id=SOURCE_ID, limit=1, offset=0
    )
    assert paged_total == 2
    assert len(paged) == 1
    assert paged[0].name == "order_items"


def _owning_object_id(store, column_id: str) -> str:
    column = store.get_column(column_id)
    assert column is not None
    return column.object_id


def _column_ids(store) -> tuple[str, str]:
    orders = store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/orders"
    )
    payments = store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/payments"
    )
    assert orders is not None and payments is not None
    from_col = next(c for c in orders.columns if c.name == "id")
    to_col = next(c for c in payments.columns if c.name == "order_id")
    return from_col.id, to_col.id


def test_join_lifecycle_and_change_log_agree(catalog_store) -> None:
    from backend.metadata.catalog.join_origin import HUMAN_JOIN_ORIGIN

    _seed_catalog()
    from_id, to_id = _column_ids(catalog_store)

    join = catalog_store.write_insert_join(
        from_column_id=from_id,
        to_column_id=to_id,
        evidence="probe query",
        created_by_user_id="user_1",
        attester=HUMAN_JOIN_ORIGIN,
    ).record
    assert join.is_rejected is False

    found = catalog_store.get_join_by_pair(from_id, to_id)
    assert found is not None and found.id == join.id

    for_object, object_total = catalog_store.list_joins_for_object(
        _owning_object_id(catalog_store, from_id)
    )
    assert object_total >= 1
    assert any(j.id == join.id for j in for_object)

    amended = catalog_store.update_join(
        join.id,
        evidence="amended probe",
        join_kind="LEFT",
        join_expression="id = order_id",
        actor_user_id="user_1",
    )
    assert amended is not None
    assert amended.evidence == "amended probe"
    assert amended.join_kind == "LEFT"

    catalog_store.set_join_rejection(
        join.id,
        rejected_at=utc_now(),
        rejected_by_user_id="user_1",
        actor_user_id="user_1",
    )
    rejected = catalog_store.get_join(join.id)
    assert rejected is not None and rejected.is_rejected is True

    # Join Change is the audit trail both adapters must append to identically
    # (ADR 0030 / 0031): create, amend, then rejection.
    changes = catalog_store.list_join_changes(
        from_column_id=from_id, to_column_id=to_id
    )
    assert [c.kind for c in changes] == ["create", "amend", "reject"]
    assert changes[0].attester == HUMAN_JOIN_ORIGIN
    assert changes[1].actor_user_id == "user_1"

    assert catalog_store.delete_join(join.id) is True
    assert catalog_store.get_join(join.id) is None


def _seed_domain() -> str:
    from backend.metadata.business_domains.store import (
        BusinessDomainRecord,
        get_business_domain_store,
        new_business_domain_id,
    )

    now = utc_now()
    record = BusinessDomainRecord(
        id=new_business_domain_id(),
        code="sales",
        name="Sales",
        description=None,
        created_at=now,
        updated_at=now,
    )
    get_business_domain_store().create(record)
    return record.id


def test_semantics_patch_agrees(catalog_store) -> None:
    _seed_catalog()
    orders = catalog_store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/orders"
    )
    assert orders is not None

    patched = catalog_store.patch_object_semantics(
        orders.id,
        business_name="Sales Order",
        grain_description="one row per order",
    )
    assert patched is not None
    assert patched.business_name == "Sales Order"
    assert patched.grain_description == "one row per order"
    # Untouched fields survive a partial patch (UNSET is not "clear").
    assert patched.business_semantics_ready is True

    column = next(c for c in orders.columns if c.name == "id")
    patched_column = catalog_store.patch_column_semantics(
        column.id,
        business_name="Order id",
        column_semantics={"role": "pk"},
    )
    assert patched_column is not None
    assert patched_column.business_name == "Order id"
    assert patched_column.column_semantics == {"role": "pk"}


def test_business_domain_ref_count_agrees(catalog_store) -> None:
    """Domain reference counting follows catalog_objects.business_domain_id.

    SQL always counted the FK column. Memory used to keep a sidecar map that
    only `patch_object_semantics` wrote, so `delete_objects_for_source` left a
    stale count of 1. Both adapters now read the catalog objects themselves.
    """
    _seed_catalog()
    domain_id = _seed_domain()
    orders = catalog_store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/orders"
    )
    assert orders is not None

    catalog_store.patch_object_semantics(orders.id, business_domain_id=domain_id)
    assert catalog_store.count_objects_for_domain(domain_id) == 1

    catalog_store.delete_objects_for_source(SOURCE_ID)
    assert catalog_store.list_objects(SOURCE_ID)[1] == 0
    assert catalog_store.count_objects_for_domain(domain_id) == 0


def _empty_diff():
    from backend.metadata.catalog.structure_diff import StructureDiffFacts, empty_counts

    return StructureDiffFacts(
        diff_class="unchanged", counts=empty_counts(), changes=()
    )


def _persist_objects(store, objects) -> None:
    from backend.metadata.catalog.structure_merge import StructureRefreshPlan

    now = utc_now()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    plan = StructureRefreshPlan(
        source_id=SOURCE_ID,
        objects=tuple(objects),
        upsert_joins=(),
        stamp_object_ids=(),
        last_structure_job_id=job_id,
        collected_at=now,
        diff=_empty_diff(),
    )
    with store.catalog_write(SOURCE_ID) as write:
        write.persist_plan(plan)


def test_persist_plan_writes_objects_stamps_and_inserts_missing_joins(
    catalog_store,
) -> None:
    from backend.metadata.catalog.join_origin import STRUCTURE_JOIN_ORIGIN
    from backend.metadata.catalog.structure_merge import (
        StructureJoinUpsert,
        StructureRefreshPlan,
    )

    _seed_catalog()
    from_id, to_id = _column_ids(catalog_store)
    orders = catalog_store.get_object_by_locator(
        f"obj/postgresql/{SOURCE_KEY}/public/table/orders"
    )
    assert orders is not None
    now = utc_now()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    plan = StructureRefreshPlan(
        source_id=SOURCE_ID,
        objects=(orders,),
        upsert_joins=(
            StructureJoinUpsert(
                from_column_id=from_id,
                to_column_id=to_id,
                evidence="fk orders.id -> payments.order_id",
                join_expression="id = order_id",
            ),
        ),
        stamp_object_ids=(orders.id,),
        last_structure_job_id=job_id,
        collected_at=now,
        diff=_empty_diff(),
    )
    with catalog_store.catalog_write(SOURCE_ID) as write:
        baseline, _joins = write.load_baseline()
        assert any(o.id == orders.id for o in baseline)
        write.persist_plan(plan)

    stamped = catalog_store.get_object(orders.id)
    assert stamped is not None
    assert stamped.last_structure_job_id == job_id
    found = catalog_store.get_join_by_pair(from_id, to_id)
    assert found is not None
    changes = catalog_store.list_join_changes(
        from_column_id=from_id, to_column_id=to_id
    )
    assert [c.kind for c in changes] == ["create"]
    assert changes[0].attester == STRUCTURE_JOIN_ORIGIN

    with catalog_store.catalog_write(SOURCE_ID) as write:
        write.persist_plan(plan)
    changes_again = catalog_store.list_join_changes(
        from_column_id=from_id, to_column_id=to_id
    )
    assert [c.kind for c in changes_again] == ["create"]


def test_persist_join_detection_plan_counts_inserts(catalog_store) -> None:
    from backend.metadata.catalog.join_origin import SQL_LINEAGE_JOIN_ORIGIN
    from backend.metadata.join_detection_jobs.reconcile import (
        JoinDetectionPlan,
        JoinDetectionUpsert,
    )

    _seed_catalog()
    from_id, to_id = _column_ids(catalog_store)
    plan = JoinDetectionPlan(
        upsert_joins=(
            JoinDetectionUpsert(
                from_column_id=from_id,
                to_column_id=to_id,
                evidence="SQL join in view: id = order_id",
                join_expression="id = order_id",
                join_kind="INNER",
            ),
        ),
        skipped_protected=0,
        skipped_rejected=0,
    )
    with catalog_store.catalog_write(SOURCE_ID) as write:
        inserted = write.persist_join_detection_plan(plan)
    assert inserted == 1
    changes = catalog_store.list_join_changes(
        from_column_id=from_id, to_column_id=to_id
    )
    assert [c.kind for c in changes] == ["create"]
    assert changes[0].attester == SQL_LINEAGE_JOIN_ORIGIN

    with catalog_store.catalog_write(SOURCE_ID) as write:
        inserted_again = write.persist_join_detection_plan(plan)
    assert inserted_again == 0
    assert (
        len(
            catalog_store.list_join_changes(
                from_column_id=from_id, to_column_id=to_id
            )
        )
        == 1
    )


def test_catalog_write_rolls_back_on_exception(catalog_store) -> None:
    _seed_catalog()
    extra = _object("rollback_probe", ready=False, business_name=None, columns=["id"])
    _, total_before = catalog_store.list_objects(SOURCE_ID)
    assert total_before == 4

    with pytest.raises(RuntimeError, match="persist aborted"):
        with catalog_store.catalog_write(SOURCE_ID) as write:
            from backend.metadata.catalog.structure_merge import StructureRefreshPlan

            write.persist_plan(
                StructureRefreshPlan(
                    source_id=SOURCE_ID,
                    objects=(extra,),
                    upsert_joins=(),
                    stamp_object_ids=(),
                    last_structure_job_id="job_abort",
                    collected_at=utc_now(),
                    diff=_empty_diff(),
                )
            )
            raise RuntimeError("persist aborted")

    names = {o.name for o in catalog_store.list_objects(SOURCE_ID)[0]}
    assert extra.name not in names
    assert catalog_store.list_objects(SOURCE_ID)[1] == total_before


def test_recompute_locators_for_source_agrees(catalog_store) -> None:
    _seed_catalog()
    changed = catalog_store.recompute_locators_for_source(
        SOURCE_ID,
        engine="postgresql",
        kind="database",
        source_key="renamed",
    )
    assert changed > 0
    relocated = catalog_store.get_object_by_locator(
        "obj/postgresql/renamed/public/table/orders"
    )
    assert relocated is not None
    assert relocated.name == "orders"
    for col in relocated.columns:
        assert "/renamed/" in col.locator_key
    assert (
        catalog_store.get_object_by_locator(
            f"obj/postgresql/{SOURCE_KEY}/public/table/orders"
        )
        is None
    )
