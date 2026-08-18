"""Canonical native type and Type Mapping entity (ADR 0024)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store, reset_audit_store  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.normalized_type import canonicalize_native_type  # noqa: E402
from backend.metadata.catalog.service import ColumnView, column_view_as_dict  # noqa: E402
from backend.metadata.catalog.store import get_catalog_store  # noqa: E402
from backend.metadata.connectors.base import (  # noqa: E402
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
)
from backend.metadata.structure_jobs.service import run_structure_job  # noqa: E402
from backend.metadata.sources.service import create_source  # noqa: E402
from backend.metadata.type_mappings.seeds import (  # noqa: E402
    ensure_product_type_mappings,
)
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
)
from backend.metadata.type_mappings.service import (  # noqa: E402
    assign_normalized_types,
    patch_mapping,
    resolve_normalized_type,
)
from backend.metadata.type_mappings.store import (  # noqa: E402
    TypeMappingRecord,
    get_type_mapping_store,
    new_type_mapping_id,
    reset_type_mapping_store,
)


def test_canonicalize_strips_every_paren_group() -> None:
    assert canonicalize_native_type("varchar(50)") == "varchar"
    assert canonicalize_native_type("varchar(100)") == "varchar"
    assert canonicalize_native_type("character varying(50)") == "character varying"
    assert canonicalize_native_type("TIMESTAMP(6) WITH TIME ZONE") == (
        "timestamp with time zone"
    )
    assert canonicalize_native_type("INTERVAL YEAR(2) TO MONTH") == (
        "interval year to month"
    )
    assert canonicalize_native_type("NUMBER(10,2)") == "number"
    assert canonicalize_native_type("integer[]") == "integer[]"
    assert canonicalize_native_type("  Double   Precision  ") == "double precision"
    assert canonicalize_native_type("") == ""
    assert canonicalize_native_type("   ") == ""


def test_empty_data_type_is_unknown_without_insert() -> None:
    reset_type_mapping_store()
    assert resolve_normalized_type(engine="postgresql", data_type="") == "unknown"
    assert resolve_normalized_type(engine="postgresql", data_type="  ") == "unknown"
    items, total = get_type_mapping_store().list_mappings()
    assert total == 0
    assert items == []


def test_missing_engine_is_implementation_error() -> None:
    with pytest.raises(ValueError, match="engine is required"):
        resolve_normalized_type(engine="", data_type="integer")


def test_job_inserts_unknown_and_does_not_overwrite() -> None:
    reset_type_mapping_store()
    assert resolve_normalized_type(engine="postgresql", data_type="geometry") == (
        "unknown"
    )
    store = get_type_mapping_store()
    row = store.get_by_key("postgresql", "geometry")
    assert row is not None
    assert row.origin == "job"
    store.save(
        TypeMappingRecord(
            id=row.id,
            engine=row.engine,
            native_type=row.native_type,
            normalized_type="binary",
            origin="user",
            created_at=row.created_at,
            updated_at=utc_now(),
        )
    )
    assert resolve_normalized_type(engine="postgresql", data_type="geometry") == (
        "binary"
    )
    again = store.get_by_key("postgresql", "geometry")
    assert again is not None
    assert again.origin == "user"
    assert again.normalized_type == "binary"


def test_insert_if_absent_keeps_first_row() -> None:
    reset_type_mapping_store()
    store = get_type_mapping_store()
    now = utc_now()
    first = store.insert_if_absent(
        TypeMappingRecord(
            id=new_type_mapping_id(),
            engine="postgresql",
            native_type="geometry",
            normalized_type="unknown",
            origin="job",
            created_at=now,
            updated_at=now,
        )
    )
    second = store.insert_if_absent(
        TypeMappingRecord(
            id=new_type_mapping_id(),
            engine="postgresql",
            native_type="geometry",
            normalized_type="string",
            origin="job",
            created_at=now,
            updated_at=now,
        )
    )
    assert second.id == first.id
    assert second.normalized_type == "unknown"


def test_upgrade_occupies_and_takes_over_job_row() -> None:
    reset_type_mapping_store()
    store = get_type_mapping_store()
    now = utc_now()
    inserted = store.create(
        TypeMappingRecord(
            id=new_type_mapping_id(),
            engine="postgresql",
            native_type="integer",
            normalized_type="unknown",
            origin="job",
            created_at=now,
            updated_at=now,
        )
    )
    ensure_product_type_mappings()
    taken = store.get_by_key("postgresql", "integer")
    assert taken is not None
    assert taken.id == inserted.id
    assert taken.origin == "product"
    assert taken.normalized_type == "integer"
    ensure_product_type_mappings()
    again = store.get_by_key("postgresql", "integer")
    assert again is not None
    assert again.id == inserted.id


def test_seeded_aliases_are_distinct_keys() -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    store = get_type_mapping_store()
    varchar = store.get_by_key("postgresql", "varchar")
    varying = store.get_by_key("postgresql", "character varying")
    assert varchar is not None and varying is not None
    assert varchar.id != varying.id
    assert canonicalize_native_type("varchar(50)") == "varchar"
    assert canonicalize_native_type("character varying(100)") == "character varying"


def test_assign_normalized_types_resolves_distinct_canonicals() -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    now = utc_now()

    def _col(name: str, data_type: str, ordinal: int) -> CatalogColumnRecord:
        return CatalogColumnRecord(
            id=f"col_{name}",
            object_id="obj_1",
            locator_key=f"col/{name}",
            name=name,
            ordinal=ordinal,
            data_type=data_type,
            nullable=True,
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

    incoming = [
        CatalogObjectRecord(
            id="obj_1",
            source_id="src_1",
            locator_key="obj/mssql/s/dbo/table/t",
            object_type="table",
            schema_name="dbo",
            name="t",
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
                _col("id", "int", 1),
                _col("code", "varchar(50)", 2),
                _col("note", "varchar(200)", 3),
                _col("shape", "geometry", 4),
                _col("blank", "", 5),
            ],
        )
    ]
    assigned = assign_normalized_types(incoming, engine="mssql")
    types = {c.name: c.normalized_type for c in assigned[0].columns}
    assert types["id"] == "integer"
    assert types["code"] == "string"
    assert types["note"] == "string"
    assert types["shape"] == "unknown"
    assert types["blank"] == "unknown"
    store = get_type_mapping_store()
    assert store.get_by_key("mssql", "geometry") is not None
    assert store.get_by_key("mssql", "") is None


def test_homonym_seeds() -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    assert resolve_normalized_type(engine="mssql", data_type="bit") == "boolean"
    assert resolve_normalized_type(engine="postgresql", data_type="bit(8)") == "binary"
    assert resolve_normalized_type(engine="oracle", data_type="DATE") == "timestamp"
    assert resolve_normalized_type(engine="oracle", data_type="LONG") == "string"
    assert resolve_normalized_type(engine="oracle", data_type="LONG RAW") == "binary"
    assert resolve_normalized_type(engine="oracle", data_type="NUMBER(10)") == "number"
    assert resolve_normalized_type(engine="postgresql", data_type="time") == "time"
    assert resolve_normalized_type(engine="postgresql", data_type="integer[]") == "array"


def test_mcp_column_payload_omits_normalized_type() -> None:
    payload = column_view_as_dict(
        ColumnView(
            id="c1",
            locator_key="col/postgresql/s/public/table/t/column/id",
            name="id",
            data_type="integer",
            normalized_type="integer",
            nullable=False,
            default_value=None,
            comment=None,
            business_name=None,
            business_description=None,
            column_semantics=None,
            enum_catalog=None,
            semantic_source=None,
            field_kind="column",
            ordinal=1,
            is_present=True,
        )
    )
    assert "normalized_type" not in payload
    assert payload["data_type"] == "integer"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_audit_store()
    reset_type_mapping_store()
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    ensure_product_type_mappings()
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        yield test_client


def test_http_list_and_patch_non_seed(client: TestClient) -> None:
    listed = client.get("/type-mappings", params={"engine": "postgresql", "limit": 500})
    assert listed.status_code == 200, listed.text
    seeds = listed.json()["items"]
    assert any(i["origin"] == "product" and i["native_type"] == "integer" for i in seeds)

    seed_id = next(i["id"] for i in seeds if i["native_type"] == "integer")
    blocked = client.patch(
        f"/type-mappings/{seed_id}", json={"normalized_type": "string"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "TYPE_MAPPING_SEED_IMMUTABLE"

    resolve_normalized_type(engine="postgresql", data_type="geometry")
    job_rows = client.get(
        "/type-mappings", params={"q": "geometry", "origin": "job"}
    )
    assert job_rows.status_code == 200
    geo = job_rows.json()["items"][0]
    assert geo["normalized_type"] == "unknown"

    unknown_patch = client.patch(
        f"/type-mappings/{geo['id']}", json={"normalized_type": "unknown"}
    )
    assert unknown_patch.status_code == 400
    assert unknown_patch.json()["code"] == "TYPE_MAPPING_UNKNOWN_FORBIDDEN"

    patched = client.patch(
        f"/type-mappings/{geo['id']}", json={"normalized_type": "binary"}
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()["mapping"]
    assert body["normalized_type"] == "binary"
    assert body["origin"] == "user"

    events, _cursor = get_audit_store().list_events(resource_type="type_mapping")
    assert any(e.action == "type_mapping.patch" for e in events)


def test_patch_seed_via_service_raises() -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    row = get_type_mapping_store().get_by_key("postgresql", "text")
    assert row is not None
    from backend.metadata.errors import TypeMappingSeedImmutable

    with pytest.raises(TypeMappingSeedImmutable):
        patch_mapping(
            mapping_id=row.id,
            normalized_type="string",
            actor_user_id="u1",
            actor_token_id=None,
        )


def test_job_insert_does_not_write_audit() -> None:
    reset_type_mapping_store()
    reset_audit_store()
    resolve_normalized_type(engine="postgresql", data_type="geometry")
    assert get_audit_store().list_events(resource_type="type_mapping")[0] == []


class _FakeConnector:
    engine = "postgresql"

    def collect_structure(self, endpoint, progress=None) -> CollectedStructure:  # noqa: ANN001
        return CollectedStructure(
            objects=[
                CollectedObject(
                    schema_name="public",
                    name="places",
                    object_type="table",
                    columns=[
                        CollectedColumn(
                            name="id", ordinal=1, data_type="integer", nullable=False
                        ),
                        CollectedColumn(
                            name="geom",
                            ordinal=2,
                            data_type="geometry",
                            nullable=True,
                        ),
                    ],
                    primary_key=["id"],
                )
            ]
        )


def test_structure_job_warns_unknown_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_type_mapping_store()
    ensure_product_type_mappings()
    source = create_source(
        key="geo-src",
        name="Geo",
        kind="database",
        description=None,
        engine="postgresql",
        access={
            "host": "127.0.0.1",
            "port": 5432,
            "username": "u",
            "password": "p",
            "ssl_mode": "require",
            "database": "MES",
            "schema": "public",
            "extra": {},
        },
    )
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _FakeConnector(),
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    out = run_structure_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert "WARN" in stored.log_body
    assert "columns mapped to unknown" in stored.log_body
    assert "geom" in stored.log_body
    assert stored.result is not None
    assert "unknown" not in stored.result.get("counts", {})

    objects = get_catalog_store().list_present_for_source(source.id)
    cols = {c.name: c.normalized_type for o in objects for c in o.columns}
    assert cols["id"] == "integer"
    assert cols["geom"] == "unknown"
