"""Join detection parser, resolver, reconciliation, and Job execution."""

from __future__ import annotations

import os
from datetime import datetime

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
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    create_queued_job,
    get_job_store,
    reset_job_store,
)
from backend.main import app  # noqa: E402
from backend.metadata.catalog.join_origin import SQL_LINEAGE_JOIN_ORIGIN  # noqa: E402
from backend.metadata.catalog.records import (  # noqa: E402
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.store import get_catalog_store, reset_catalog_store  # noqa: E402
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.join_detection_jobs.parser import parse_definition_joins  # noqa: E402
from backend.metadata.join_detection_jobs.reconcile import (  # noqa: E402
    build_join_detection_plan,
)
from backend.metadata.join_detection_jobs.resolver import CatalogJoinResolver  # noqa: E402
from backend.metadata.join_detection_jobs.service import run_join_detection_job  # noqa: E402
from backend.metadata.sources.service import create_source, require_source  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.worker.schedules import reset_schedule_store  # noqa: E402


def _pairs(leaves: list) -> set[tuple[str, str, str, str]]:
    return {
        (leaf.left_table, leaf.left_column, leaf.right_table, leaf.right_column)
        for leaf in leaves
    }


def test_parser_explicit_and_implicit_equi_joins() -> None:
    explicit = parse_definition_joins(
        "CREATE VIEW v AS SELECT * FROM orders o "
        "JOIN customers c ON o.customer_id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert explicit.fragment_errors == 0
    assert _pairs(explicit.leaves) == {("orders", "customer_id", "customers", "id")}

    implicit = parse_definition_joins(
        "SELECT * FROM orders o, customers c WHERE o.customer_id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert implicit.fragment_errors == 0
    assert _pairs(implicit.leaves) == {("orders", "customer_id", "customers", "id")}
    assert implicit.leaves[0].join_kind == "IMPLICIT"


def test_parser_qualify_failure_counts_as_parse_error() -> None:
    parsed = parse_definition_joins(
        "SELECT * JOIN u ON 1=1",
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.parse_errors == 1
    assert parsed.tokenize_errors == 0
    assert parsed.leaves == []


def test_parser_skips_comments_and_does_not_infer_from_names() -> None:
    parsed = parse_definition_joins(
        """
        CREATE VIEW v AS
        SELECT *
        FROM orders o -- join customers later
        JOIN items i ON o.id = i.order_id
        /* o.customer_id = customers.id */
        """,
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.fragment_errors == 0
    assert _pairs(parsed.leaves) == {("orders", "id", "items", "order_id")}

    named = parse_definition_joins(
        "SELECT * FROM orders o CROSS JOIN customers c",
        engine="postgresql",
        default_schema="public",
    )
    assert named.fragment_errors == 0
    assert named.leaves == []


def test_parser_tsql_and_oracle_aliases() -> None:
    tsql = parse_definition_joins(
        "SELECT * FROM [dbo].[orders] o INNER JOIN [dbo].[customers] c "
        "ON o.customer_id = c.id",
        engine="mssql",
        default_schema="dbo",
    )
    assert tsql.fragment_errors == 0
    assert _pairs(tsql.leaves) == {("orders", "customer_id", "customers", "id")}

    oracle = parse_definition_joins(
        'SELECT * FROM "ORDERS" o JOIN "CUSTOMERS" c ON o.cust_id = c.id',
        engine="oracle",
        default_schema="HR",
    )
    assert oracle.fragment_errors == 0
    assert {leaf.left_column.lower() for leaf in oracle.leaves} == {"cust_id"}


def test_parser_multi_statement_routine_and_malformed() -> None:
    parsed = parse_definition_joins(
        """
        CREATE PROCEDURE refresh_orders AS
        BEGIN
          SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id;
          SELECT * FROM orders o JOIN items i ON o.id = i.order_id;
        END
        """,
        engine="mssql",
        default_schema="dbo",
    )
    assert parsed.fragment_errors == 0
    assert _pairs(parsed.leaves) == {
        ("orders", "customer_id", "customers", "id"),
        ("orders", "id", "items", "order_id"),
    }

    malformed = parse_definition_joins(
        "SELECT FROM",
        engine="postgresql",
        default_schema="public",
    )
    assert malformed.parse_errors >= 1
    assert malformed.tokenize_errors == 0


def test_parser_token_error_keeps_other_fragments() -> None:
    parsed = parse_definition_joins(
        """
        CREATE PROCEDURE refresh_orders AS
        BEGIN
          SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id;
          SELECT * FROM items WHERE name = 'unclosed
        END
        """,
        engine="mssql",
        default_schema="dbo",
    )
    assert _pairs(parsed.leaves) == {("orders", "customer_id", "customers", "id")}
    assert parsed.tokenize_errors >= 1
    assert parsed.parse_errors == 0


def test_resolver_skips_unresolved_endpoints() -> None:
    now = utc_now()
    objects = [
        CatalogObjectRecord(
            id="obj_orders",
            source_id="src_1",
            locator_key="obj/postgresql/s/public/table/orders",
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
            last_structure_job_id=None,
            collected_at=now,
            created_at=now,
            updated_at=now,
            columns=[
                CatalogColumnRecord(
                    id="col_orders_id",
                    object_id="obj_orders",
                    locator_key="col/orders/id",
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
    ]
    resolver = CatalogJoinResolver(objects)
    parsed = parse_definition_joins(
        "SELECT * FROM orders o JOIN customers c ON o.id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.leaves
    outcome = resolver.resolve_leaf(parsed.leaves[0], host_locator_key="view/v")
    assert outcome.join is None
    assert outcome.reason is not None


def _join(
    *,
    join_id: str,
    from_id: str,
    to_id: str,
    now: datetime,
    created_by_user_id: str | None = None,
) -> CatalogJoinRecord:
    return CatalogJoinRecord(
        id=join_id,
        from_column_id=from_id,
        to_column_id=to_id,
        evidence="kept",
        join_kind="INNER",
        join_expression="a = b",
        created_by_user_id=created_by_user_id,
        created_at=now,
    )


def test_reconcile_skips_existing_and_inserts_missing() -> None:
    from backend.metadata.join_detection_jobs.resolver import ResolvedJoin

    now = utc_now()
    existing = [
        _join(join_id="j_stale", from_id="a", to_id="b", now=now),
        _join(join_id="j_fk", from_id="c", to_id="d", now=now),
        _join(
            join_id="j_human",
            from_id="e",
            to_id="f",
            now=now,
            created_by_user_id="u1",
        ),
    ]
    resolved = [
        ResolvedJoin(
            from_column_id="c",
            to_column_id="d",
            join_kind="INNER",
            join_expression="c = d",
            host_locator_key="view/v",
        ),
        ResolvedJoin(
            from_column_id="e",
            to_column_id="f",
            join_kind="INNER",
            join_expression="e = f",
            host_locator_key="view/v",
        ),
        ResolvedJoin(
            from_column_id="g",
            to_column_id="h",
            join_kind="INNER",
            join_expression="g = h",
            host_locator_key="view/v",
        ),
    ]
    plan = build_join_detection_plan(
        existing_joins=existing,
        resolved=resolved,
    )
    assert plan.skipped_protected == 2
    assert plan.skipped_rejected == 0
    assert [(u.from_column_id, u.to_column_id) for u in plan.upsert_joins] == [
        ("g", "h")
    ]


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


def _source():
    return create_source(
        key="join-src",
        name="Join",
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


def _column(object_id: str, name: str, *, now: datetime) -> CatalogColumnRecord:
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


def _object(
    *,
    object_id: str,
    source_id: str,
    name: str,
    object_type: str,
    ddl: str | None,
    columns: list[CatalogColumnRecord],
    now: datetime,
    schema_name: str = "public",
) -> CatalogObjectRecord:
    return CatalogObjectRecord(
        id=object_id,
        source_id=source_id,
        locator_key=f"obj/postgresql/join-src/{schema_name}/{object_type}/{name}",
        object_type=object_type,
        schema_name=schema_name,
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


def _seed_join_catalog(source) -> None:
    now = utc_now()
    orders = _object(
        object_id="obj_orders",
        source_id=source.id,
        name="orders",
        object_type="table",
        ddl=None,
        columns=[
            _column("obj_orders", "id", now=now),
            _column("obj_orders", "customer_id", now=now),
        ],
        now=now,
    )
    customers = _object(
        object_id="obj_customers",
        source_id=source.id,
        name="customers",
        object_type="table",
        ddl=None,
        columns=[_column("obj_customers", "id", now=now)],
        now=now,
    )
    view = _object(
        object_id="obj_view",
        source_id=source.id,
        name="v_open",
        object_type="view",
        ddl=(
            "CREATE VIEW v_open AS SELECT * FROM orders o "
            "JOIN customers c ON o.customer_id = c.id"
        ),
        columns=[],
        now=now,
    )
    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[orders, customers, view],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )


def test_join_detection_job_writes_sql_lineage(client: TestClient) -> None:
    source = _source()
    _seed_join_catalog(source)
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["schema"] == "join_detection.v1"
    assert stored.result["joins_upserted"] == 1
    assert stored.result["objects_eligible"] == 1
    store = get_catalog_store()
    joins, total = store.list_joins_for_object("obj_orders")
    assert total == 1
    assert joins[0].created_by_user_id is None
    assert "v_open" in joins[0].evidence
    changes = store.list_join_changes(
        from_column_id=joins[0].from_column_id,
        to_column_id=joins[0].to_column_id,
    )
    assert len(changes) == 1
    assert changes[0].attester == SQL_LINEAGE_JOIN_ORIGIN

    second = create_queued_job(kind="join_detection", input={"source_id": source.id})
    again = run_join_detection_job(second.id)
    assert again["status"] == "succeeded"
    stored2 = get_job_store().get(second.id)
    assert stored2 is not None
    assert stored2.result["joins_upserted"] == 0
    assert stored2.result["joins_skipped_protected"] == 1
    assert stored2.result["joins_deleted_stale"] == 0
    assert len(
        store.list_join_changes(
            from_column_id=joins[0].from_column_id,
            to_column_id=joins[0].to_column_id,
        )
    ) == 1


def test_join_detection_warns_on_unresolved_endpoints(client: TestClient) -> None:
    source = _source()
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[
            _object(
                object_id="obj_orders",
                source_id=source.id,
                name="orders",
                object_type="table",
                ddl=None,
                columns=[_column("obj_orders", "customer_id", now=now)],
                now=now,
            ),
            _object(
                object_id="obj_view",
                source_id=source.id,
                name="v_open",
                object_type="view",
                ddl=(
                    "CREATE VIEW v_open AS SELECT * FROM orders o "
                    "JOIN customers c ON o.customer_id = c.id"
                ),
                columns=[],
                now=now,
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["joins_skipped_unresolved"] >= 1
    assert stored.result["joins_upserted"] == 0
    assert "WARN" in (stored.log_body or "")
    assert "unresolved join endpoints" in (stored.log_body or "")


def test_join_detection_token_error_does_not_fail_job(client: TestClient) -> None:
    source = _source()
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[
            _object(
                object_id="obj_orders",
                source_id=source.id,
                name="orders",
                object_type="table",
                ddl=None,
                columns=[
                    _column("obj_orders", "id", now=now),
                    _column("obj_orders", "customer_id", now=now),
                ],
                now=now,
            ),
            _object(
                object_id="obj_customers",
                source_id=source.id,
                name="customers",
                object_type="table",
                ddl=None,
                columns=[_column("obj_customers", "id", now=now)],
                now=now,
            ),
            _object(
                object_id="obj_proc",
                source_id=source.id,
                name="refresh_orders",
                object_type="procedure",
                ddl=(
                    "CREATE PROCEDURE refresh_orders AS\n"
                    "BEGIN\n"
                    "  SELECT * FROM orders o JOIN customers c "
                    "ON o.customer_id = c.id;\n"
                    "  SELECT * FROM items WHERE name = 'unclosed\n"
                    "END"
                ),
                columns=[],
                now=now,
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["schema"] == "join_detection.v1"
    assert stored.result["objects_eligible"] == 1
    assert stored.result["objects_parsed"] == 1
    assert stored.result["objects_parse_failed"] == 1
    assert stored.result["joins_upserted"] == 1
    log = stored.log_body or ""
    assert "cannot tokenize ×1" in log
    assert "obj/postgresql/join-src/public/procedure/refresh_orders" in log
    assert "succeeded eligible=1 parsed=1 parse_failed=1 upserted=1" in log
    joins, total = get_catalog_store().list_joins_for_object("obj_orders")
    assert total == 1
    assert joins[0].created_by_user_id is None


def test_join_detection_skips_empty_ddl(client: TestClient) -> None:
    source = _source()
    _seed_join_catalog(source)
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_seed_empty",
        collected=[
            _object(
                object_id="obj_orders",
                source_id=source.id,
                name="orders",
                object_type="table",
                ddl=None,
                columns=[
                    _column("obj_orders", "id", now=now),
                    _column("obj_orders", "customer_id", now=now),
                ],
                now=now,
            ),
            _object(
                object_id="obj_customers",
                source_id=source.id,
                name="customers",
                object_type="table",
                ddl=None,
                columns=[_column("obj_customers", "id", now=now)],
                now=now,
            ),
            _object(
                object_id="obj_view",
                source_id=source.id,
                name="v_open",
                object_type="view",
                ddl=(
                    "CREATE VIEW v_open AS SELECT * FROM orders o "
                    "JOIN customers c ON o.customer_id = c.id"
                ),
                columns=[],
                now=now,
            ),
            _object(
                object_id="obj_fn",
                source_id=source.id,
                name="fn_encrypted",
                object_type="function",
                ddl=None,
                columns=[],
                now=now,
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["objects_eligible"] == 1


def test_tombstoned_host_does_not_delete_sql_lineage_join(client: TestClient) -> None:
    source = _source()
    _seed_join_catalog(source)
    first = create_queued_job(kind="join_detection", input={"source_id": source.id})
    assert run_join_detection_job(first.id)["status"] == "succeeded"
    joins, total = get_catalog_store().list_joins_for_object("obj_orders")
    assert total == 1
    join_id = joins[0].id

    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_tombstone",
        collected=[
            _object(
                object_id="obj_orders",
                source_id=source.id,
                name="orders",
                object_type="table",
                ddl=None,
                columns=[
                    _column("obj_orders", "id", now=now),
                    _column("obj_orders", "customer_id", now=now),
                ],
                now=now,
            ),
            _object(
                object_id="obj_customers",
                source_id=source.id,
                name="customers",
                object_type="table",
                ddl=None,
                columns=[_column("obj_customers", "id", now=now)],
                now=now,
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    listed, _ = get_catalog_store().list_objects(source.id, include_absent=True)
    host = next(obj for obj in listed if obj.name == "v_open")
    assert host.is_present is False
    present = get_catalog_store().list_present_for_source(source.id)
    assert all(obj.name != "v_open" for obj in present)

    second = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(second.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(second.id)
    assert stored is not None
    assert stored.result["joins_deleted_stale"] == 0
    joins, total = get_catalog_store().list_joins_for_object("obj_orders")
    assert total == 1
    assert joins[0].id == join_id


def test_join_detection_job_disabled_source(client: TestClient) -> None:
    source = _source()
    from backend.metadata.sources.store import get_source_store
    from dataclasses import replace

    store = get_source_store()
    store.save_source(replace(require_source(source.id), status="disabled"))
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_SOURCE_DISABLED"


def test_join_detection_same_kind_lock_blocks(client: TestClient) -> None:
    from backend.metadata.source_job_runner import try_acquire_kind_execution_lock

    source = _source()
    held = try_acquire_kind_execution_lock("join_detection", source.id)
    assert held is not None
    try:
        job = create_queued_job(kind="join_detection", input={"source_id": source.id})
        out = run_join_detection_job(job.id)
        assert out["status"] == "failed"
        assert out["error_code"] == "JOB_ALREADY_ACTIVE"
        stored = get_job_store().get(job.id)
        assert stored is not None
        assert "join_detection Kind execution lock" in (stored.error_summary or "")
    finally:
        held.release()


def test_join_detection_runs_while_structure_lock_held(client: TestClient) -> None:
    from backend.metadata.source_job_runner import try_acquire_kind_execution_lock

    source = _source()
    _seed_join_catalog(source)
    held = try_acquire_kind_execution_lock("structure", source.id)
    assert held is not None
    try:
        job = create_queued_job(kind="join_detection", input={"source_id": source.id})
        out = run_join_detection_job(job.id)
        assert out.get("error_code") != "JOB_ALREADY_ACTIVE"
        assert out["status"] == "succeeded"
    finally:
        held.release()


def test_structure_runs_while_join_detection_lock_held(client: TestClient) -> None:
    from backend.metadata.source_job_runner import try_acquire_kind_execution_lock
    from backend.metadata.structure_jobs.service import run_structure_job

    source = _source()
    held = try_acquire_kind_execution_lock("join_detection", source.id)
    assert held is not None
    try:
        job = create_queued_job(kind="structure", input={"source_id": source.id})
        out = run_structure_job(job.id)
        # May fail for connector/access reasons in this fixture, but not kind lock.
        assert out.get("error_code") != "JOB_ALREADY_ACTIVE"
    finally:
        held.release()


def test_join_detection_persist_failure_leaves_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source()
    _seed_join_catalog(source)
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})

    def boom(self, plan) -> int:  # noqa: ANN001
        raise RuntimeError("persist failed")

    monkeypatch.setattr(
        "backend.metadata.catalog.store.memory._MemoryStructureWrite.persist_join_detection_plan",
        boom,
    )
    out = run_join_detection_job(job.id)
    assert out["status"] == "failed"
    joins, total = get_catalog_store().list_joins_for_object("obj_orders")
    assert total == 0
    assert joins == []


def test_persist_join_detection_plan_returns_actual_insert_count(
    client: TestClient,
) -> None:
    from backend.metadata.join_detection_jobs.reconcile import (
        JoinDetectionPlan,
        JoinDetectionUpsert,
    )

    source = _source()
    _seed_join_catalog(source)
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    assert run_join_detection_job(job.id)["status"] == "succeeded"

    store = get_catalog_store()
    joins, total = store.list_joins_for_object("obj_orders")
    assert total == 1
    existing = joins[0]
    changes_before = store.list_join_changes(
        from_column_id=existing.from_column_id,
        to_column_id=existing.to_column_id,
    )
    assert len(changes_before) == 1

    stale_plan = JoinDetectionPlan(
        upsert_joins=(
            JoinDetectionUpsert(
                from_column_id=existing.from_column_id,
                to_column_id=existing.to_column_id,
                evidence="SQL join in stale: customer_id = id",
                join_expression="customer_id = id",
                join_kind="INNER",
            ),
        ),
        skipped_protected=0,
        skipped_rejected=0,
    )
    with store.catalog_write(source.id) as write:
        inserted = write.persist_join_detection_plan(stale_plan)
    assert inserted == 0
    joins_after, total_after = store.list_joins_for_object("obj_orders")
    assert total_after == 1
    assert joins_after[0].id == existing.id
    assert joins_after[0].evidence == existing.evidence
    changes_after = store.list_join_changes(
        from_column_id=existing.from_column_id,
        to_column_id=existing.to_column_id,
    )
    assert len(changes_after) == 1
    assert changes_after[0].id == changes_before[0].id


def test_parser_resolves_derived_table_and_cte_aliases() -> None:
    subq = parse_definition_joins(
        "SELECT * FROM (SELECT customer_id FROM orders) b "
        "JOIN customers c ON b.customer_id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert subq.fragment_errors == 0
    assert subq.alias_unresolved == 0
    assert _pairs(subq.leaves) == {("orders", "customer_id", "customers", "id")}

    cte = parse_definition_joins(
        "WITH b AS (SELECT customer_id FROM orders) "
        "SELECT * FROM b JOIN customers c ON b.customer_id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert cte.fragment_errors == 0
    assert cte.alias_unresolved == 0
    assert _pairs(cte.leaves) == {("orders", "customer_id", "customers", "id")}

    star = parse_definition_joins(
        "SELECT * FROM orders o JOIN (SELECT * FROM customers) c "
        "ON o.customer_id = c.id",
        engine="postgresql",
        default_schema="public",
    )
    assert star.alias_unresolved == 0
    assert _pairs(star.leaves) == {("orders", "customer_id", "customers", "id")}


def test_parser_does_not_treat_unknown_alias_as_table() -> None:
    parsed = parse_definition_joins(
        "SELECT * FROM orders o JOIN customers c ON o.customer_id = x.id",
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.leaves == []
    assert parsed.alias_unresolved == 1

    # Even if a real table named x exists in catalog later, the leaf must not invent x.id.
    invented = parse_definition_joins(
        "SELECT * FROM orders o JOIN customers c ON o.customer_id = t.id",
        engine="postgresql",
        default_schema="public",
    )
    assert invented.leaves == []
    assert invented.alias_unresolved == 1


def test_parser_counts_unqualified_equi_join_as_alias_unresolved() -> None:
    parsed = parse_definition_joins(
        "SELECT * FROM orders JOIN customers ON customer_id = id",
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.leaves == []
    assert parsed.fragment_errors == 0
    assert parsed.alias_unresolved >= 1


def test_parser_drops_same_column_self_join() -> None:
    parsed = parse_definition_joins(
        "CREATE VIEW v AS SELECT * FROM emp a JOIN emp b ON a.id = b.id",
        engine="postgresql",
        default_schema="public",
    )
    assert parsed.fragment_errors == 0
    assert parsed.alias_unresolved == 0
    assert parsed.leaves == []


def test_parser_preserves_catalog_segment() -> None:
    cross = parse_definition_joins(
        "SELECT * FROM OtherDb.dbo.orders o JOIN dbo.customers c "
        "ON o.customer_id = c.id",
        engine="mssql",
        default_schema="dbo",
    )
    assert len(cross.leaves) == 1
    assert cross.leaves[0].left_catalog is not None
    assert cross.leaves[0].left_catalog.casefold() == "otherdb"
    assert cross.leaves[0].left_table == "orders"
    assert cross.leaves[0].right_catalog is None

    same = parse_definition_joins(
        "SELECT * FROM ecoa.dbo.orders o JOIN dbo.customers c "
        "ON o.customer_id = c.id",
        engine="mssql",
        default_schema="dbo",
    )
    assert len(same.leaves) == 1
    assert same.leaves[0].left_catalog.casefold() == "ecoa"


def test_resolver_rejects_external_catalog_keeps_same_database() -> None:
    from backend.metadata.join_detection_jobs.parser import JoinLeaf
    from backend.metadata.join_detection_jobs.resolver import UnresolvedReason

    now = utc_now()
    objects = [
        CatalogObjectRecord(
            id="obj_orders",
            source_id="src_1",
            locator_key="obj/mssql/s/dbo/table/orders",
            object_type="table",
            schema_name="dbo",
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
            last_structure_job_id=None,
            collected_at=now,
            created_at=now,
            updated_at=now,
            columns=[
                CatalogColumnRecord(
                    id="col_orders_cid",
                    object_id="obj_orders",
                    locator_key="col/orders/cid",
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
                )
            ],
        ),
        CatalogObjectRecord(
            id="obj_customers",
            source_id="src_1",
            locator_key="obj/mssql/s/dbo/table/customers",
            object_type="table",
            schema_name="dbo",
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
            last_structure_job_id=None,
            collected_at=now,
            created_at=now,
            updated_at=now,
            columns=[
                CatalogColumnRecord(
                    id="col_customers_id",
                    object_id="obj_customers",
                    locator_key="col/customers/id",
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
        ),
    ]
    resolver = CatalogJoinResolver(objects, source_database="ecoa")
    external = JoinLeaf(
        left_catalog="e9",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_catalog=None,
        right_schema="dbo",
        right_table="customers",
        right_column="id",
        join_kind="INNER",
        join_expression="orders.customer_id = customers.id",
    )
    out = resolver.resolve_leaf(external, host_locator_key="view/v")
    assert out.join is None
    assert out.reason == UnresolvedReason.EXTERNAL_CATALOG

    same = JoinLeaf(
        left_catalog="ecoa",
        left_schema="dbo",
        left_table="orders",
        left_column="customer_id",
        right_catalog=None,
        right_schema="dbo",
        right_table="customers",
        right_column="id",
        join_kind="INNER",
        join_expression="orders.customer_id = customers.id",
    )
    ok = resolver.resolve_leaf(same, host_locator_key="view/v")
    assert ok.join is not None
    assert ok.join.from_column_id == "col_orders_cid"
    assert ok.join.to_column_id == "col_customers_id"


def test_resolver_same_column_is_not_object_miss() -> None:
    from backend.metadata.join_detection_jobs.parser import JoinLeaf
    from backend.metadata.join_detection_jobs.resolver import UnresolvedReason

    now = utc_now()
    objects = [
        CatalogObjectRecord(
            id="obj_emp",
            source_id="src_1",
            locator_key="obj/postgresql/s/public/table/emp",
            object_type="table",
            schema_name="public",
            name="emp",
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
            last_structure_job_id=None,
            collected_at=now,
            created_at=now,
            updated_at=now,
            columns=[
                CatalogColumnRecord(
                    id="col_emp_id",
                    object_id="obj_emp",
                    locator_key="col/emp/id",
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
    ]
    resolver = CatalogJoinResolver(objects)
    leaf = JoinLeaf(
        left_catalog=None,
        left_schema="public",
        left_table="emp",
        left_column="id",
        right_catalog=None,
        right_schema="public",
        right_table="emp",
        right_column="id",
        join_kind="INNER",
        join_expression="emp.id = emp.id",
    )
    out = resolver.resolve_leaf(leaf, host_locator_key="view/v")
    assert out.join is None
    assert out.reason is None
    assert out.reason != UnresolvedReason.OBJECT_NOT_IN_CATALOG


def test_join_detection_result_attributes_unresolved(client: TestClient) -> None:
    source = create_source(
        key="join-mssql",
        name="Join MSSQL",
        kind="database",
        description=None,
        engine="mssql",
        access={
            "host": "127.0.0.1",
            "port": 1433,
            "username": "u",
            "password": "p",
            "ssl_mode": "disable",
            "database": "ecoa",
            "schema": "dbo",
            "extra": {},
        },
    )
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[
            _object(
                object_id="obj_orders",
                source_id=source.id,
                name="orders",
                object_type="table",
                ddl=None,
                columns=[_column("obj_orders", "customer_id", now=now)],
                now=now,
                schema_name="dbo",
            ),
            _object(
                object_id="obj_customers",
                source_id=source.id,
                name="customers",
                object_type="table",
                ddl=None,
                columns=[_column("obj_customers", "id", now=now)],
                now=now,
                schema_name="dbo",
            ),
            _object(
                object_id="obj_view",
                source_id=source.id,
                name="v_cross",
                object_type="view",
                ddl=(
                    "CREATE VIEW v_cross AS SELECT * FROM e9.dbo.orders o "
                    "JOIN dbo.customers c ON o.customer_id = c.id"
                ),
                columns=[],
                now=now,
                schema_name="dbo",
            ),
        ],
        schema_scope="dbo",
        fail_safe_threshold=1.0,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["joins_upserted"] == 0
    assert stored.result["joins_skipped_unresolved_external"] >= 1
    assert stored.result["joins_skipped_unresolved"] >= 1


def test_join_detection_same_column_self_join_is_not_unresolved(
    client: TestClient,
) -> None:
    source = _source()
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="job_seed",
        collected=[
            _object(
                object_id="obj_emp",
                source_id=source.id,
                name="emp",
                object_type="table",
                ddl=None,
                columns=[_column("obj_emp", "id", now=now)],
                now=now,
            ),
            _object(
                object_id="obj_view",
                source_id=source.id,
                name="v_self",
                object_type="view",
                ddl=(
                    "CREATE VIEW v_self AS SELECT * FROM emp a "
                    "JOIN emp b ON a.id = b.id"
                ),
                columns=[],
                now=now,
            ),
        ],
        schema_scope="public",
        fail_safe_threshold=1.0,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result["joins_upserted"] == 0
    assert stored.result["joins_skipped_unresolved_object"] == 0
    assert stored.result["joins_skipped_unresolved"] == 0


def test_join_detection_fails_when_access_cannot_decrypt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata.errors import SourceSecretRequired

    source = _source()
    _seed_join_catalog(source)

    def boom(_ciphertext: str):
        raise SourceSecretRequired("Access decrypt failed")

    monkeypatch.setattr(
        "backend.metadata.join_detection_jobs.service.decrypt_access_blob",
        boom,
    )
    job = create_queued_job(kind="join_detection", input={"source_id": source.id})
    out = run_join_detection_job(job.id)
    assert out == {"status": "failed", "error_code": "JOB_SECRET_MISSING"}
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "JOB_SECRET_MISSING"
    joins, total = get_catalog_store().list_joins_for_object("obj_orders")
    assert total == 0
    assert joins == []
