"""Boundary invariants for locator, FK→Join, search, semantics, and join path."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.errors import LocatorInvalid  # noqa: E402
from backend.metadata.joins.graph import find_join_paths  # noqa: E402
from backend.metadata.locators import (  # noqa: E402
    format_column_locator,
    format_object_locator,
    format_source_locator,
    source_locator_segment,
)
from backend.metadata.schemas.catalog import (  # noqa: E402
    ColumnSemanticsPatchRequest,
    ObjectSemanticsPatchRequest,
    SemanticSource,
)
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
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


@pytest.fixture(autouse=True)
def _reset_memory_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_catalog_store()
    reset_source_store()
    now = datetime.utcnow()
    get_source_store().create_source(
        SourceRecord(
            id="src_1",
            key="demo-src",
            locator_key="src/postgresql/demo-src",
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
    *,
    col_id: str,
    object_id: str,
    name: str,
    table: str,
    ordinal: int = 0,
) -> CatalogColumnRecord:
    now = datetime.utcnow()
    return CatalogColumnRecord(
        id=col_id,
        object_id=object_id,
        locator_key=format_column_locator(
            engine="postgresql",
            kind="database",
            source_key="demo-src",
            schema_name="public",
            object_type="table",
            name=table,
            column_name=name,
        ),
        name=name,
        ordinal=ordinal,
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


def _table(
    *,
    object_id: str,
    name: str,
    columns: list[tuple[str, str]],
    foreign_keys: list[CatalogForeignKeyRecord] | None = None,
) -> CatalogObjectRecord:
    now = datetime.utcnow()
    return CatalogObjectRecord(
        id=object_id,
        source_id="src_1",
        locator_key=format_object_locator(
            engine="postgresql",
            kind="database",
            source_key="demo-src",
            schema_name="public",
            object_type="table",
            name=name,
        ),
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
            _col(col_id=cid, object_id=object_id, name=cname, table=name, ordinal=i)
            for i, (cid, cname) in enumerate(columns)
        ],
        foreign_keys=list(foreign_keys or []),
    )


def test_source_locator_rejects_empty_engine_and_kind() -> None:
    with pytest.raises(LocatorInvalid):
        source_locator_segment(engine=None, kind="")
    with pytest.raises(LocatorInvalid):
        source_locator_segment(engine="  ", kind="  ")
    with pytest.raises(LocatorInvalid):
        format_source_locator(engine=None, kind="", key="k")


def test_locator_formatters_match_runtime_rules() -> None:
    assert format_source_locator(engine="PostgreSQL", kind="database", key="a/b") == (
        "src/postgresql/a%2Fb"
    )
    assert format_object_locator(
        engine="postgresql",
        kind="database",
        source_key="demo",
        schema_name="public",
        object_type="table",
        name="orders",
    ) == "obj/postgresql/demo/public/table/orders"
    assert format_column_locator(
        engine=None,
        kind="api",
        source_key="svc",
        schema_name="-",
        object_type="resource",
        name="items",
        column_name="id",
    ) == "col/api/svc/-/resource/items/column/id"


def test_unpublished_reencode_migration_removed() -> None:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    names = {p.name for p in versions.glob("*.py")}
    assert "0017_reencode_locator_keys.py" not in names
    assert "0013_locator_keys.py" in names
    assert "0016_join_graph.py" in names


def test_semantic_source_excludes_system_specific_vocab() -> None:
    allowed = set(get_args(SemanticSource))
    assert allowed == {"mcp", "user_input"}
    assert "erp_dictionary" not in allowed
    assert "e9_dictionary" not in allowed
    assert "model_routing_hint" not in ObjectSemanticsPatchRequest.model_fields
    assert "model_routing_hint" not in ColumnSemanticsPatchRequest.model_fields
    assert "field_kind" not in ColumnSemanticsPatchRequest.model_fields


def test_blank_search_query_rejected(client: TestClient) -> None:
    for path in ("/catalog/objects/search", "/catalog/columns/search"):
        missing = client.get(path)
        assert missing.status_code == 422
        blank = client.get(path, params={"q": "   "})
        assert blank.status_code == 400
        assert blank.json()["code"] == "CATALOG_SEARCH_QUERY_REQUIRED"


def test_illegal_semantics_and_field_kind_not_writable(client: TestClient) -> None:
    source = client.post(
        "/sources",
        json={
            "key": "demo-http",
            "name": "Demo",
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert source.status_code == 201
    source_id = source.json()["source"]["id"]
    store = get_catalog_store()
    obj = _table(
        object_id="obj_http",
        name="orders",
        columns=[("col_id", "id"), ("col_note", "note")],
    )
    obj.source_id = source_id
    apply_structure_snapshot(
        source_id=source_id,
        job_id="seed",
        collected=[obj],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo-http",
    )
    stored = store.get_object(obj.id)
    assert stored is not None
    col = stored.columns[0]
    before_kind = col.field_kind

    bad_category = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"object_category": "erp_dictionary"},
    )
    assert bad_category.status_code == 422

    unknown_pk = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_primary_key": ["not_a_real_column"]},
    )
    assert unknown_pk.status_code == 400
    assert unknown_pk.json()["code"] == "SEMANTIC_COLUMN_UNKNOWN"

    unknown_domain = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_domain_code": "missing-domain"},
    )
    assert unknown_domain.status_code == 400
    assert unknown_domain.json()["code"] == "BUSINESS_DOMAIN_UNKNOWN"

    ignored = client.patch(
        f"/columns/{col.id}/semantics",
        json={"business_name": "Order Id", "field_kind": "computed"},
    )
    assert ignored.status_code == 200
    refreshed = store.get_column(col.id)
    assert refreshed is not None
    assert refreshed.field_kind == before_kind
    assert refreshed.business_name == "Order Id"

    from backend.metadata.catalog import service as catalog_service

    batch = catalog_service.set_column_semantics_batch(
        object_id=obj.id,
        columns=[{"column_name": "missing_col", "business_name": "X"}],
        actor_user_id="user_1",
        actor_token_id=None,
        semantic_source="mcp",
    )
    assert batch["updated_count"] == 0
    assert batch["skipped_columns"][0]["reason"] == "invalid_column_name"


def test_join_path_reasons() -> None:
    store = get_catalog_store()
    a = _table(object_id="obj_a", name="a", columns=[("col_a", "id")])
    b = _table(object_id="obj_b", name="b", columns=[("col_b", "id")])
    apply_structure_snapshot(
        source_id="src_1",
        job_id="j1",
        collected=[a, b],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo-src",
    )
    missing_start = find_join_paths(
        store=store,
        start_object_id="missing",
        target_object_id="obj_b",
        max_hops=1,
        top_targets=3,
    )
    assert missing_start.reason == "NO_START_COLUMNS"
    assert missing_start.paths == []

    unreachable = find_join_paths(
        store=store,
        start_object_id="obj_a",
        target_object_id="obj_b",
        max_hops=1,
        top_targets=3,
    )
    assert unreachable.reason == "TARGET_UNREACHABLE"
    assert unreachable.paths == []


def test_fk_unresolved_aborts_and_keeps_snapshot() -> None:
    store = get_catalog_store()
    customers = _table(
        object_id="obj_customers",
        name="customers",
        columns=[("col_cust_id", "id")],
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
    )
    apply_structure_snapshot(
        source_id="src_1",
        job_id="job_old",
        collected=[customers, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo-src",
    )
    joins_before = store.list_joins_for_object("obj_orders")
    assert len(joins_before) == 1
    assert joins_before[0].origin == "foreign_key"
    assert joins_before[0].to_column_id == "col_cust_id"
    present_before = {o.id: o.name for o in store.list_present_for_source("src_1")}

    broken_orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_cust_fk", "customer_id")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_orders_missing",
                columns=["customer_id"],
                ref_schema="public",
                ref_table="ghost",
                ref_columns=["id"],
            )
        ],
    )
    with pytest.raises(CatalogWriteAborted) as exc:
        apply_structure_snapshot(
            source_id="src_1",
            job_id="job_bad",
            collected=[customers, broken_orders],
            schema_scope=None,
            fail_safe_threshold=1.0,
            engine="postgresql",
            kind="database",
            source_key="demo-src",
        )
    assert exc.value.code == "JOB_FK_UNRESOLVED"
    present_after = {o.id: o.name for o in store.list_present_for_source("src_1")}
    assert present_after == present_before
    joins_after = store.list_joins_for_object("obj_orders")
    assert len(joins_after) == 1
    assert joins_after[0].to_column_id == "col_cust_id"


def test_fk_column_mismatch_aborts() -> None:
    store = get_catalog_store()
    parent = _table(
        object_id="obj_parent",
        name="parent",
        columns=[("col_p1", "a"), ("col_p2", "b")],
    )
    child = _table(
        object_id="obj_child",
        name="child",
        columns=[("col_c1", "a"), ("col_c2", "b")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_bad_counts",
                columns=["a", "b"],
                ref_schema="public",
                ref_table="parent",
                ref_columns=["a"],
            )
        ],
    )
    with pytest.raises(CatalogWriteAborted) as exc:
        apply_structure_snapshot(
            source_id="src_1",
            job_id="job_mismatch",
            collected=[parent, child],
            schema_scope=None,
            fail_safe_threshold=1.0,
            engine="postgresql",
            kind="database",
            source_key="demo-src",
        )
    assert exc.value.code == "JOB_FK_COLUMN_MISMATCH"
    assert store.list_present_for_source("src_1") == []


def test_fk_retarget_clears_stale_edge() -> None:
    store = get_catalog_store()
    customers = _table(
        object_id="obj_customers",
        name="customers",
        columns=[("col_cust_id", "id")],
    )
    partners = _table(
        object_id="obj_partners",
        name="partners",
        columns=[("col_part_id", "id")],
    )
    orders = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_ref", "ref_id")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_orders_ref",
                columns=["ref_id"],
                ref_schema="public",
                ref_table="customers",
                ref_columns=["id"],
            )
        ],
    )
    apply_structure_snapshot(
        source_id="src_1",
        job_id="job_v1",
        collected=[customers, partners, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo-src",
    )
    first = store.list_joins_for_object("obj_orders")
    assert len(first) == 1
    assert first[0].to_column_id == "col_cust_id"

    retargeted = _table(
        object_id="obj_orders",
        name="orders",
        columns=[("col_ord_id", "id"), ("col_ref", "ref_id")],
        foreign_keys=[
            CatalogForeignKeyRecord(
                name="fk_orders_ref",
                columns=["ref_id"],
                ref_schema="public",
                ref_table="partners",
                ref_columns=["id"],
            )
        ],
    )
    apply_structure_snapshot(
        source_id="src_1",
        job_id="job_v2",
        collected=[customers, partners, retargeted],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo-src",
    )
    second = store.list_joins_for_object("obj_orders")
    assert len(second) == 1
    assert second[0].from_column_id == "col_ref"
    assert second[0].to_column_id == "col_part_id"
    assert second[0].origin == "foreign_key"
