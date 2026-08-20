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
from backend.metadata.structure_diffs.store import (  # noqa: E402
    get_structure_diff_store,
    reset_structure_diff_store,
)


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_catalog_store()
    reset_source_store()
    reset_structure_diff_store()
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


def test_apply_persists_structure_diff() -> None:
    now = utc_now()
    table = _table(now=now)
    commit = apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_seed",
        collected=[table],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    assert commit.facts.diff_class == "non_breaking"
    assert commit.structure_diff_id
    envelope = commit.result_envelope()
    assert envelope["schema"] == "structure.diff.v1"
    assert envelope["structure_diff_id"] == commit.structure_diff_id
    diffs, total = get_structure_diff_store().list_for_source("src_1")
    assert total == 1
    assert diffs[0].id == commit.structure_diff_id
    assert diffs[0].job_id == "job_seed"


def test_fail_safe_apply_persists_no_structure_diff() -> None:
    from backend.metadata.catalog.store import CatalogWriteAborted

    now = utc_now()
    tables = [
        CatalogObjectRecord(
            id=f"obj_t{i}",
            source_id="src_1",
            locator_key=f"obj/postgresql/demo/public/table/t{i}",
            object_type="table",
            schema_name="public",
            name=f"t{i}",
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
            columns=[
                CatalogColumnRecord(
                    id=f"col_t{i}_id",
                    object_id=f"obj_t{i}",
                    locator_key=(
                        f"col/postgresql/demo/public/table/t{i}/column/id"
                    ),
                    name="id",
                    ordinal=1,
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
            ],
        )
        for i in range(4)
    ]
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="job_seed",
        collected=tables,
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    seed_diffs, seed_total = get_structure_diff_store().list_for_source("src_1")
    assert seed_total == 1
    with pytest.raises(CatalogWriteAborted) as exc:
        apply_structure_snapshot(
            source=require_source("src_1"),
            job_id="job_bad",
            collected=[tables[0]],
            schema_scope=None,
            fail_safe_threshold=0.5,
        )
    assert exc.value.code == "JOB_FAIL_SAFE"
    diffs, total = get_structure_diff_store().list_for_source("src_1")
    assert total == seed_total
    assert [d.job_id for d in diffs] == [d.job_id for d in seed_diffs]
    assert not any(d.job_id == "job_bad" for d in diffs)


def test_diff_persist_failure_leaves_catalog_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utc_now()
    table = _table(now=now)

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("diff persist failed")

    monkeypatch.setattr(
        "backend.metadata.catalog.structure_refresh.persist_structure_diff",
        _boom,
    )
    with pytest.raises(RuntimeError, match="diff persist failed"):
        apply_structure_snapshot(
            source=require_source("src_1"),
            job_id="job_fail",
            collected=[table],
            schema_scope=None,
            fail_safe_threshold=1.0,
        )
    assert get_catalog_store().get_object("obj_orders") is None
    diffs, total = get_structure_diff_store().list_for_source("src_1")
    assert total == 0
    assert diffs == []


def test_diff_create_then_raise_rolls_back_catalog_and_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory Diff is a separate dict; create-then-raise must undo both sides."""
    from backend.metadata.structure_diffs.store import (
        StructureDiffRecord,
        new_structure_diff_id,
    )

    now = utc_now()
    store = get_structure_diff_store()
    # Many older Diffs must not block job_id compensation (no page scan).
    for i in range(250):
        store.create(
            StructureDiffRecord(
                id=new_structure_diff_id(),
                source_id="src_1",
                job_id=f"job_hist_{i}",
                diff_class="unchanged",
                counts=empty_counts(),
                changes=[],
                created_at=now,
            )
        )
    table = _table(now=now)
    real_create = store.create

    def _create_then_raise(record: StructureDiffRecord, *, session=None):  # noqa: ANN001
        real_create(record, session=session)
        raise RuntimeError("diff create after-write failure")

    monkeypatch.setattr(store, "create", _create_then_raise)
    with pytest.raises(RuntimeError, match="diff create after-write failure"):
        apply_structure_snapshot(
            source=require_source("src_1"),
            job_id="job_partial",
            collected=[table],
            schema_scope=None,
            fail_safe_threshold=1.0,
        )
    assert get_catalog_store().get_object("obj_orders") is None
    diffs, total = store.list_for_source("src_1", limit=300)
    assert total == 250
    assert not any(d.job_id == "job_partial" for d in diffs)
    assert store.delete_for_job("job_partial") == 0
