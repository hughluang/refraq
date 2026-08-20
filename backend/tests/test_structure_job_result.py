"""Structure Job result and Structure Diff HTTP."""

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

from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import get_settings, reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    ERROR_RUNNING_TIMEOUT,
    create_queued_job,
    get_job_store,
    mark_cancelled,
    mark_failed,
)
from backend.main import app  # noqa: E402
from backend.metadata.catalog.records import CatalogColumnRecord, CatalogObjectRecord  # noqa: E402
from backend.metadata.catalog.store import get_catalog_store  # noqa: E402
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.connectors.base import (  # noqa: E402
    CollectedColumn,
    CollectedObject,
    CollectedStructure,
)
from backend.metadata.structure_jobs.service import run_structure_job  # noqa: E402
from backend.metadata.sources.service import create_source  # noqa: E402
from backend.metadata.sources.store import SourceRecord  # noqa: E402
from backend.metadata.structure_diffs.store import get_structure_diff_store  # noqa: E402


def _access() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "u",
        "password": "p",
        "ssl_mode": "require",
        "database": "MES",
        "schema": "public",
        "extra": {},
    }


def _seed_tables(source: SourceRecord, names: list[str]) -> None:
    now = utc_now()
    collected = []
    for name in names:
        collected.append(
            CatalogObjectRecord(
                id=f"obj_{name}",
                source_id=source.id,
                locator_key=f"obj/postgresql/diff-src/public/table/{name}",
                object_type="table",
                schema_name="public",
                name=name,
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
                last_structure_job_id="job_old",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[
                    CatalogColumnRecord(
                        id=f"col_{name}_id",
                        object_id=f"obj_{name}",
                        locator_key=(
                            f"col/postgresql/diff-src/public/table/{name}/column/id"
                        ),
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
        )
    apply_structure_snapshot(
        source=source,
        job_id="job_old",
        collected=collected,
        schema_scope="public",
        fail_safe_threshold=1.0,
    )


class _FakeConnector:
    engine = "postgresql"

    def __init__(self, names: list[str]) -> None:
        self._names = names

    def test_connection(self, endpoint) -> None:  # noqa: ANN001
        return None

    def collect_structure(self, endpoint, progress=None) -> CollectedStructure:  # noqa: ANN001
        objects = [
            CollectedObject(
                schema_name="public",
                name=name,
                object_type="table",
                columns=[
                    CollectedColumn(
                        name="id",
                        ordinal=1,
                        data_type="integer",
                        nullable=False,
                    )
                ],
                primary_key=["id"],
            )
            for name in self._names
        ]
        return CollectedStructure(objects=objects)


class _FakeConnectorWithNullDdlRoutine:
    engine = "postgresql"

    def test_connection(self, endpoint) -> None:  # noqa: ANN001
        return None

    def collect_structure(self, endpoint, progress=None) -> CollectedStructure:  # noqa: ANN001
        return CollectedStructure(
            objects=[
                CollectedObject(
                    schema_name="public",
                    name="orders",
                    object_type="table",
                    columns=[
                        CollectedColumn(
                            name="id",
                            ordinal=1,
                            data_type="integer",
                            nullable=False,
                        )
                    ],
                    primary_key=["id"],
                ),
                CollectedObject(
                    schema_name="public",
                    name="fn_encrypted",
                    object_type="function",
                    ddl=None,
                ),
            ]
        )


def _source() -> object:
    return create_source(
        key="diff-src",
        name="Diff",
        kind="database",
        description=None,
        engine="postgresql",
        access=_access(),
    )


@pytest.fixture()
def client() -> TestClient:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
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


def test_successful_structure_job_writes_result_and_diff(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    source = _source()
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _FakeConnector(["orders"]),
    )
    job = create_queued_job(
        kind="structure",
        input={"source_id": source.id},
        summary="structure · diff-src",
    )
    out = run_structure_job(job.id)
    assert out["status"] == "succeeded"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.result is not None
    assert stored.result["schema"] == "structure.diff.v1"
    assert stored.result["class"] == "non_breaking"
    assert stored.result["counts"]["objects_added"] == 1
    diff_id = stored.result["structure_diff_id"]

    listed = client.get(f"/sources/{source.id}/structure-diffs")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["class"] == "non_breaking"
    assert items[0]["job_id"] == job.id

    detail = client.get(f"/structure-diffs/{diff_id}")
    assert detail.status_code == 200, detail.text
    changes = detail.json()["structure_diff"]["changes"]
    assert any(c["change"] == "object_added" for c in changes)

    job_get = client.get(f"/jobs/{job.id}")
    assert job_get.status_code == 200
    assert job_get.json()["job"]["result"]["class"] == "non_breaking"
    assert job_get.json()["job"]["summary"] == "structure · diff-src"


def test_structure_job_succeeds_when_routine_ddl_is_none(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    source = _source()
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _FakeConnectorWithNullDdlRoutine(),
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    out = run_structure_job(job.id)
    assert out["status"] == "succeeded"
    objects, _ = get_catalog_store().list_objects(source.id)
    by_name = {obj.name: obj for obj in objects}
    assert by_name["fn_encrypted"].ddl is None
    assert by_name["fn_encrypted"].object_type == "function"


def test_unexpected_snapshot_error_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _FakeConnector(["orders"]),
    )
    monkeypatch.setattr(
        "backend.metadata.structure_jobs.service.apply_structure_snapshot",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "sending query and params failed: number of parameters "
                "must be between 0 and 65535"
            )
        ),
    )
    job = create_queued_job(kind="structure", input={"source_id": source.id})
    out = run_structure_job(job.id)
    assert out["status"] == "failed"
    assert out["error_code"] == "JOB_EXECUTION_FAILED"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "JOB_EXECUTION_FAILED"
    assert stored.result is None
    diffs, total = get_structure_diff_store().list_for_source(source.id)
    assert total == 0
    assert diffs == []


def test_fail_safe_runner_writes_no_result_or_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    _seed_tables(source, ["t0", "t1", "t2", "t3"])
    monkeypatch.setattr(get_settings(), "refraq_catalog_fail_safe_threshold", 0.5)
    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: _FakeConnector(["t0"]),
    )
    job = create_queued_job(
        kind="structure",
        input={"source_id": source.id},
    )
    out = run_structure_job(job.id)
    assert out["status"] == "failed"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.error_code == "JOB_FAIL_SAFE"
    assert stored.result is None
    diffs, _total = get_structure_diff_store().list_for_source(source.id)
    assert all(d.job_id != job.id for d in diffs)
    assert any(d.job_id == "job_old" for d in diffs)
    present = get_catalog_store().list_present_for_source(source.id)
    assert len(present) == 4


