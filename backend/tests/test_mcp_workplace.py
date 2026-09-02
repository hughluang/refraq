"""MCP workplace: split reads, Semantics Change, hybrid search, join path query."""

from __future__ import annotations

import os
from dataclasses import replace

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
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.embedding import cosine_similarity, set_embed_fn_for_tests  # noqa: E402
from backend.metadata.catalog.service import lookup_join_paths, search_objects  # noqa: E402
from backend.metadata.errors import JoinPathUnavailable  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.mcp_guidance import SERVER_INSTRUCTIONS, TOOL_DESCRIPTIONS  # noqa: E402
from backend.metadata.mcp_server import mcp  # noqa: E402
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


def test_server_instructions_and_prompts() -> None:
    assert "search_sources" in (mcp.instructions or "")
    assert SERVER_INSTRUCTIONS.strip()
    import asyncio

    names = {p.name for p in asyncio.run(mcp.list_prompts())}
    assert names == {
        "lookup_business",
        "analyze_object",
        "explore_join_path",
        "enrich_semantics",
    }
    assert "get_object_semantics" in TOOL_DESCRIPTIONS["get_object"]


def _source() -> None:
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
    business_name: str | None = None,
    business_description: str | None = None,
) -> CatalogObjectRecord:
    now = utc_now()
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_1",
        locator_key=f"obj/postgresql/mes-prod/public/table/{name}",
        object_type="table",
        schema_name="public",
        name=name,
        ddl="CREATE TABLE x (id int)",
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
                locator_key=f"col/postgresql/mes-prod/public/table/{name}/column/id",
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


def test_semantics_change_http_and_mcp(client: TestClient) -> None:
    _source()
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[_obj(object_id="obj_wo", name="wo_hdr")],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    patched = client.patch(
        "/objects/obj_wo/semantics",
        json={"business_name": "Work Order", "business_description": "One header"},
    )
    assert patched.status_code == 200, patched.text
    listed = client.get("/objects/obj_wo/semantics-changes")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    names = {row["field_name"] for row in items}
    assert "business_name" in names
    assert any(row["new_value"] == "Work Order" for row in items)
    assert any(row["old_value"] is None for row in items if row["field_name"] == "business_name")


def test_hybrid_search_finds_semantic_only_hit() -> None:
    _source()

    def fake_embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            low = text.lower()
            if "customer" in low or "buyer" in low:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out

    set_embed_fn_for_tests(fake_embed)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[
            _obj(
                object_id="obj_cust",
                name="cust_hdr",
                business_name="Customer",
            ),
            _obj(object_id="obj_wid", name="widgets"),
        ],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    _, lexical_total = get_catalog_store().search_objects("buyer", limit=10, offset=0)
    items, total = search_objects("buyer", limit=10, offset=0)
    assert total == lexical_total
    assert any(o.id == "obj_cust" for o in items)

    _, lexical_cust = get_catalog_store().search_objects("cust", limit=10, offset=0)
    fused, fused_total = search_objects("cust", limit=10, offset=0)
    assert fused_total == lexical_cust
    assert any(o.id == "obj_cust" for o in fused)
    set_embed_fn_for_tests(None)


def test_join_path_query_without_hit_is_unreachable() -> None:
    _source()
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[_obj(object_id="obj_wo", name="wo_hdr")],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    result = lookup_join_paths(
        "obj/postgresql/mes-prod/public/table/wo_hdr",
        query_text="no-such-business-term-zzz",
        max_hops=2,
        top_targets=3,
    )
    assert result.paths_found == 0
    assert result.reason == "TARGET_UNREACHABLE"


def test_hybrid_query_embed_failure_uses_lexical_page() -> None:
    _source()

    def boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    set_embed_fn_for_tests(boom)
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[_obj(object_id="obj_cust", name="cust_hdr")],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    items, total = search_objects("cust_hdr", limit=10, offset=0)
    store_items, store_total = get_catalog_store().search_objects(
        "cust_hdr", limit=10, offset=0
    )
    assert total == store_total
    assert [o.id for o in items] == [o.id for o in store_items]
    set_embed_fn_for_tests(None)


def test_join_path_query_empty_start_is_unavailable() -> None:
    _source()
    empty = replace(_obj(object_id="obj_empty", name="empty_tbl"), columns=[])
    apply_structure_snapshot(
        source=require_source("src_1"),
        job_id="j1",
        collected=[empty],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    with pytest.raises(JoinPathUnavailable):
        lookup_join_paths(
            "obj/postgresql/mes-prod/public/table/empty_tbl",
            query_text="anything",
        )


def test_cosine_similarity_rejects_incompatible_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) is None
    assert cosine_similarity([], [1.0]) is None
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) is None
