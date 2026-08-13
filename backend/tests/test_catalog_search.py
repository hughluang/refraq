"""Catalog search ranking tests (memory store)."""

from __future__ import annotations

from backend.core.time import utc_now
import os
from datetime import datetime

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.pop("DATABASE_URL", None)

from backend.core.config import reset_settings_cache  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_catalog_store()
    reset_source_store()
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_1",
            key="mes-prod",
            locator_key="src/postgresql/mes-prod",
            name="MES",
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


def _obj(
    *,
    object_id: str,
    name: str,
    schema: str = "public",
    business_name: str | None = None,
    business_description: str | None = None,
    locator: str | None = None,
) -> CatalogObjectRecord:
    now = utc_now()
    loc = locator or f"obj/postgresql/mes-prod/{schema}/table/{name}"
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_1",
        locator_key=loc,
        object_type="table",
        schema_name=schema,
        name=name,
        ddl=None,
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=business_name,
        business_description=business_description,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=False,
        semantics_updated_at=None,
        last_structure_job_id=None,
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=f"col_{object_id}",
                object_id=object_id,
                locator_key=f"col/postgresql/mes-prod/{schema}/table/{name}/column/id",
                name="id",
                ordinal=0,
                data_type="int",
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


def test_search_objects_ranking_exact_prefix_substring_business() -> None:
    store = get_catalog_store()
    apply_structure_snapshot(
        source_id="src_1",
        job_id="j1",
        collected=[
            _obj(object_id="obj_exact", name="work_order"),
            _obj(object_id="obj_prefix", name="work_order_line"),
            _obj(object_id="obj_sub", name="x_work_order_y"),
            _obj(
                object_id="obj_biz",
                name="wo_hdr",
                business_name="contains work_order label",
                business_description="MES header",
            ),
        ],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
    )
    # Seed business fields (structure insert keeps incoming business_*).
    items, total = store.search_objects("work_order", limit=10, offset=0)
    assert total == 4
    ids = [o.id for o in items]
    assert ids[0] == "obj_exact"
    assert ids[1] == "obj_prefix"
    assert "obj_sub" in ids
    assert "obj_biz" in ids
    assert ids.index("obj_sub") < ids.index("obj_biz")


def test_search_columns_name_and_business() -> None:
    store = get_catalog_store()
    now = utc_now()
    obj = _obj(object_id="obj_c", name="orders")
    obj.columns = [
        CatalogColumnRecord(
            id="col_wo",
            object_id="obj_c",
            locator_key="col/postgresql/mes-prod/public/table/orders/column/wo_id",
            name="wo_id",
            ordinal=0,
            data_type="int",
            nullable=False,
            is_present=True,
            default_value=None,
            comment=None,
            business_name="Work Order Id",
            business_description=None,
            column_semantics=None,
            enum_catalog=None,
            semantic_source=None,
            field_kind="column",
            created_at=now,
            updated_at=now,
        ),
        CatalogColumnRecord(
            id="col_other",
            object_id="obj_c",
            locator_key="col/postgresql/mes-prod/public/table/orders/column/qty",
            name="qty",
            ordinal=1,
            data_type="int",
            nullable=True,
            is_present=True,
            default_value=None,
            comment=None,
            business_name=None,
            business_description="line quantity",
            column_semantics=None,
            enum_catalog=None,
            semantic_source=None,
            field_kind="column",
            created_at=now,
            updated_at=now,
        ),
    ]
    apply_structure_snapshot(
        source_id="src_1",
        job_id="j1",
        collected=[obj],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
    )
    items, total = store.search_columns("wo_id", limit=10, offset=0)
    assert total >= 1
    assert items[0].id == "col_wo"

    biz, biz_total = store.search_columns("line quantity", limit=10, offset=0)
    assert biz_total == 1
    assert biz[0].id == "col_other"
