"""Structure refresh emits a delta plan and does not overwrite semantics."""

from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.pop("DATABASE_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.store import (  # noqa: E402
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_diff import (  # noqa: E402
    StructureDiffFacts,
    empty_counts,
)
from backend.metadata.catalog.structure_merge import (  # noqa: E402
    StructureRefreshPlan,
    build_structure_refresh_plan,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
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
            id="src_1",
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
    data_type: str = "integer",
) -> CatalogColumnRecord:
    return CatalogColumnRecord(
        id=col_id,
        object_id=object_id,
        locator_key=f"col/postgresql/demo/public/table/orders/column/{name}",
        name=name,
        ordinal=1 if name == "id" else 2,
        data_type=data_type,
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


def _table(*, now: datetime, data_type: str = "integer") -> CatalogObjectRecord:
    return CatalogObjectRecord(
        id="obj_orders",
        source_id="src_1",
        locator_key="obj/postgresql/demo/public/table/orders",
        object_type="table",
        schema_name="public",
        name="orders",
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
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[_col("col_id", "obj_orders", "id", now=now, data_type=data_type)],
        foreign_keys=[],
        indexes=[],
    )


def _plan(existing: list[CatalogObjectRecord], incoming: list[CatalogObjectRecord]):
    return build_structure_refresh_plan(
        source_id="src_1",
        job_id="job_refresh",
        existing_objects=existing,
        existing_joins=[],
        incoming=incoming,
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo",
        now=utc_now(),
    )


def test_unchanged_refresh_emits_empty_objects_and_stamps() -> None:
    now = utc_now()
    table = _table(now=now)
    plan = _plan([table], [table])
    assert plan.objects == ()
    assert plan.stamp_object_ids == ("obj_orders",)
    assert plan.diff.diff_class == "unchanged"


def test_no_change_refresh_advances_collected_at() -> None:
    now = utc_now()
    table = _table(now=now)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_seed",
        collected=[table],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    first = get_catalog_store().get_object("obj_orders")
    assert first is not None
    first_collected = first.collected_at
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_refresh",
        collected=[table],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    again = get_catalog_store().get_object("obj_orders")
    assert again is not None
    assert again.collected_at is not None
    assert first_collected is not None
    assert again.collected_at >= first_collected
    assert again.last_structure_job_id == "job_refresh"
    assert again.updated_at == first.updated_at


def test_refresh_keeps_patched_semantics() -> None:
    now = utc_now()
    table = _table(now=now)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_seed",
        collected=[table],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    get_catalog_store().patch_object_semantics(
        "obj_orders",
        business_name="Orders",
        business_semantics_ready=True,
    )
    get_catalog_store().patch_column_semantics(
        "col_id",
        business_name="Order id",
        column_semantics={"role": "pk"},
    )
    changed = _table(now=now, data_type="bigint")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_refresh",
        collected=[changed],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    obj = get_catalog_store().get_object("obj_orders")
    assert obj is not None
    assert obj.business_name == "Orders"
    assert obj.business_semantics_ready is True
    assert obj.columns[0].data_type == "bigint"
    assert obj.columns[0].business_name == "Order id"
    assert obj.columns[0].column_semantics == {"role": "pk"}


def test_stamp_missing_object_id_raises() -> None:
    store = get_catalog_store()
    now = utc_now()
    plan = StructureRefreshPlan(
        source_id="src_1",
        objects=(),
        delete_join_ids=(),
        upsert_joins=(),
        stamp_object_ids=("missing",),
        last_structure_job_id="job_x",
        collected_at=now,
        diff=StructureDiffFacts(
            diff_class="unchanged", counts=empty_counts(), changes=()
        ),
    )
    with pytest.raises(KeyError, match="missing"):
        store._persist_structure_plan_unlocked(plan, now=now)
