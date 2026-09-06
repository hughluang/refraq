"""Declared catalog scope must exist before object listing."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")

from backend.core.time import utc_now
from backend.jobs.store import create_queued_job, get_job_store
from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
from backend.metadata.connectors.base import ConnectorError, SourceEndpoint
from backend.metadata.connectors.mssql import MssqlConnector
from backend.metadata.connectors.mssql import _OBJECT_SQL as MSSQL_OBJECT_SQL
from backend.metadata.connectors.mssql import _SCOPE_SQL as MSSQL_SCOPE_SQL
from backend.metadata.connectors.oracle import OracleConnector
from backend.metadata.connectors.oracle import _OBJECT_SQL as ORACLE_OBJECT_SQL
from backend.metadata.connectors.oracle import _SCOPE_SQL as ORACLE_SCOPE_SQL
from backend.metadata.connectors.postgresql import PostgresqlConnector
from backend.metadata.connectors.postgresql import _OBJECT_SQL as PG_OBJECT_SQL
from backend.metadata.connectors.postgresql import _SCOPE_SQL as PG_SCOPE_SQL
from backend.metadata.sources.probe import run_source_probe
from backend.metadata.sources.service import create_source
from backend.metadata.structure_diffs.store import get_structure_diff_store
from backend.metadata.structure_jobs.service import run_structure_job


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _FakeEngine:
    def __init__(
        self,
        *,
        scope_sql: object,
        object_sql: object,
        scope_present: bool,
    ) -> None:
        self.scope_sql = scope_sql
        self.object_sql = object_sql
        self.scope_present = scope_present
        self.seen: list[object] = []

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def dispose(self) -> None:
        return None

    def execution_options(self, **_kwargs: object):
        return self

    def execute(self, sql: object, params: dict[str, object] | None = None):
        self.seen.append(sql)
        if sql is self.scope_sql:
            if self.scope_present:
                return _FakeResult([{"present": 1}])
            return _FakeResult([])
        if sql is self.object_sql and not self.scope_present:
            raise AssertionError("object listing ran before catalog scope was proven")
        return _FakeResult([])


class _Progress:
    def __init__(self) -> None:
        self.listed: list[str] = []

    def listing_objects(self, schema: str) -> None:
        self.listed.append(schema)

    def listed_objects(self, total: int) -> None:
        return None

    def fetched(self, part: str, rows: int) -> None:
        return None

    def assembled(self, total: int) -> None:
        return None


def _pg_endpoint(schema: str = "public") -> SourceEndpoint:
    return SourceEndpoint(
        engine="postgresql",
        host="127.0.0.1",
        port=5432,
        username="u",
        password="p",
        database_name="MES",
        schema_filter=schema,
    )


def _mssql_endpoint(schema: str = "dbo") -> SourceEndpoint:
    return SourceEndpoint(
        engine="mssql",
        host="127.0.0.1",
        port=1433,
        username="u",
        password="p",
        database_name="MES",
        schema_filter=schema,
        ssl_mode="disable",
    )


def _oracle_endpoint(owner: str = "MES") -> SourceEndpoint:
    return SourceEndpoint(
        engine="oracle",
        host="127.0.0.1",
        port=1521,
        username="u",
        password="p",
        database_name="MES",
        schema_filter=owner,
        ssl_mode="disable",
    )


def _access(schema: str = "public") -> dict[str, object]:
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "u",
        "password": "p",
        "ssl_mode": "require",
        "database": "MES",
        "schema": schema,
        "extra": {},
    }


def _seed_table(source, *, name: str = "kept") -> None:
    now = utc_now()
    apply_structure_snapshot(
        source=source,
        job_id="old",
        collected=[
            CatalogObjectRecord(
                id="obj_keep",
                source_id=source.id,
                locator_key=f"obj/postgresql/{source.key}/public/table/{name}",
                object_type="table",
                schema_name="public",
                name=name,
                ddl=None,
                comment=None,
                primary_key=None,
                is_present=True,
                business_name="Kept",
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
                last_structure_job_id="old",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[],
            )
        ],
        schema_scope="public",
    )


def test_scope_sql_is_not_object_listing() -> None:
    assert "pg_namespace" in str(PG_SCOPE_SQL)
    assert "pg_class" not in str(PG_SCOPE_SQL)
    assert "sys.schemas" in str(MSSQL_SCOPE_SQL)
    assert "sys.objects" not in str(MSSQL_SCOPE_SQL)
    assert "all_users" in str(ORACLE_SCOPE_SQL)
    assert "all_tables" not in str(ORACLE_SCOPE_SQL)


@pytest.mark.parametrize(
    ("connector_cls", "endpoint", "scope_sql", "object_sql"),
    [
        (PostgresqlConnector, _pg_endpoint(), PG_SCOPE_SQL, PG_OBJECT_SQL),
        (MssqlConnector, _mssql_endpoint(), MSSQL_SCOPE_SQL, MSSQL_OBJECT_SQL),
        (OracleConnector, _oracle_endpoint(), ORACLE_SCOPE_SQL, ORACLE_OBJECT_SQL),
    ],
)
def test_missing_scope_fails_before_listing(
    connector_cls: type,
    endpoint: SourceEndpoint,
    scope_sql: object,
    object_sql: object,
) -> None:
    engine = _FakeEngine(
        scope_sql=scope_sql, object_sql=object_sql, scope_present=False
    )
    progress = _Progress()
    connector = connector_cls()
    with patch.object(connector_cls, "_engine", return_value=engine):
        with pytest.raises(ConnectorError) as exc_info:
            connector.collect_structure(endpoint, progress=progress)
        with pytest.raises(ConnectorError) as probe_exc:
            connector.test_connection(endpoint)
    assert exc_info.value.code == "JOB_ENDPOINT_FAILED"
    assert "does not exist" in exc_info.value.message
    assert probe_exc.value.code == "JOB_ENDPOINT_FAILED"
    assert progress.listed == []
    assert scope_sql in engine.seen
    assert object_sql not in engine.seen


@pytest.mark.parametrize(
    ("connector_cls", "endpoint", "scope_sql", "object_sql", "scope"),
    [
        (PostgresqlConnector, _pg_endpoint(), PG_SCOPE_SQL, PG_OBJECT_SQL, "public"),
        (MssqlConnector, _mssql_endpoint(), MSSQL_SCOPE_SQL, MSSQL_OBJECT_SQL, "dbo"),
        (OracleConnector, _oracle_endpoint(), ORACLE_SCOPE_SQL, ORACLE_OBJECT_SQL, "MES"),
    ],
)
def test_proven_empty_scope_is_complete_collect(
    connector_cls: type,
    endpoint: SourceEndpoint,
    scope_sql: object,
    object_sql: object,
    scope: str,
) -> None:
    engine = _FakeEngine(
        scope_sql=scope_sql, object_sql=object_sql, scope_present=True
    )
    progress = _Progress()
    connector = connector_cls()
    with patch.object(connector_cls, "_engine", return_value=engine):
        collected = connector.collect_structure(endpoint, progress=progress)
        connector.test_connection(endpoint)
    assert collected.objects == []
    assert progress.listed == [scope]
    assert engine.seen[0] is scope_sql
    assert object_sql in engine.seen


def test_probe_missing_scope_is_source_test_failed() -> None:
    engine = _FakeEngine(
        scope_sql=PG_SCOPE_SQL, object_sql=PG_OBJECT_SQL, scope_present=False
    )
    with patch.object(PostgresqlConnector, "_engine", return_value=engine):
        result = run_source_probe(engine="postgresql", access=_access(schema="nope"))
    assert result.ok is False
    assert result.code == "SOURCE_TEST_FAILED"
    assert result.message is not None
    assert "does not exist" in result.message


def test_probe_proven_empty_scope_succeeds() -> None:
    engine = _FakeEngine(
        scope_sql=PG_SCOPE_SQL, object_sql=PG_OBJECT_SQL, scope_present=True
    )
    with patch.object(PostgresqlConnector, "_engine", return_value=engine):
        result = run_source_probe(engine="postgresql", access=_access())
    assert result.ok is True
    assert result.code is None


def _pg_source():
    return create_source(
        key="scope-src",
        name="Scope",
        kind="database",
        description=None,
        engine="postgresql",
        access=_access(),
    )


def test_missing_scope_job_does_not_apply() -> None:
    source = _pg_source()
    _seed_table(source)
    engine = _FakeEngine(
        scope_sql=PG_SCOPE_SQL, object_sql=PG_OBJECT_SQL, scope_present=False
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    with patch.object(PostgresqlConnector, "_engine", return_value=engine):
        out = run_structure_job(job.id)
    assert out["status"] == "failed"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.error_code == "JOB_ENDPOINT_FAILED"
    present = get_catalog_store().list_present_for_source(source.id)
    assert [o.name for o in present] == ["kept"]
    diffs, _ = get_structure_diff_store().list_for_source(source.id)
    assert all(item.job_id != job.id for item in diffs)
    assert PG_OBJECT_SQL not in engine.seen
    assert "listing objects" not in stored.log_body


def test_proven_empty_scope_job_commits_absent() -> None:
    source = _pg_source()
    _seed_table(source)
    engine = _FakeEngine(
        scope_sql=PG_SCOPE_SQL, object_sql=PG_OBJECT_SQL, scope_present=True
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    with patch.object(PostgresqlConnector, "_engine", return_value=engine):
        out = run_structure_job(job.id)
    assert out["status"] == "succeeded"
    present = get_catalog_store().list_present_for_source(source.id)
    assert present == []
    objects, _ = get_catalog_store().list_objects(source.id)
    assert [o.name for o in objects if not o.is_present] == ["kept"]
    diffs, _ = get_structure_diff_store().list_for_source(source.id)
    assert any(item.job_id == job.id for item in diffs)
    assert engine.seen[0] is PG_SCOPE_SQL
    assert PG_OBJECT_SQL in engine.seen
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert "listing objects in public…" in stored.log_body
    assert "listed 0 objects" in stored.log_body
