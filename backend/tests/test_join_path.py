"""Join path BFS tests."""

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
from backend.metadata.joins.graph import find_join_paths  # noqa: E402
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_catalog_store()
    reset_source_store()
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_1",
            key="mes",
            locator_key="src/postgresql/mes",
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


def _table(
    object_id: str,
    name: str,
    columns: list[tuple[str, str]],
) -> CatalogObjectRecord:
    now = utc_now()
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_1",
        locator_key=f"obj/postgresql/mes/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl=None,
        comment=None,
        primary_key=None,
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
        last_structure_job_id=None,
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id=cid,
                object_id=object_id,
                locator_key=f"col/postgresql/mes/public/table/{name}/column/{cname}",
                name=cname,
                ordinal=i,
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
            for i, (cid, cname) in enumerate(columns)
        ],
    )


def test_two_hop_join_path() -> None:
    store = get_catalog_store()
    # A -- B -- C
    a = _table("obj_a", "a", [("col_a_id", "id"), ("col_a_b", "b_id")])
    b = _table("obj_b", "b", [("col_b_id", "id"), ("col_b_c", "c_id")])
    c = _table("obj_c", "c", [("col_c_id", "id")])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[a, b, c],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    store.upsert_join(
        from_column_id="col_a_b",
        to_column_id="col_b_id",
        evidence="fk_ab",
        created_by_user_id=None,
        origin="human",
        join_expression="a.b_id = b.id",
    )
    store.upsert_join(
        from_column_id="col_b_c",
        to_column_id="col_c_id",
        evidence="fk_bc",
        created_by_user_id=None,
        origin="human",
        join_expression="b.c_id = c.id",
    )

    result = find_join_paths(
        store=store,
        start_object_id="obj_a",
        target_object_id="obj_c",
        max_hops=2,
        top_targets=3,
    )
    assert len(result.paths) >= 1
    path = result.paths[0]
    assert len(path.hops) == 2
    assert path.target_object_id == "obj_c"
    assert path.path_summary


def test_direct_joins_for_column_start() -> None:
    store = get_catalog_store()
    a = _table("obj_a", "a", [("col_a_id", "id"), ("col_a_b", "b_id")])
    b = _table("obj_b", "b", [("col_b_id", "id")])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[a, b],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    store.upsert_join(
        from_column_id="col_a_b",
        to_column_id="col_b_id",
        evidence="fk",
        created_by_user_id=None,
        origin="human",
    )
    result = find_join_paths(
        store=store,
        start_column_id="col_a_b",
        max_hops=1,
        top_targets=3,
    )
    assert len(result.direct_joins) == 1
    assert result.direct_joins[0].from_column_id == "col_a_b"
