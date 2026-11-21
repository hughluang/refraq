"""Catalog, search, query, and sample honor Source Access."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.embedding import set_embed_fn_for_tests  # noqa: E402
from backend.metadata.catalog.join_pair import Inserted  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.source_access import (  # noqa: E402
    create_membership,
    reset_source_access_store,
)
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)
from backend.metadata.structure_diffs.store import reset_structure_diff_store  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

PASSWORD = "secret"


@dataclass
class _World:
    client: TestClient
    source_a: str
    source_b: str
    source_disabled: str
    object_a: str
    object_a2: str
    object_b: str
    procedure_a: str
    column_a: str
    column_a2: str
    column_b: str
    diff_a: str
    users: dict[str, str]

    def login(self, account: str) -> None:
        response = self.client.post(
            "/auth/login",
            json={"account": account, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    reset_source_access_store()
    reset_structure_diff_store()
    set_embed_fn_for_tests(None)
    roles = get_role_store()
    seed_roles(roles)
    full = create_role(
        roles,
        key="catalog_full",
        name="Catalog full",
        permissions=[
            "console:access",
            "channel:read",
            "channel:write",
            "mirror:read",
            "metadata:read",
            "metadata:write",
            "catalog:sample",
            "query:run",
        ],
    )
    read_only = create_role(
        roles,
        key="catalog_read",
        name="Catalog read",
        permissions=[
            "console:access",
            "metadata:read",
            "catalog:sample",
            "query:run",
        ],
    )
    no_query = create_role(
        roles,
        key="catalog_no_query",
        name="Catalog no query",
        permissions=[
            "console:access",
            "metadata:read",
            "metadata:write",
            "catalog:sample",
        ],
    )
    no_sample = create_role(
        roles,
        key="catalog_no_sample",
        name="Catalog no sample",
        permissions=[
            "console:access",
            "metadata:read",
            "metadata:write",
            "query:run",
        ],
    )
    users = {
        "hidden": _user("hidden", full.id),
        "viewer": _user("viewer", full.id),
        "steward": _user("steward", full.id),
        "reader": _user("reader", read_only.id),
        "noquery": _user("noquery", no_query.id),
        "nosample": _user("nosample", no_sample.id),
    }
    _source("src_a", "src-a", status="active")
    _source("src_b", "src-b", status="active")
    _source("src_off", "src-off", status="disabled")
    orders = _obj(
        object_id="obj_orders",
        name="orders",
        source_id="src_a",
        source_key="src-a",
    )
    customers = _obj(
        object_id="obj_customers",
        name="customers",
        source_id="src_a",
        source_key="src-a",
    )
    procedure = _obj(
        object_id="obj_proc",
        name="sync_proc",
        source_id="src_a",
        source_key="src-a",
        object_type="procedure",
    )
    secret = _obj(
        object_id="obj_secret",
        name="orders_hidden",
        source_id="src_b",
        source_key="src-b",
    )
    committed = apply_structure_snapshot(
        source=require_source("src_a"),
        job_id="job_a",
        collected=[orders, customers, procedure],
        schema_scope=None,
    )
    apply_structure_snapshot(
        source=require_source("src_b"),
        job_id="job_b",
        collected=[secret],
        schema_scope=None,
    )
    create_membership(
        subject_type="user",
        subject_id=users["viewer"],
        target="src_a",
        level="viewer",
    )
    create_membership(
        subject_type="user",
        subject_id=users["steward"],
        target="src_a",
        level="steward",
    )
    create_membership(
        subject_type="user",
        subject_id=users["steward"],
        target="src_b",
        level="steward",
    )
    create_membership(
        subject_type="user",
        subject_id=users["reader"],
        target="src_a",
        level="maintainer",
    )
    create_membership(
        subject_type="user",
        subject_id=users["noquery"],
        target="src_off",
        level="maintainer",
    )
    create_membership(
        subject_type="user",
        subject_id=users["nosample"],
        target="src_a",
        level="maintainer",
    )
    built = _World(
        client=TestClient(app),
        source_a="src_a",
        source_b="src_b",
        source_disabled="src_off",
        object_a="obj_orders",
        object_a2="obj_customers",
        object_b="obj_secret",
        procedure_a="obj_proc",
        column_a="col_obj_orders",
        column_a2="col_obj_customers",
        column_b="col_obj_secret",
        diff_a=committed.structure_diff_id,
        users=users,
    )
    with built.client:
        yield built
    set_embed_fn_for_tests(None)


def _user(account: str, role_id: str) -> str:
    record = get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password(PASSWORD),
        role_id=role_id,
        status="active",
    )
    return record.id


def _source(source_id: str, key: str, *, status: str) -> None:
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key=key,
            locator_key=f"src/postgresql/{key}",
            name=key,
            kind="database",
            status=status,
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
    engine: str = "postgresql",
) -> CatalogObjectRecord:
    now = utc_now()
    column_id = f"col_{object_id}"
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/{engine}/{source_key}/public/{object_type}/{name}",
        object_type=object_type,
        schema_name="public",
        name=name,
        ddl="CREATE TABLE x (id int)",
        comment=None,
        primary_key=None,
        is_present=True,
        business_name=None,
        business_description=None,
        object_category=None,
        grain_description=None,
        business_primary_key=None,
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
                id=column_id,
                object_id=object_id,
                locator_key=(
                    f"col/{engine}/{source_key}/public/{object_type}/{name}/column/id"
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


def _insert_join(world: _World) -> str:
    result = get_catalog_store().write_insert_join(
        from_column_id=world.column_a,
        to_column_id=world.column_a2,
        evidence="analyst confirmed",
        created_by_user_id=world.users["steward"],
        attester="human",
    )
    assert isinstance(result, Inserted)
    return result.record.id


def _join_body(world: _World, *, to_column_id: str | None = None) -> dict[str, str]:
    return {
        "from_column_id": world.column_a,
        "to_column_id": to_column_id or world.column_a2,
        "evidence": "analyst confirmed",
    }


def test_hidden_source_list_matches_unknown_source(world: _World) -> None:
    world.login("hidden")
    hidden = world.client.get(f"/sources/{world.source_a}/objects")
    unknown = world.client.get("/sources/src_missing/objects")
    assert_problem(hidden, status=404, code="SOURCE_NOT_FOUND")
    assert_problem(unknown, status=404, code="SOURCE_NOT_FOUND")


def test_viewer_lists_objects_on_visible_source_only(world: _World) -> None:
    world.login("viewer")
    listed = world.client.get(f"/sources/{world.source_a}/objects")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["items"]} >= {
        world.object_a,
        world.object_a2,
    }
    foreign = world.client.get(f"/sources/{world.source_b}/objects")
    assert_problem(foreign, status=404, code="SOURCE_NOT_FOUND")


@pytest.mark.parametrize(
    "path",
    [
        "/objects/{object_id}",
        "/objects/{object_id}/ddl",
        "/objects/{object_id}/semantics-changes",
        "/objects/{object_id}/joins",
    ],
)
def test_hidden_object_reads_match_unknown_object(world: _World, path: str) -> None:
    world.login("hidden")
    hidden = world.client.get(path.format(object_id=world.object_a))
    unknown = world.client.get(path.format(object_id="obj_missing"))
    assert_problem(hidden, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    assert_problem(unknown, status=404, code="CATALOG_OBJECT_NOT_FOUND")


def test_viewer_reads_visible_object(world: _World) -> None:
    world.login("viewer")
    loaded = world.client.get(f"/objects/{world.object_a}")
    assert loaded.status_code == 200
    assert loaded.json()["object"]["id"] == world.object_a
    foreign = world.client.get(f"/objects/{world.object_b}")
    assert_problem(foreign, status=404, code="CATALOG_OBJECT_NOT_FOUND")


def test_semantics_write_follows_level_and_role(world: _World) -> None:
    body = {"business_name": "Orders"}
    world.login("hidden")
    assert_problem(
        world.client.patch(f"/objects/{world.object_a}/semantics", json=body),
        status=404,
        code="CATALOG_OBJECT_NOT_FOUND",
    )
    world.login("viewer")
    assert_problem(
        world.client.patch(f"/objects/{world.object_a}/semantics", json=body),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("reader")
    assert_problem(
        world.client.patch(f"/objects/{world.object_a}/semantics", json=body),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("steward")
    updated = world.client.patch(f"/objects/{world.object_a}/semantics", json=body)
    assert updated.status_code == 200
    assert updated.json()["object"]["business_name"] == "Orders"


def test_column_semantics_write_uses_column_not_found(world: _World) -> None:
    body = {"business_name": "Identifier"}
    world.login("hidden")
    assert_problem(
        world.client.patch(f"/columns/{world.column_a}/semantics", json=body),
        status=404,
        code="CATALOG_COLUMN_NOT_FOUND",
    )
    world.login("viewer")
    assert_problem(
        world.client.patch(f"/columns/{world.column_a}/semantics", json=body),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("steward")
    updated = world.client.patch(f"/columns/{world.column_a}/semantics", json=body)
    assert updated.status_code == 200
    assert updated.json()["column"]["business_name"] == "Identifier"


def test_column_semantics_batch_uses_object_not_found(world: _World) -> None:
    body = {"columns": [{"column_name": "id", "business_name": "Identifier"}]}
    world.login("hidden")
    assert_problem(
        world.client.patch(f"/objects/{world.object_a}/columns/semantics", json=body),
        status=404,
        code="CATALOG_OBJECT_NOT_FOUND",
    )
    world.login("viewer")
    assert_problem(
        world.client.patch(f"/objects/{world.object_a}/columns/semantics", json=body),
        status=403,
        code="AUTH_FORBIDDEN",
    )


def test_join_create_invisible_endpoint_is_not_cross_source(world: _World) -> None:
    world.login("viewer")
    refused = world.client.post(
        "/joins",
        json=_join_body(world, to_column_id=world.column_b),
    )
    assert_problem(refused, status=404, code="CATALOG_COLUMN_NOT_FOUND")
    world.login("hidden")
    hidden = world.client.post("/joins", json=_join_body(world))
    assert_problem(hidden, status=404, code="CATALOG_COLUMN_NOT_FOUND")


def test_join_create_visible_cross_source_succeeds(world: _World) -> None:
    world.login("steward")
    created = world.client.post(
        "/joins",
        json=_join_body(world, to_column_id=world.column_b),
    )
    assert created.status_code == 201
    local = world.client.post("/joins", json=_join_body(world))
    assert local.status_code == 201


def test_join_create_viewer_on_visible_pair_is_forbidden(world: _World) -> None:
    world.login("viewer")
    refused = world.client.post("/joins", json=_join_body(world))
    assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
    world.login("reader")
    role_refused = world.client.post("/joins", json=_join_body(world))
    assert_problem(role_refused, status=403, code="AUTH_FORBIDDEN")


def test_join_batch_invisible_endpoint_is_not_cross_source(world: _World) -> None:
    world.login("viewer")
    refused = world.client.post(
        "/joins:batch",
        json={"joins": [_join_body(world, to_column_id=world.column_b)]},
    )
    assert_problem(refused, status=404, code="CATALOG_COLUMN_NOT_FOUND")
    world.login("steward")
    visible = world.client.post(
        "/joins:batch",
        json={"joins": [_join_body(world, to_column_id=world.column_b)]},
    )
    assert visible.status_code == 200
    assert visible.json()["created_count"] == 1


def test_join_amend_reject_restore_and_delete_follow_write_rule(world: _World) -> None:
    join_id = _insert_join(world)
    patch = {"evidence": "revised", "join_kind": "INNER"}
    world.login("hidden")
    assert_problem(
        world.client.patch(f"/joins/{join_id}", json=patch),
        status=404,
        code="CATALOG_JOIN_NOT_FOUND",
    )
    world.login("viewer")
    assert_problem(
        world.client.patch(f"/joins/{join_id}", json=patch),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("reader")
    assert_problem(
        world.client.patch(f"/joins/{join_id}", json=patch),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("steward")
    amended = world.client.patch(f"/joins/{join_id}", json=patch)
    assert amended.status_code == 200
    rejected = world.client.post(f"/joins/{join_id}/reject")
    assert rejected.status_code == 200
    world.login("hidden")
    assert_problem(
        world.client.post(f"/joins/{join_id}/restore"),
        status=404,
        code="CATALOG_JOIN_NOT_FOUND",
    )
    world.login("steward")
    restored = world.client.post(f"/joins/{join_id}/restore")
    assert restored.status_code == 200
    world.login("viewer")
    assert_problem(
        world.client.delete(f"/joins/{join_id}"),
        status=403,
        code="AUTH_FORBIDDEN",
    )
    world.login("steward")
    deleted = world.client.delete(f"/joins/{join_id}")
    assert deleted.status_code == 204


def test_join_path_hidden_target_matches_unknown_target(world: _World) -> None:
    world.login("viewer")
    hidden = world.client.get(
        "/joins/path",
        params={"start": world.object_a, "target": world.object_b},
    )
    unknown = world.client.get(
        "/joins/path",
        params={"start": world.object_a, "target": "obj_missing"},
    )
    column = world.client.get(
        "/joins/path",
        params={"start": world.object_a, "target": world.column_b},
    )
    assert_problem(hidden, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    assert_problem(unknown, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    assert_problem(column, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    world.login("steward")
    crossed = world.client.get(
        "/joins/path",
        params={"start": world.object_a, "target": world.object_b},
    )
    assert crossed.status_code == 200
    assert crossed.json()["paths_found"] == 0
    assert crossed.json()["reason"] == "TARGET_UNREACHABLE"


def test_join_path_hidden_start_is_not_found(world: _World) -> None:
    world.login("viewer")
    hidden = world.client.get("/joins/path", params={"start": world.object_b})
    assert_problem(hidden, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    visible = world.client.get("/joins/path", params={"start": world.object_a})
    assert visible.status_code == 200


def test_structure_diff_hidden_matches_unknown(world: _World) -> None:
    world.login("hidden")
    listed = world.client.get(f"/sources/{world.source_a}/structure-diffs")
    unknown_source = world.client.get("/sources/src_missing/structure-diffs")
    loaded = world.client.get(f"/structure-diffs/{world.diff_a}")
    unknown_diff = world.client.get("/structure-diffs/sdiff_missing")
    assert_problem(listed, status=404, code="SOURCE_NOT_FOUND")
    assert_problem(unknown_source, status=404, code="SOURCE_NOT_FOUND")
    assert_problem(loaded, status=404, code="STRUCTURE_DIFF_NOT_FOUND")
    assert_problem(unknown_diff, status=404, code="STRUCTURE_DIFF_NOT_FOUND")


def test_viewer_reads_structure_diff(world: _World) -> None:
    world.login("viewer")
    listed = world.client.get(f"/sources/{world.source_a}/structure-diffs")
    assert listed.status_code == 200
    assert any(item["id"] == world.diff_a for item in listed.json()["items"])
    loaded = world.client.get(f"/structure-diffs/{world.diff_a}")
    assert loaded.status_code == 200
    assert loaded.json()["structure_diff"]["id"] == world.diff_a
    foreign = world.client.get(f"/sources/{world.source_b}/structure-diffs")
    assert_problem(foreign, status=404, code="SOURCE_NOT_FOUND")


def test_query_hidden_source_is_not_found_before_disabled(world: _World) -> None:
    world.login("hidden")
    hidden = world.client.post(
        f"/sources/{world.source_disabled}/query",
        json={"sql": "select 1"},
    )
    assert_problem(hidden, status=404, code="SOURCE_NOT_FOUND")
    world.login("noquery")
    forbidden = world.client.post(
        f"/sources/{world.source_disabled}/query",
        json={"sql": "select 1"},
    )
    assert_problem(forbidden, status=403, code="AUTH_FORBIDDEN")
    create_membership(
        subject_type="user",
        subject_id=world.users["viewer"],
        target=world.source_disabled,
        level="viewer",
    )
    world.login("viewer")
    disabled = world.client.post(
        f"/sources/{world.source_disabled}/query",
        json={"sql": "select 1"},
    )
    assert_problem(disabled, status=400, code="JOB_SOURCE_DISABLED")


def test_sample_hidden_object_is_not_found_before_unsupported_type(
    world: _World,
) -> None:
    world.login("hidden")
    hidden = world.client.post(f"/objects/{world.procedure_a}/sample", json={})
    assert_problem(hidden, status=404, code="CATALOG_OBJECT_NOT_FOUND")
    world.login("nosample")
    forbidden = world.client.post(f"/objects/{world.procedure_a}/sample", json={})
    assert_problem(forbidden, status=403, code="AUTH_FORBIDDEN")
    world.login("viewer")
    unsupported = world.client.post(f"/objects/{world.procedure_a}/sample", json={})
    assert_problem(unsupported, status=400, code="SAMPLE_OBJECT_TYPE_UNSUPPORTED")


def test_search_hides_invisible_sources_for_both_rank_modes(world: _World) -> None:
    world.login("viewer")
    lexical_objects = world.client.get("/catalog/objects/search", params={"q": "orders"})
    assert lexical_objects.status_code == 200
    lexical_body = lexical_objects.json()
    assert lexical_body["rank_mode"] == "lexical"
    assert {item["id"] for item in lexical_body["items"]} == {world.object_a}
    lexical_columns = world.client.get("/catalog/columns/search", params={"q": "id"})
    assert {item["id"] for item in lexical_columns.json()["items"]} == {
        world.column_a,
        world.column_a2,
        f"col_{world.procedure_a}",
    }
    filtered = world.client.get(
        "/catalog/objects/search",
        params={"q": "orders", "source_id": world.source_b},
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"] == []
    unknown = world.client.get(
        "/catalog/objects/search",
        params={"q": "orders", "source_id": "src_missing"},
    )
    assert unknown.status_code == 200
    assert unknown.json()["items"] == []

    def _embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(_embed)
    now = utc_now()
    from backend.metadata.catalog.embedding import CatalogEmbeddingRecord

    store = get_catalog_store()
    for object_id in (world.object_a, world.object_b):
        store.upsert_embedding(
            CatalogEmbeddingRecord(
                id=f"emb_{object_id}",
                kind="object",
                target_id=object_id,
                locator_key=f"loc/{object_id}",
                content_hash="h",
                embedding=[1.0, 0.0],
                indexed_at=now,
                generation=0,
            )
        )
    vector_objects = world.client.get("/catalog/objects/search", params={"q": "orders"})
    assert vector_objects.status_code == 200
    vector_body = vector_objects.json()
    assert vector_body["rank_mode"] == "vector"
    assert [item["id"] for item in vector_body["items"]] == [world.object_a]


def test_search_with_no_visible_source_is_an_empty_page(world: _World) -> None:
    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("should not embed")

    set_embed_fn_for_tests(_boom)
    world.login("hidden")
    found = world.client.get("/catalog/objects/search", params={"q": "orders"})
    assert found.status_code == 200
    body = found.json()
    assert body["items"] == []
    assert body["rank_mode"] == "vector"
    columns = world.client.get("/catalog/columns/search", params={"q": "id"})
    assert columns.status_code == 200
    assert columns.json()["items"] == []


def test_catalog_detail_offers_sync_for_visible_supported_tables(world):
    world.login("viewer")
    eligible = world.client.get(f"/objects/{world.object_a}").json()["object"]
    assert eligible["sync_table"] == {"source_name": "src-a", "qualified_table": "public.orders"}
    procedure = world.client.get(f"/objects/{world.procedure_a}").json()["object"]
    assert procedure["sync_table"] is None
    assert world.client.get(f"/objects/{world.object_b}").status_code == 404

    world.login("steward")
    for path, changes in [
        ("semantics", {"business_name": "Orders"}),
        ("columns/semantics", {"columns": [{"column_name": "id", "business_name": "Identifier"}]}),
    ]:
        saved = world.client.patch(f"/objects/{world.object_a}/{path}", json=changes)
        assert saved.status_code == 200, saved.text
        assert saved.json()["object"]["sync_table"] == eligible["sync_table"]


@pytest.mark.parametrize("field", ["manual_name", "read_name"])
def test_table_setup_rejects_blank_node_name(world, field):
    world.login("viewer")
    body = {"name": "Orders", "table_setup": {
        "object_id": world.object_a, "request_id": "df287872-c9f9-4f70-bf45-11719a430a99", field: "   ",
    }}
    assert world.client.post("/channels", json=body).status_code == 422
    body["table_setup"][field] = "  Verify orders  "
    created = world.client.post("/channels", json=body)
    assert created.status_code == 201
    draft = world.client.get(f"/channels/{created.json()['channel']['id']}/draft").json()
    assert "Verify orders" in [node["name"] for node in draft["graph"]["nodes"]]


def test_write_only_steward_can_edit_without_sync_table(world):
    role = create_role(get_role_store(), key="semantics_writer", name="Semantics writer",
                       permissions=["console:access", "metadata:write"])
    writer = _user("semantics_writer", role.id)
    create_membership(subject_type="user", subject_id=writer, target=world.source_a, level="steward")
    world.login("semantics_writer")
    response = world.client.patch(f"/objects/{world.object_a}/semantics", json={"business_name": "Orders"})
    assert response.status_code == 200, response.text
    assert response.json()["object"]["sync_table"] is None


def test_create_channel_from_table_retries_after_later_edit(world):
    world.login("viewer")
    body = {"name": "Orders workflow", "tags": {"names": ["Orders"]}, "table_setup": {
        "object_id": world.object_a, "request_id": "df287872-c9f9-4f70-bf45-11719a430a99",
    }}
    created = world.client.post("/channels", json=body)
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    url = f"/channels/{channel_id}/draft"
    graph = world.client.get(url).json()["graph"]
    trigger, read = graph["nodes"]
    assert trigger["type"] == "trigger.manual"
    assert read["type"] == "read.mirror"
    assert read["config"] == {"object_id": world.object_a, "freshness_policy": "fail"}
    edge, = graph["edges"]
    assert edge["source"] == {"node_id": trigger["id"], "port": "main"}
    assert edge["target"] == {"node_id": read["id"], "port": "main"}
    read["name"] = "Verify amount"
    assert world.client.put(url, json={"base_revision": 1, "graph": graph}).is_success
    assert world.client.post("/channels", json=body).json()["channel"]["id"] == channel_id
    assert world.client.get(url).json()["graph"]["nodes"][1]["name"] == "Verify amount"
    assert world.client.get("/mirrors").json()["items"] == []
    graph.update(nodes=[trigger], edges=[])
    saved = world.client.put(url, json={"base_revision": 2, "graph": graph})
    assert saved.is_success, saved.text
    published = world.client.post(f"/channels/{channel_id}/publish", json={"draft_revision": saved.json()["draft_revision"]})
    assert published.is_success, published.text
    current = world.client.get(f"/channels/{channel_id}").json()
    assert current["channel"]["latest_version"]["number"] == 1
    assert world.client.post("/channels", json=body).json() == current
    for action in ("channel.create", "tags.replace"):
        events, _ = get_audit_store().list_events(action=action, resource_type="channel")
        assert sum(event.resource_id == channel_id for event in events) == 1
    world.login("steward")
    other = world.client.post("/channels", json=body)
    assert other.status_code == 201 and other.json()["channel"]["id"] != channel_id
    world.login("viewer")
    apply_structure_snapshot(source=require_source(world.source_a), job_id="job_removed",
                             collected=[], schema_scope=None)
    assert world.client.get(f"/objects/{world.object_a}").json()["object"]["sync_table"] is None
    for object_id in (world.object_a, world.object_b, world.procedure_a):
        body["table_setup"]["object_id"] = object_id
        assert world.client.post("/channels", json=body).status_code == 404


def test_catalog_source_discovery_without_sources_administration(world: _World) -> None:
    world.login("viewer")
    assert world.client.get("/sources").status_code == 403
    response = world.client.get("/catalog/sources")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [world.source_a]
    assert set(response.json()["items"][0]) == {"id", "key", "name", "engine"}
    assert world.client.get("/catalog/sources", params={"source_id": world.source_b}).json()["total"] == 0
    world.login("hidden")
    assert world.client.get("/catalog/sources").json()["total"] == 0


def test_mirror_picker_filters_visible_engines_and_catalog_presence_before_paging(world: _World) -> None:
    source = require_source(world.source_a)
    mysql = get_source_store().create_source(replace(source, id="src_mysql", engine="mysql", key="mysql"))
    create_membership(subject_type="user", subject_id=world.users["viewer"], target=mysql.id, level="viewer")
    same_name = "page_orders"
    apply_structure_snapshot(
        source=mysql, job_id="mysql_structure", schema_scope=None,
        collected=[_obj(object_id="mysql_orders", name=same_name, source_id=mysql.id, source_key=mysql.key, engine="mysql")],
    )

    def pg_table(name: str, object_type: str = "table") -> CatalogObjectRecord:
        return _obj(object_id=name, name=name, source_id=source.id, source_key=source.key, object_type=object_type)

    present = [pg_table(same_name + "_a"), pg_table(same_name + "_b")]
    view = pg_table(same_name + "_view", object_type="view")
    apply_structure_snapshot(source=source, job_id="pg_before", schema_scope=None,
                             collected=[*present, view, pg_table(same_name)])
    apply_structure_snapshot(source=source, job_id="pg_after", schema_scope=None, collected=[*present, view])
    world.login("viewer")
    endpoint = "/catalog/objects/search"
    params = {"q": same_name, "limit": 1, "mirror_eligible": "true"}
    assert any(item["source_id"] == mysql.id
               for item in world.client.get(endpoint, params={"q": same_name}).json()["items"])
    for offset, names, more in [(0, [same_name + "_a"], True), (1, [same_name + "_b"], False), (2, [], False)]:
        response = world.client.get(endpoint, params={**params, "offset": offset})
        assert response.status_code == 200, response.text
        body = response.json()
        assert [(item["source_id"], item["name"]) for item in body["items"]] == [(source.id, name) for name in names]
        assert body["truncated"] is more
    assert world.client.get(endpoint, params={**params, "source_id": mysql.id}).json()["items"] == []
