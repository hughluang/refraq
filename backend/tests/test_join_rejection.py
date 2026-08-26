"""Join Rejection: writers, reconcilers, path, HTTP/MCP, audit."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

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
from backend.core.time import format_instant, utc_now  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.join_origin import SQL_LINEAGE_JOIN_ORIGIN  # noqa: E402
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.store import get_catalog_store, reset_catalog_store  # noqa: E402
from backend.metadata.catalog.structure_merge import build_structure_refresh_plan  # noqa: E402
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.join_detection_jobs.reconcile import build_join_detection_plan  # noqa: E402
from backend.metadata.join_detection_jobs.resolver import ResolvedJoin  # noqa: E402
from backend.metadata.join_detection_jobs.service import run_join_detection_job  # noqa: E402
from backend.metadata.mcp_server import patch_join as mcp_patch_join  # noqa: E402
from backend.metadata.mcp_server import reject_join as mcp_reject_join  # noqa: E402
from backend.metadata.mcp_server import restore_join as mcp_restore_join  # noqa: E402
from backend.metadata.mcp_server import upsert_joins as mcp_upsert_joins  # noqa: E402
from backend.metadata.sources.service import create_source, require_source  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.schedules import reset_schedule_store  # noqa: E402


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
    reset_schedule_store()
    reset_audit_store()
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


def _join(
    *,
    join_id: str,
    from_id: str,
    to_id: str,
    now: datetime,
    rejected: bool = False,
) -> CatalogJoinRecord:
    return CatalogJoinRecord(
        id=join_id,
        from_column_id=from_id,
        to_column_id=to_id,
        evidence="kept",
        join_kind="INNER",
        join_expression="a = b",
        created_by_user_id=None,
        created_at=now,
        rejected_at=now if rejected else None,
        rejected_by_user_id="u1" if rejected else None,
    )


def test_reconcile_skips_rejected_and_does_not_stale_delete() -> None:
    now = utc_now()
    existing = [
        _join(
            join_id="j_rejected",
            from_id="a",
            to_id="b",
            now=now,
            rejected=True,
        )
    ]
    plan = build_join_detection_plan(
        existing_joins=existing,
        resolved=[
            ResolvedJoin(
                from_column_id="a",
                to_column_id="b",
                join_kind="INNER",
                join_expression="a = b",
                host_locator_key="view/v",
            )
        ],
    )
    assert plan.upsert_joins == ()
    assert plan.skipped_rejected == 1
    stale = build_join_detection_plan(
        existing_joins=existing,
        resolved=[],
    )
    assert stale.skipped_rejected == 0


def test_structure_refresh_does_not_delete_or_overwrite_rejected_fk() -> None:
    now = utc_now()
    customers = CatalogObjectRecord(
        id="obj_customers",
        source_id="src_origin",
        locator_key="obj/postgresql/demo/public/table/customers",
        object_type="table",
        schema_name="public",
        name="customers",
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
                id="col_cust_id",
                object_id="obj_customers",
                locator_key="col/c/id",
                name="id",
                ordinal=0,
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
    orders = CatalogObjectRecord(
        id="obj_orders",
        source_id="src_origin",
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
        columns=[
            CatalogColumnRecord(
                id="col_ord_id",
                object_id="obj_orders",
                locator_key="col/o/id",
                name="id",
                ordinal=0,
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
            ),
            CatalogColumnRecord(
                id="col_cust_fk",
                object_id="obj_orders",
                locator_key="col/o/customer_id",
                name="customer_id",
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
            ),
        ],
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
    rejected = _join(
        join_id="j_rej",
        from_id="col_cust_fk",
        to_id="col_cust_id",
        now=now,
        rejected=True,
    )
    plan = build_structure_refresh_plan(
        source_id="src_origin",
        job_id="job_refresh",
        existing_objects=[customers, orders],
        existing_joins=[rejected],
        incoming=[customers, orders],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="demo",
        now=now,
    )
    assert plan.upsert_joins == ()


def test_http_reject_restore_amend_and_audit(client: TestClient) -> None:
    from backend.tests.test_catalog_semantics_joins import _make_source, _seed_object

    source = _make_source(client, key="reject-src")
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "guess"},
    )
    assert created.status_code == 201, created.text
    join_id = created.json()["join"]["id"]

    rejected = client.post(f"/joins/{join_id}/reject")
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()["join"]
    assert body["is_rejected"] is True
    assert "origin" not in body
    assert body["evidence"] == "guess"
    assert body["created_by_user_id"] is not None

    listed = client.get(f"/objects/{obj.id}/joins")
    assert listed.json()["items"][0]["is_rejected"] is True

    dup = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "again"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "JOIN_REJECTED"

    patched = client.patch(f"/joins/{join_id}", json={"evidence": "nope"})
    assert patched.status_code == 409
    assert patched.json()["code"] == "JOIN_REJECTED"

    restored = client.post(f"/joins/{join_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["join"]["is_rejected"] is False

    events, _ = get_audit_store().list_events(action="join.reject")
    assert events
    restored_events, _ = get_audit_store().list_events(action="join.restore")
    assert restored_events

    store = get_catalog_store()
    changes = store.list_join_changes(from_column_id=a, to_column_id=b)
    assert [c.kind for c in changes] == ["create", "reject", "restore"]
    assert changes[0].attester == "human"


def test_amend_keeps_created_by_and_appends_join_change(client: TestClient) -> None:
    from backend.tests.test_catalog_semantics_joins import _make_source, _seed_object

    source = _make_source(client, key="amend-src")
    obj = _seed_object(source["id"])
    store = get_catalog_store()
    a, b = obj.columns[0].id, obj.columns[1].id
    auto = store.write_insert_join(
        from_column_id=a,
        to_column_id=b,
        evidence="SQL join in v",
        created_by_user_id=None,
        attester=SQL_LINEAGE_JOIN_ORIGIN,
    ).record
    patched = client.patch(
        f"/joins/{auto.id}",
        json={"evidence": "operator confirmed", "join_kind": "INNER"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()["join"]
    assert "origin" not in body
    assert body["evidence"] == "operator confirmed"
    assert body["created_by_user_id"] is None
    changes = store.list_join_changes(from_column_id=a, to_column_id=b)
    assert [c.kind for c in changes] == ["create", "amend"]
    assert changes[0].attester == SQL_LINEAGE_JOIN_ORIGIN
    assert changes[1].attester is None
    refused = client.delete(f"/joins/{auto.id}")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "JOIN_DELETE_AUTOMATIC"


def test_join_detection_counts_skipped_rejected(client: TestClient) -> None:
    source = create_source(
        key="detect-rej",
        name="Detect",
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
    now = utc_now()

    def column(object_id: str, name: str) -> CatalogColumnRecord:
        return CatalogColumnRecord(
            id=f"col_{object_id}_{name}",
            object_id=object_id,
            locator_key=f"col/{object_id}/{name}",
            name=name,
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

    def obj(
        object_id: str,
        name: str,
        object_type: str,
        ddl: str | None,
        columns: list[CatalogColumnRecord],
    ) -> CatalogObjectRecord:
        return CatalogObjectRecord(
            id=object_id,
            source_id=source.id,
            locator_key=f"obj/postgresql/detect-rej/public/{object_type}/{name}",
            object_type=object_type,
            schema_name="public",
            name=name,
            ddl=ddl,
            comment=None,
            primary_key=["id"] if object_type == "table" else None,
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
            columns=columns,
        )

    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[
            obj(
                "obj_orders",
                "orders",
                "table",
                None,
                [column("obj_orders", "id"), column("obj_orders", "customer_id")],
            ),
            obj(
                "obj_customers",
                "customers",
                "table",
                None,
                [column("obj_customers", "id")],
            ),
            obj(
                "obj_view",
                "v_open",
                "view",
                "CREATE VIEW v_open AS SELECT * FROM orders o "
                "JOIN customers c ON o.customer_id = c.id",
                [],
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    store = get_catalog_store()
    planted = store.write_insert_join(
        from_column_id="col_obj_orders_customer_id",
        to_column_id="col_obj_customers_id",
        evidence="SQL join in v_open",
        created_by_user_id=None,
        attester=SQL_LINEAGE_JOIN_ORIGIN,
    ).record
    store.set_join_rejection(
        planted.id, rejected_at=utc_now(), rejected_by_user_id="u1"
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["joins_skipped_rejected"] == 1
    assert stored.result["joins_upserted"] == 0
    listed, total = store.list_joins_for_object("obj_orders")
    assert total == 1
    assert listed[0].is_rejected is True

    store.set_join_rejection(
        planted.id, rejected_at=None, rejected_by_user_id=None
    )
    store.delete_join(planted.id)
    second = create_queued_job(kind="join_detection", input={"source_id": source.id})
    again = run_join_detection_job(second.id)
    assert again["status"] == "succeeded"
    listed2, total2 = store.list_joins_for_object("obj_orders")
    assert total2 == 1
    assert listed2[0].is_rejected is False


def test_mcp_reject_and_restore(client: TestClient) -> None:
    from backend.tests.test_catalog_semantics_joins import _make_source, _seed_object

    source = _make_source(client, key="mcp-rej")
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "guess"},
    )
    join_id = created.json()["join"]["id"]
    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "rej-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]
    rejected = json.loads(
        mcp_reject_join(authorization=f"Bearer {secret}", join_id=join_id)
    )
    assert rejected["join"]["is_rejected"] is True
    restored = json.loads(
        mcp_restore_join(authorization=f"Bearer {secret}", join_id=join_id)
    )
    assert restored["join"]["is_rejected"] is False


def test_batch_reports_rejected_and_asserted_known(client: TestClient) -> None:
    from backend.tests.test_catalog_semantics_joins import _make_source, _seed_object

    source = _make_source(client, key="batch-rej")
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "original"},
    )
    assert created.status_code == 201, created.text
    join_id = created.json()["join"]["id"]

    asserted = client.post(
        "/joins:batch",
        json={
            "joins": [
                {
                    "from_column_id": a,
                    "to_column_id": b,
                    "evidence": "retry-asserted",
                }
            ]
        },
    )
    assert asserted.status_code == 200, asserted.text
    assert asserted.json()["created_count"] == 0
    assert asserted.json()["already_known_count"] == 1
    assert asserted.json()["rejected_count"] == 0
    assert asserted.json()["items"][0]["is_rejected"] is False
    assert asserted.json()["items"][0]["evidence"] == "original"

    rejected = client.post(f"/joins/{join_id}/reject")
    assert rejected.status_code == 200, rejected.text

    batch = client.post(
        "/joins:batch",
        json={
            "joins": [
                {
                    "from_column_id": a,
                    "to_column_id": b,
                    "evidence": "should-not-overwrite",
                }
            ]
        },
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()
    assert body["created_count"] == 0
    assert body["already_known_count"] == 0
    assert body["rejected_count"] == 1
    assert body["items"][0]["id"] == join_id
    assert body["items"][0]["is_rejected"] is True
    assert body["items"][0]["evidence"] == "original"

    single = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "single"},
    )
    assert single.status_code == 409
    assert single.json()["code"] == "JOIN_REJECTED"


def test_mcp_upsert_joins_reports_rejected_then_restore_patch(
    client: TestClient,
) -> None:
    from backend.tests.test_catalog_semantics_joins import _make_source, _seed_object

    source = _make_source(client, key="mcp-batch-rej")
    obj = _seed_object(source["id"])
    a, b = obj.columns[0].id, obj.columns[1].id
    created = client.post(
        "/joins",
        json={"from_column_id": a, "to_column_id": b, "evidence": "guess"},
    )
    join_id = created.json()["join"]["id"]
    client.post(f"/joins/{join_id}/reject")

    expires = format_instant(utc_now() + timedelta(days=7))
    tok = client.post("/tokens", json={"name": "batch-rej-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    secret = tok.json()["secret"]
    auth = f"Bearer {secret}"

    reported = json.loads(
        mcp_upsert_joins(
            authorization=auth,
            joins=[
                {
                    "from_column_id": a,
                    "to_column_id": b,
                    "evidence": "agent-still-thinks-valid",
                }
            ],
        )
    )
    assert reported["created_count"] == 0
    assert reported["already_known_count"] == 0
    assert reported["rejected_count"] == 1
    assert reported["items"][0]["id"] == join_id
    assert reported["items"][0]["is_rejected"] is True
    assert reported["items"][0]["evidence"] == "guess"

    blocked = json.loads(
        mcp_patch_join(
            authorization=auth,
            join_id=join_id,
            evidence="too-soon",
        )
    )
    assert blocked["error"]["code"] == "JOIN_REJECTED"

    restored = json.loads(mcp_restore_join(authorization=auth, join_id=join_id))
    assert restored["join"]["is_rejected"] is False

    patched = json.loads(
        mcp_patch_join(
            authorization=auth,
            join_id=join_id,
            evidence="agent-confirmed",
        )
    )
    assert patched["join"]["evidence"] == "agent-confirmed"
    assert patched["join"]["is_rejected"] is False

    known = json.loads(
        mcp_upsert_joins(
            authorization=auth,
            joins=[
                {
                    "from_column_id": a,
                    "to_column_id": b,
                    "evidence": "will-not-overwrite",
                }
            ],
        )
    )
    assert known["already_known_count"] == 1
    assert known["rejected_count"] == 0
    assert known["items"][0]["evidence"] == "agent-confirmed"