"""Catalog Search vector path, rank_mode, and fail-loud embed errors."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.embedding import (  # noqa: E402
    CatalogEmbeddingRecord,
    set_embed_fn_for_tests,
)
from backend.metadata.catalog.service import (  # noqa: E402
    lookup_join_paths,
    search_columns,
    search_objects,
)
from backend.metadata.errors import CatalogSearchEmbedFailed  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.mcp_actor import mcp_authorization  # noqa: E402
from backend.metadata.mcp_server import (  # noqa: E402
    search_columns as mcp_search_columns,
    search_objects as mcp_search_objects,
)
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    set_embed_fn_for_tests(None)
    roles = get_role_store()
    seed_roles(roles)
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=super_admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client
    set_embed_fn_for_tests(None)


def _reset() -> None:
    reset_settings_cache()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    set_embed_fn_for_tests(None)


def _source(source_id: str, key: str) -> None:
    now = utc_now()
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


def _obj(
    *,
    object_id: str,
    name: str,
    source_id: str,
    source_key: str,
    object_type: str = "table",
    business_name: str | None = None,
) -> CatalogObjectRecord:
    now = utc_now()
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/postgresql/{source_key}/public/{object_type}/{name}",
        object_type=object_type,
        schema_name="public",
        name=name,
        ddl="CREATE TABLE x (id int)",
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
                locator_key=(
                    f"col/postgresql/{source_key}/public/{object_type}/{name}/column/id"
                ),
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


def _unit_embed(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0] for _ in texts]


def test_hybrid_source_filter_excludes_foreign_objects() -> None:
    _reset()
    _source("src_1", "mes-a")
    _source("src_2", "mes-b")
    set_embed_fn_for_tests(_unit_embed)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[_obj(object_id="obj_local", name="local_tbl", source_id="src_1", source_key="mes-a")],
        schema_scope=None,
    )
    apply_structure_snapshot(
        source=require_source("src_2"),
        job_id="j2",
        collected=[
            _obj(object_id="obj_foreign", name="foreign_tbl", source_id="src_2", source_key="mes-b")
        ],
        schema_scope=None,
    )
    found = search_objects("zzz_nomatch", source_id="src_1", limit=20, offset=0)
    assert found.rank_mode == "vector"
    assert not found.truncated
    assert [o.id for o in found.items] == ["obj_local"]
    assert all(o.source_id == "src_1" for o in found.items)
    cols = search_columns("zzz_nomatch", source_id="src_1", limit=20, offset=0)
    assert cols.rank_mode == "vector"
    assert [c.id for c in cols.items] == ["col_obj_local"]
    set_embed_fn_for_tests(None)


def test_hybrid_object_type_filter_excludes_other_types() -> None:
    _reset()
    _source("src_1", "mes-a")
    set_embed_fn_for_tests(_unit_embed)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_tbl",
                name="alpha_tbl",
                source_id="src_1",
                source_key="mes-a",
                object_type="table",
            ),
            _obj(
                object_id="obj_view",
                name="alpha_view",
                source_id="src_1",
                source_key="mes-a",
                object_type="view",
            ),
        ],
        schema_scope=None,
    )
    found = search_objects("zzz_nomatch", object_type="table", limit=20, offset=0)
    assert found.rank_mode == "vector"
    assert [o.id for o in found.items] == ["obj_tbl"]
    assert all(o.object_type == "table" for o in found.items)
    set_embed_fn_for_tests(None)


def test_empty_neighbors_is_empty_vector_page() -> None:
    _reset()
    _source("src_1", "mes-a")
    collected = [
        _obj(
            object_id=f"obj_{i:03d}",
            name=f"shared_token_{i:03d}",
            source_id="src_1",
            source_key="mes-a",
        )
        for i in range(3)
    ]
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=collected,
        schema_scope=None,
    )
    set_embed_fn_for_tests(_unit_embed)
    found = search_objects("shared_token", limit=20, offset=0)
    assert found.rank_mode == "vector"
    assert found.items == []
    assert not found.truncated
    set_embed_fn_for_tests(None)


def test_search_rank_mode_on_http_and_mcp(client: TestClient) -> None:
    _source("src_1", "mes-a")
    set_embed_fn_for_tests(_unit_embed)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                source_id="src_1",
                source_key="mes-a",
                business_name="Customer",
            )
        ],
        schema_scope=None,
    )
    http = client.get("/catalog/objects/search?q=buyer")
    assert http.status_code == 200
    body = http.json()
    assert body["rank_mode"] == "vector"
    assert "total" not in body
    assert body["truncated"] is False
    assert any(item["id"] == "obj_cust" for item in body["items"])

    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "hybrid-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    with mcp_authorization(f"Bearer {tok.json()['secret']}"):
        mcp_body = json.loads(asyncio.run(mcp_search_objects(query_text="buyer")))
        mcp_cols = json.loads(asyncio.run(mcp_search_columns(query_text="buyer")))
    assert mcp_body["rank_mode"] == "vector"
    assert "total" not in mcp_body
    assert mcp_body["truncated"] is False
    assert mcp_cols["rank_mode"] == "vector"
    set_embed_fn_for_tests(None)


def test_same_query_embeds_twice() -> None:
    _reset()
    _source("src_1", "mes-a")
    seen: list[str] = []

    def _count(texts: list[str]) -> list[list[float]]:
        seen.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(_count)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                source_id="src_1",
                source_key="mes-a",
                business_name="Customer",
            )
        ],
        schema_scope=None,
    )
    before = seen.count("buyer")
    search_objects("buyer", limit=10, offset=0)
    search_objects("buyer", limit=5, offset=0)
    assert seen.count("buyer") == before + 2
    set_embed_fn_for_tests(None)


def test_embed_failure_is_error_not_lexical_page() -> None:
    _reset()
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                source_id="src_1",
                source_key="mes-a",
            )
        ],
        schema_scope=None,
    )

    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    set_embed_fn_for_tests(_boom)
    with pytest.raises(CatalogSearchEmbedFailed):
        search_objects("cust_hdr", limit=10, offset=0)
    set_embed_fn_for_tests(None)


def test_http_embed_failure_is_503(client: TestClient) -> None:
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                source_id="src_1",
                source_key="mes-a",
            )
        ],
        schema_scope=None,
    )

    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    set_embed_fn_for_tests(_boom)
    http = client.get("/catalog/objects/search?q=cust_hdr")
    assert http.status_code == 503
    assert http.json()["code"] == "CATALOG_SEARCH_EMBED_FAILED"
    set_embed_fn_for_tests(None)


def test_join_path_query_embed_failure_is_error() -> None:
    _reset()
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_local",
                name="local_tbl",
                source_id="src_1",
                source_key="mes-a",
            ),
            _obj(
                object_id="obj_peer",
                name="peer_tbl",
                source_id="src_1",
                source_key="mes-a",
            ),
        ],
        schema_scope=None,
    )
    get_catalog_store().write_insert_join(
        from_column_id="col_obj_local",
        to_column_id="col_obj_peer",
        evidence="fk",
        created_by_user_id=None,
        attester="human",
    )

    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    set_embed_fn_for_tests(_boom)
    with pytest.raises(CatalogSearchEmbedFailed):
        lookup_join_paths(
            "obj/postgresql/mes-a/public/table/local_tbl",
            query_text="buyer",
            max_hops=2,
            top_targets=3,
        )
    set_embed_fn_for_tests(None)


def test_join_path_query_names_rank_mode() -> None:
    _reset()
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_local",
                name="local_tbl",
                source_id="src_1",
                source_key="mes-a",
            )
        ],
        schema_scope=None,
    )
    result = lookup_join_paths(
        "obj/postgresql/mes-a/public/table/local_tbl",
        query_text="no-such-business-term-zzz",
        max_hops=2,
        top_targets=3,
    )
    assert result.rank_mode == "lexical"
    assert result.reason == "TARGET_UNREACHABLE"

    explore = lookup_join_paths(
        "obj/postgresql/mes-a/public/table/local_tbl",
        max_hops=1,
        top_targets=3,
    )
    assert explore.rank_mode is None


def test_lexical_process_state_omits_total() -> None:
    _reset()
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                source_id="src_1",
                source_key="mes-a",
            )
        ],
        schema_scope=None,
    )
    found = search_objects("cust_hdr", limit=10, offset=0)
    assert found.rank_mode == "lexical"
    assert [o.id for o in found.items] == ["obj_cust"]
    assert not hasattr(found, "total")


def _join_pair() -> None:
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="customers",
                source_id="src_1",
                source_key="mes-a",
            ),
            _obj(
                object_id="obj_ord",
                name="orders",
                source_id="src_1",
                source_key="mes-a",
            ),
        ],
        schema_scope=None,
    )
    get_catalog_store().write_insert_join(
        from_column_id="col_obj_cust",
        to_column_id="col_obj_ord",
        evidence="fk",
        created_by_user_id=None,
        attester="human",
    )


def test_join_path_query_ranks_inside_reachable_set() -> None:
    _reset()
    _source("src_1", "mes-a")
    _source("src_2", "mes-b")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="customers",
                source_id="src_1",
                source_key="mes-a",
            ),
            _obj(
                object_id="obj_ord",
                name="orders",
                source_id="src_1",
                source_key="mes-a",
            ),
        ],
        schema_scope=None,
    )
    apply_structure_snapshot(
        source=require_source("src_2"),
        job_id="j2",
        collected=[
            _obj(
                object_id="obj_foreign_ord",
                name="orders",
                source_id="src_2",
                source_key="mes-b",
            )
        ],
        schema_scope=None,
    )
    get_catalog_store().write_insert_join(
        from_column_id="col_obj_cust",
        to_column_id="col_obj_ord",
        evidence="fk",
        created_by_user_id=None,
        attester="human",
    )
    result = lookup_join_paths(
        "obj/postgresql/mes-a/public/table/customers",
        query_text="orders",
        max_hops=1,
        top_targets=3,
    )
    assert result.rank_mode == "lexical"
    assert [p.target_object_id for p in result.paths] == ["obj_ord"]
    assert result.reason is None


def test_join_path_query_embeds_once_and_builds_graph_once() -> None:
    _reset()
    _source("src_1", "mes-a")
    _join_pair()
    seen: list[str] = []

    def _count(texts: list[str]) -> list[list[float]]:
        seen.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(_count)
    store = get_catalog_store()
    counts = {"objects": 0, "joins": 0}
    orig_objects = store.list_present_for_source
    orig_joins = store.list_all_joins_for_source

    def _objects(source_id: str):
        counts["objects"] += 1
        return orig_objects(source_id)

    def _joins(source_id: str):
        counts["joins"] += 1
        return orig_joins(source_id)

    store.list_present_for_source = _objects  # type: ignore[method-assign]
    store.list_all_joins_for_source = _joins  # type: ignore[method-assign]
    result = lookup_join_paths(
        "obj/postgresql/mes-a/public/table/customers",
        query_text="orders",
        max_hops=1,
        top_targets=3,
    )
    assert result.rank_mode == "vector"
    assert seen.count("orders") == 1
    assert counts["objects"] == 1
    assert counts["joins"] == 1
    set_embed_fn_for_tests(None)


def test_join_path_query_recalls_reachable_over_closer_unrelated() -> None:
    _reset()
    _source("src_1", "mes-a")
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="customers",
                source_id="src_1",
                source_key="mes-a",
            ),
            _obj(
                object_id="obj_ord",
                name="orders",
                source_id="src_1",
                source_key="mes-a",
            ),
            _obj(
                object_id="obj_amt",
                name="amount_fact",
                source_id="src_1",
                source_key="mes-a",
            ),
        ],
        schema_scope=None,
    )
    store = get_catalog_store()
    store.write_insert_join(
        from_column_id="col_obj_cust",
        to_column_id="col_obj_ord",
        evidence="fk",
        created_by_user_id=None,
        attester="human",
    )
    now = utc_now()
    store.upsert_embedding(
        CatalogEmbeddingRecord(
            id="emb_ord",
            kind="column",
            target_id="col_obj_ord",
            locator_key="col/ord",
            content_hash="h",
            embedding=[0.2, 0.9],
            indexed_at=now,
            generation=0,
        )
    )
    store.upsert_embedding(
        CatalogEmbeddingRecord(
            id="emb_amt",
            kind="column",
            target_id="col_obj_amt",
            locator_key="col/amt",
            content_hash="h",
            embedding=[1.0, 0.0],
            indexed_at=now,
            generation=0,
        )
    )
    set_embed_fn_for_tests(lambda texts: [[1.0, 0.0] for _ in texts])
    result = lookup_join_paths(
        "obj/postgresql/mes-a/public/table/customers",
        query_text="amount",
        max_hops=1,
        top_targets=3,
    )
    assert result.rank_mode == "vector"
    assert [p.target_object_id for p in result.paths] == ["obj_ord"]
    set_embed_fn_for_tests(None)

