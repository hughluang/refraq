"""Structure refresh Join Origin protection (C1)."""

from __future__ import annotations

from backend.core.time import utc_now
import os
from datetime import datetime

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.pop("DATABASE_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.store import (  # noqa: E402
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.catalog.structure_merge import (  # noqa: E402
    build_structure_refresh_plan,
)
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_catalog_store()
    reset_source_store()
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_origin",
            key="demo",
            locator_key="src/postgresql/demo",
            name="Demo",
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


def _col(
    col_id: str,
    object_id: str,
    name: str,
    *,
    now: datetime,
) -> CatalogColumnRecord:
    return CatalogColumnRecord(
        id=col_id,
        object_id=object_id,
        locator_key=f"col/{object_id}/{name}",
        name=name,
        ordinal=0 if name == "id" else 1,
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


def _table(
    *,
    object_id: str,
    name: str,
    columns: list[tuple[str, str]],
    foreign_keys: list[CatalogForeignKeyRecord] | None = None,
    now: datetime | None = None,
) -> CatalogObjectRecord:
    stamp = now or utc_now()
    cols = [_col(cid, object_id, cname, now=stamp) for cid, cname in columns]
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_origin",
        locator_key=f"obj/postgresql/demo/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl=None,
        comment=None,
        primary_key=["id"],
        is_present=True,
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
        last_structure_job_id="job_seed",
        collected_at=stamp,
        created_at=stamp,
        updated_at=stamp,
        columns=cols,
        foreign_keys=list(foreign_keys or []),
        indexes=[],
    )


def test_plan_skips_protected_human_join() -> None:
    now = utc_now()
    customers = _table(
        object_id="obj_customers",
        name="customers",
        columns=[("col_cust_id", "id")],
        now=now,
    )
    orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_cust_fk", "customer_id")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_orders_customer",
                columns=["customer_id"],
                ref_schema="public",
                ref_table="customers",
                ref_columns=["id"],
            )
        ],
        now=now,
    )
    human_join = CatalogJoinRecord(
        id="join_human_1",
        from_column_id="col_cust_fk",
        to_column_id="col_cust_id",
        evidence="manual",
        join_kind="INNER",
        join_expression="customer_id = id",
        origin="human",
        created_by_user_id="u1",
        created_at=now,
    )
    plan = build_structure_refresh_plan(
        source_id="src_origin",
        job_id="job_refresh",
        existing_objects=[customers, orders],
        existing_joins=[human_join],
        incoming=[customers, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo",
        now=now,
    )
    assert plan.delete_join_ids == ()
    assert plan.upsert_joins == ()


def test_apply_preserves_human_join_via_store() -> None:
    store = get_catalog_store()
    now = utc_now()
    customers = _table(
        object_id="obj_customers",
        name="customers",
        columns=[("col_cust_id", "id")],
        now=now,
    )
    orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_cust_fk", "customer_id")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_orders_customer",
                columns=["customer_id"],
                ref_schema="public",
                ref_table="customers",
                ref_columns=["id"],
            )
        ],
        now=now,
    )
    # Seed without FK first so we can plant a human join on the pair.
    bare_orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_cust_fk", "customer_id")],
        now=now,
    )
    apply_structure_snapshot(
        source=require_source("src_origin"),
        job_id="job_seed",
        collected=[customers, bare_orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    human = store.upsert_join(
        from_column_id="col_cust_fk",
        to_column_id="col_cust_id",
        evidence="analyst confirmed",
        created_by_user_id="u1",
        origin="human",
    )
    assert human.origin == "human"

    apply_structure_snapshot(
        source=require_source("src_origin"),
        job_id="job_refresh",
        collected=[customers, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    joins, _ = store.list_joins_for_object("obj_orders")
    assert len(joins) == 1
    assert joins[0].id == human.id
    assert joins[0].origin == "human"
    assert joins[0].evidence == "analyst confirmed"


def test_service_foreign_key_upsert_keeps_human_join() -> None:
    from backend.metadata.catalog import join_writes as catalog_joins

    store = get_catalog_store()
    now = utc_now()
    customers = _table(
        object_id="obj_customers",
        name="customers",
        columns=[("col_cust_id", "id")],
        now=now,
    )
    orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_cust_fk", "customer_id")],
        now=now,
    )
    apply_structure_snapshot(
        source=require_source("src_origin"),
        job_id="job_seed",
        collected=[customers, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    human = catalog_joins.upsert_join(
        from_column_id="col_cust_fk",
        to_column_id="col_cust_id",
        evidence="analyst confirmed",
        actor_user_id="u1",
        actor_token_id=None,
        origin="human",
    )
    kept = catalog_joins.upsert_join(
        from_column_id="col_cust_fk",
        to_column_id="col_cust_id",
        evidence="FK fk_orders_customer",
        actor_user_id=None,
        actor_token_id=None,
        origin="foreign_key",
    )
    assert kept.id == human.id
    assert kept.origin == "human"
    assert kept.evidence == "analyst confirmed"
