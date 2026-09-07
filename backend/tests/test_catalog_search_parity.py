"""SQL Catalog Search matches the memory adapter on a locale-stable fixture."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from backend.core.time import utc_now
from backend.metadata.catalog.records import CatalogColumnRecord, CatalogObjectRecord
from backend.metadata.catalog.search_rank import rank_and_page, _search_rank

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
    " business_domains, catalog_embeddings"
)

SOURCE_ID = "src_parity"
CJK_ORDER = "\u8ba2\u5355"
CJK_TIE_BA = "\u516b\u53f7"
CJK_TIE_A = "\u554a\u53f7"
CJK_TIE_QUERY = "\u53f7"


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _now():
    return utc_now()


def _column(object_id: str, name: str, **kwargs: object) -> CatalogColumnRecord:
    now = _now()
    return CatalogColumnRecord(
        id=f"col_{object_id}_{name}",
        object_id=object_id,
        locator_key=f"col/postgresql/parity/public/table/{object_id}/column/{name}",
        name=name,
        ordinal=0,
        data_type="text",
        nullable=True,
        is_present=True,
        default_value=None,
        comment=None,
        business_name=kwargs.get("business_name"),  # type: ignore[arg-type]
        business_description=kwargs.get("business_description"),  # type: ignore[arg-type]
        column_semantics=None,
        enum_catalog=None,
        semantic_source=None,
        field_kind="column",
        created_at=now,
        updated_at=now,
    )


def _obj(
    object_id: str,
    name: str,
    *,
    schema: str = "public",
    business_name: str | None = None,
    business_description: str | None = None,
    columns: list[CatalogColumnRecord] | None = None,
    source_id: str = SOURCE_ID,
    object_type: str = "table",
) -> CatalogObjectRecord:
    now = _now()
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/postgresql/parity/{schema or '_'}/{object_type}/{name}",
        object_type=object_type,
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
        columns=columns
        or [
            _column(object_id, "id"),
        ],
        foreign_keys=[],
        indexes=[],
    )


def _fixture_objects() -> list[CatalogObjectRecord]:
    return [
        _obj("obj_exact", "work_order"),
        _obj("obj_prefix", "work_order_line"),
        _obj("obj_sub", "x_work_order_y"),
        _obj(
            "obj_biz",
            "wo_hdr",
            business_name="contains work_order label",
            business_description="MES header",
        ),
        _obj("obj_cjk", CJK_ORDER),
        _obj("obj_cjk_ba", CJK_TIE_BA),
        _obj("obj_cjk_a", CJK_TIE_A),
        _obj("obj_pct", "qty_100%_off"),
        _obj("obj_pct_x", "qty_100X_off"),
        _obj("obj_us", "a_b"),
        _obj("obj_axb", "axb"),
        _obj("obj_empty_schema", "orphan_table", schema=""),
        _obj("obj_empty_biz", "plain", business_name="", business_description=""),
        _obj(
            "obj_colhost",
            "orders",
            columns=[
                _column("obj_colhost", "wo_id"),
                _column(
                    "obj_colhost",
                    "qty",
                    business_name="line quantity",
                    business_description="units",
                ),
                _column("obj_colhost", "pct_100%"),
            ],
        ),
    ]


def _create_source(source_id: str, key: str) -> None:
    from backend.metadata.sources.store import SourceRecord, get_source_store

    now = _now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=key,
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


def _seed(store, objects: list[CatalogObjectRecord]) -> None:
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
    from backend.metadata.sources.service import require_source

    _create_source(SOURCE_ID, "parity")
    apply_structure_snapshot(
        source=require_source(SOURCE_ID),
        job_id="j_parity",
        collected=objects,
        schema_scope=None,
    )
    # Structure insert keeps business_* from collected rows.
    del store  # store is get_catalog_store() after seed


def _search_all(store, objects: list[CatalogObjectRecord]):
    queries = [
        "work_order",
        CJK_ORDER,
        CJK_TIE_QUERY,
        "100%",
        "a_b",
        "orphan_table",
        "plain",
        "wo_id",
        "line quantity",
        "pct_100%",
        "no_such_token",
    ]
    out: dict[str, object] = {}
    for q in queries:
        items, total = store.search_objects(q, source_id=SOURCE_ID, limit=50, offset=0)
        out[f"obj:{q}"] = ([o.id for o in items], total)
        cols, ctotal = store.search_columns(q, source_id=SOURCE_ID, limit=50, offset=0)
        out[f"col:{q}"] = ([c.id for c in cols], ctotal)
    # Python spec on the same fixture (objects + nested columns).
    spec_obj, spec_obj_total = rank_and_page(
        objects,
        rank_of=lambda o: _search_rank(
            "work_order",
            locator_key=o.locator_key,
            name=o.name,
            schema_name=o.schema_name,
            business_name=o.business_name,
            business_description=o.business_description,
        ),
        tiebreak=lambda o: (o.schema_name, o.name, o.id),
        limit=50,
        offset=0,
    )
    out["spec:work_order"] = ([o.id for o in spec_obj], spec_obj_total)
    return out


def _activate(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.metadata.business_domains.store import reset_business_domain_store
    from backend.metadata.catalog.store import reset_catalog_store
    from backend.metadata.sources.store import reset_source_store
    from backend.metadata.structure_diffs.store import reset_structure_diff_store

    if backend == "sql":
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
        monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
        reset_settings_cache()
        reset_db_singletons()
        from backend.core.entry import migrate_with_advisory_lock

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
    reset_source_store()
    reset_catalog_store()
    reset_structure_diff_store()
    reset_business_domain_store()


def test_memory_search_matches_python_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    objects = _fixture_objects()
    _activate(monkeypatch, "memory")
    store = get_catalog_store()
    _seed(store, objects)
    store = get_catalog_store()
    result = _search_all(store, objects)
    ids, total = result["obj:work_order"]  # type: ignore[misc]
    assert total == 4
    assert ids[0] == "obj_exact"
    assert ids[1] == "obj_prefix"
    assert result["spec:work_order"][0] == ids
    assert result[f"obj:{CJK_ORDER}"][0] == ["obj_cjk"]
    assert result[f"obj:{CJK_TIE_QUERY}"][0] == ["obj_cjk_ba", "obj_cjk_a"]
    assert "obj_pct" in result["obj:100%"][0]
    assert "obj_pct_x" not in result["obj:100%"][0]
    assert result["obj:a_b"][0][0] == "obj_us"
    assert "obj_axb" not in result["obj:a_b"][0]
    assert "obj_empty_schema" in result["obj:orphan_table"][0]
    assert result["col:wo_id"][1] >= 1
    assert result["col:line quantity"][1] >= 1


@pytest.mark.skipif(not _postgres_available(), reason="Postgres not available")
def test_sql_search_matches_memory_locale_stable_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    objects = _fixture_objects()
    _activate(monkeypatch, "memory")
    store = get_catalog_store()
    _seed(store, _fixture_objects())
    memory = _search_all(get_catalog_store(), objects)

    _activate(monkeypatch, "sql")
    store = get_catalog_store()
    _seed(store, _fixture_objects())
    sql = _search_all(get_catalog_store(), objects)
    assert sql == memory


def _seed_neighbor_fixture(store) -> list[str]:
    from backend.metadata.catalog.embedding import CatalogEmbeddingRecord

    now = _now()
    rows = [
        ("obj_near", [1.0, 0.0], 1),
        ("obj_mid", [0.8, 0.6], 1),
        ("obj_tie_p", [0.6, 0.8], 1),
        ("obj_tie_q", [0.6, 0.8], 1),
        ("obj_zero", [0.0, 0.0], 1),
        ("obj_neg", [-1.0, 0.0], 1),
        ("obj_dim", [1.0, 0.0, 0.0], 1),
        ("obj_old", [1.0, 0.0], 0),
    ]
    for target_id, vec, generation in rows:
        store.upsert_embedding(
            CatalogEmbeddingRecord(
                id=f"emb_{target_id}",
                kind="object",
                target_id=target_id,
                locator_key=f"loc/{target_id}",
                content_hash="parity",
                embedding=vec,
                indexed_at=now,
                generation=generation,
            )
        )
    return store.nearest_embeddings(
        kind="object",
        query=[1.0, 0.0],
        limit=10,
        generation=1,
    )


def test_memory_nearest_embeddings_matches_cosine_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    _activate(monkeypatch, "memory")
    ids = _seed_neighbor_fixture(get_catalog_store())
    assert ids == ["obj_near", "obj_mid", "obj_tie_p", "obj_tie_q"]


@pytest.mark.skipif(not _postgres_available(), reason="Postgres not available")
def test_sql_nearest_embeddings_matches_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    _activate(monkeypatch, "memory")
    memory = _seed_neighbor_fixture(get_catalog_store())
    _activate(monkeypatch, "sql")
    sql = _seed_neighbor_fixture(get_catalog_store())
    assert sql == memory
    assert sql == ["obj_near", "obj_mid", "obj_tie_p", "obj_tie_q"]


FILTER_SRC_A = "src_filt_a"
FILTER_SRC_B = "src_filt_b"


def _seed_filtered_neighbor_fixture(store) -> dict[str, list[str]]:
    from backend.metadata.catalog.embedding import CatalogEmbeddingRecord
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
    from backend.metadata.sources.service import require_source

    _create_source(FILTER_SRC_A, "filt-a")
    _create_source(FILTER_SRC_B, "filt-b")
    apply_structure_snapshot(
        source=require_source(FILTER_SRC_A),
        job_id="j_filt_a",
        collected=[
            _obj(
                "obj_a_tbl",
                "alpha_tbl",
                source_id=FILTER_SRC_A,
                object_type="table",
            ),
            _obj(
                "obj_a_view",
                "alpha_view",
                source_id=FILTER_SRC_A,
                object_type="view",
            ),
        ],
        schema_scope=None,
    )
    apply_structure_snapshot(
        source=require_source(FILTER_SRC_B),
        job_id="j_filt_b",
        collected=[
            _obj(
                "obj_b_tbl",
                "beta_tbl",
                source_id=FILTER_SRC_B,
                object_type="table",
            ),
        ],
        schema_scope=None,
    )
    now = _now()
    object_rows = [
        ("obj_a_tbl", [1.0, 0.0]),
        ("obj_b_tbl", [0.8, 0.6]),
        ("obj_a_view", [0.6, 0.8]),
    ]
    for target_id, vec in object_rows:
        store.upsert_embedding(
            CatalogEmbeddingRecord(
                id=f"emb_{target_id}",
                kind="object",
                target_id=target_id,
                locator_key=f"loc/{target_id}",
                content_hash="parity-filter",
                embedding=vec,
                indexed_at=now,
                generation=1,
            )
        )
    column_rows = [
        ("col_obj_a_tbl_id", [1.0, 0.0]),
        ("col_obj_b_tbl_id", [0.8, 0.6]),
        ("col_obj_a_view_id", [0.6, 0.8]),
    ]
    for target_id, vec in column_rows:
        store.upsert_embedding(
            CatalogEmbeddingRecord(
                id=f"emb_{target_id}",
                kind="column",
                target_id=target_id,
                locator_key=f"loc/{target_id}",
                content_hash="parity-filter",
                embedding=vec,
                indexed_at=now,
                generation=1,
            )
        )
    query = [1.0, 0.0]
    return {
        "all": store.nearest_embeddings(
            kind="object", query=query, limit=10, generation=1
        ),
        "src_a": store.nearest_embeddings(
            kind="object",
            query=query,
            limit=10,
            generation=1,
            source_id=FILTER_SRC_A,
        ),
        "type_view": store.nearest_embeddings(
            kind="object",
            query=query,
            limit=10,
            generation=1,
            object_type="view",
        ),
        "src_a_table": store.nearest_embeddings(
            kind="object",
            query=query,
            limit=10,
            generation=1,
            source_id=FILTER_SRC_A,
            object_type="table",
        ),
        "cols_src_a": store.nearest_embeddings(
            kind="column",
            query=query,
            limit=10,
            generation=1,
            source_id=FILTER_SRC_A,
        ),
        "object_ids_a": store.nearest_embeddings(
            kind="object",
            query=query,
            limit=10,
            generation=1,
            object_ids=["obj_a_tbl"],
        ),
        "object_ids_empty": store.nearest_embeddings(
            kind="object",
            query=query,
            limit=10,
            generation=1,
            object_ids=[],
        ),
        "cols_object_ids_a": store.nearest_embeddings(
            kind="column",
            query=query,
            limit=10,
            generation=1,
            object_ids=["obj_a_tbl"],
        ),
    }


def test_memory_nearest_embeddings_honors_source_and_type_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    _activate(monkeypatch, "memory")
    found = _seed_filtered_neighbor_fixture(get_catalog_store())
    assert found["all"] == ["obj_a_tbl", "obj_b_tbl", "obj_a_view"]
    assert found["src_a"] == ["obj_a_tbl", "obj_a_view"]
    assert found["type_view"] == ["obj_a_view"]
    assert found["src_a_table"] == ["obj_a_tbl"]
    assert found["cols_src_a"] == ["col_obj_a_tbl_id", "col_obj_a_view_id"]
    assert found["object_ids_a"] == ["obj_a_tbl"]
    assert found["object_ids_empty"] == []
    assert found["cols_object_ids_a"] == ["col_obj_a_tbl_id"]


@pytest.mark.skipif(not _postgres_available(), reason="Postgres not available")
def test_sql_nearest_embeddings_filters_match_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.metadata.catalog.store import get_catalog_store

    _activate(monkeypatch, "memory")
    memory = _seed_filtered_neighbor_fixture(get_catalog_store())
    _activate(monkeypatch, "sql")
    sql = _seed_filtered_neighbor_fixture(get_catalog_store())
    assert sql == memory
    assert sql["src_a"] == ["obj_a_tbl", "obj_a_view"]
    assert sql["src_a_table"] == ["obj_a_tbl"]
    assert sql["cols_src_a"] == ["col_obj_a_tbl_id", "col_obj_a_view_id"]
    assert sql["object_ids_a"] == ["obj_a_tbl"]
    assert sql["object_ids_empty"] == []
    assert sql["cols_object_ids_a"] == ["col_obj_a_tbl_id"]