def test_running_timeout_during_collect_does_not_write_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    _seed_tables(source, ["orders"])
    job = create_queued_job(kind="structure", input={"source_id": source.id})

    class TimeoutDuringCollect(_FakeConnector):
        def collect_structure(self, endpoint, progress=None) -> CollectedStructure:
            collected = super().collect_structure(endpoint, progress)
            marked = mark_failed(
                job.id,
                error_code=ERROR_RUNNING_TIMEOUT,
                error_summary="Job exceeded running time limit",
                from_statuses=("running",),
            )
            assert marked is not None
            assert marked.status == "failed"
            return collected

    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: TimeoutDuringCollect(["orders", "lines"]),
    )
    out = run_structure_job(job.id)
    assert out["status"] == "failed"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == ERROR_RUNNING_TIMEOUT
    assert stored.result is None
    diffs, _total = get_structure_diff_store().list_for_source(source.id)
    assert all(d.job_id != job.id for d in diffs)
    present = get_catalog_store().list_present_for_source(source.id)
    assert [obj.name for obj in present] == ["orders"]


def test_cancel_during_collect_does_not_write_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    _seed_tables(source, ["orders"])
    job = create_queued_job(kind="structure", input={"source_id": source.id})

    class CancelDuringCollect(_FakeConnector):
        def collect_structure(self, endpoint, progress=None) -> CollectedStructure:
            collected = super().collect_structure(endpoint, progress)
            marked = mark_cancelled(job.id)
            assert marked is not None
            assert marked.status == "cancelled"
            return collected

    monkeypatch.setattr(
        "backend.metadata.connectors.runtime.get_connector",
        lambda engine: CancelDuringCollect(["orders", "lines"]),
    )
    out = run_structure_job(job.id)
    assert out["status"] == "cancelled"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.status == "cancelled"
    assert stored.result is None
    diffs, _total = get_structure_diff_store().list_for_source(source.id)
    assert all(d.job_id != job.id for d in diffs)
    present = get_catalog_store().list_present_for_source(source.id)
    assert [obj.name for obj in present] == ["orders"]


def test_source_join_select_uses_subquery_not_expanded_ids() -> None:
    from backend.metadata.catalog.store.sql import _select_joins_for_source

    compiled = _select_joins_for_source("src_big").compile()
    sql = str(compiled).lower()
    assert "catalog_columns" in sql
    assert len(compiled.params) <= 2
