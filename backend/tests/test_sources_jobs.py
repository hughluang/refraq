"""Source / Connection / Job facade API tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.jobs.store import get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    apply_structure_snapshot,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.repositories.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.repositories.user_store import get_user_store, reset_user_store  # noqa: E402
from datetime import datetime  # noqa: E402


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
    from backend.worker.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    with TestClient(app) as test_client:
        login = test_client.post(
            "/auth/login",
            json={"account": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        yield test_client


def test_source_connection_one_to_one(client: TestClient) -> None:
    created = client.post(
        "/sources",
        json={
            "key": "mes-prod",
            "name": "MES",
            "kind": "database",
            "database_name": "MES",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["source"]["id"]

    conn = client.post(
        f"/sources/{source_id}/connections",
        json={
            "name": "primary",
            "engine": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "secret": {"username": "u", "password": "p"},
        },
    )
    assert conn.status_code == 201
    assert conn.json()["connection"]["has_secret"] is True
    assert "secret" not in conn.json()["connection"]
    assert "password" not in str(conn.json())

    second = client.post(
        f"/sources/{source_id}/connections",
        json={
            "name": "standby",
            "engine": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "secret": {"username": "u", "password": "p"},
        },
    )
    assert second.status_code == 409
    assert second.json()["code"] == "SOURCE_CONNECTION_EXISTS"


def test_structure_job_single_flight(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.metadata import runner as runner_mod

    def _slow_fail(job_id: str) -> dict[str, str]:
        from backend.jobs.store import mark_running

        mark_running(job_id, celery_task_id=job_id)
        # Leave running without finishing so second enqueue conflicts.
        return {"status": "running"}

    monkeypatch.setattr(runner_mod, "run_structure_job", _slow_fail)

    source = client.post(
        "/sources",
        json={
            "key": "s1",
            "name": "S1",
            "kind": "database",
            "database_name": "db",
        },
    ).json()["source"]
    client.post(
        f"/sources/{source['id']}/connections",
        json={
            "name": "c",
            "engine": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "secret": {"username": "u", "password": "p"},
        },
    )
    # Bypass celery: create queued then mark running via store for single-flight
    from backend.jobs.store import create_queued_job, mark_running

    job = create_queued_job(
        kind="structure",
        input={"source_id": source["id"], "connection_id": "x"},
    )
    mark_running(job.id)

    resp = client.post(
        f"/sources/{source['id']}/jobs",
        json={"kind": "structure"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "JOB_ALREADY_ACTIVE"


def test_job_connection_id_mismatch(client: TestClient) -> None:
    source = client.post(
        "/sources",
        json={
            "key": "s2",
            "name": "S2",
            "kind": "database",
            "database_name": "db",
        },
    ).json()["source"]
    conn = client.post(
        f"/sources/{source['id']}/connections",
        json={
            "name": "c",
            "engine": "postgresql",
            "host": "127.0.0.1",
            "port": 5432,
            "secret": {"username": "u", "password": "p"},
        },
    ).json()["connection"]

    resp = client.post(
        f"/sources/{source['id']}/jobs",
        json={"kind": "structure", "connection_id": "conn_other"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "JOB_CONNECTION_MISMATCH"
    assert conn["id"]


def test_fail_safe_aborts_without_absent() -> None:
    reset_catalog_store()
    now = datetime.utcnow()
    store = get_catalog_store()
    # Seed present objects
    seeded = []
    for i in range(4):
        oid = f"obj_{i}"
        seeded.append(
            CatalogObjectRecord(
                id=oid,
                source_id="src_1",
                collected_from_connection_id="conn_1",
                object_type="table",
                schema_name="public",
                name=f"t{i}",
                ddl=None,
                is_present=True,
                business_name="keep",
                business_description=None,
                last_structure_job_id="job_old",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[
                    CatalogColumnRecord(
                        id=f"col_{i}",
                        object_id=oid,
                        name="id",
                        ordinal=1,
                        data_type="int",
                        nullable=False,
                        is_present=True,
                        business_name="Id",
                        business_description=None,
                        created_at=now,
                        updated_at=now,
                    )
                ],
            )
        )
    store.replace_structure_snapshot(
        source_id="src_1",
        connection_id="conn_1",
        job_id="job_old",
        objects=seeded,
        schema_scope=None,
    )
    # Collect returns only 1 of 4 -> 75% absent == threshold boundary with >
    # threshold 0.75 means ratio > 0.75 aborts; 3/4 = 0.75 should NOT abort
    # Use threshold 0.5 so 0.75 aborts
    with pytest.raises(CatalogWriteAborted) as exc:
        apply_structure_snapshot(
            source_id="src_1",
            connection_id="conn_1",
            job_id="job_new",
            collected=[seeded[0]],
            schema_scope=None,
            fail_safe_threshold=0.5,
        )
    assert exc.value.code == "JOB_FAIL_SAFE"
    present = store.list_present_for_source("src_1")
    assert len(present) == 4
    assert all(o.business_name == "keep" for o in present)


def test_collect_failure_does_not_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_settings_cache()
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"

    from backend.metadata.connectors.base import ConnectorError
    from backend.metadata.sources.store import create_connection, create_source
    from backend.metadata.runner import run_structure_job
    from backend.jobs.store import create_queued_job
    from backend.metadata.catalog.store import (
        CatalogObjectRecord,
        get_catalog_store,
    )

    source = create_source(
        key="fail-src",
        name="F",
        kind="database",
        description=None,
        database_name="db",
        schema_filter=None,
    )
    conn = create_connection(
        source_id=source.id,
        name="c",
        engine="postgresql",
        host="127.0.0.1",
        port=5432,
        secret={"username": "u", "password": "p"},
    )
    now = datetime.utcnow()
    get_catalog_store().replace_structure_snapshot(
        source_id=source.id,
        connection_id=conn.id,
        job_id="old",
        objects=[
            CatalogObjectRecord(
                id="obj_keep",
                source_id=source.id,
                collected_from_connection_id=conn.id,
                object_type="table",
                schema_name="public",
                name="kept",
                ddl=None,
                is_present=True,
                business_name="Kept",
                business_description=None,
                last_structure_job_id="old",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[],
            )
        ],
        schema_scope=None,
    )

    class Boom:
        engine = "postgresql"

        def test_connection(self, endpoint):  # noqa: ANN001
            return None

        def collect_structure(self, endpoint):  # noqa: ANN001
            raise ConnectorError("JOB_COLLECT_FAILED", "boom")

    monkeypatch.setattr(
        "backend.metadata.runner.get_connector",
        lambda engine: Boom(),
    )
    job = create_queued_job(
        kind="structure",
        input={"source_id": source.id, "connection_id": conn.id},
    )
    result = run_structure_job(job.id)
    assert result["status"] == "failed"
    stored = get_job_store().get(job.id)
    assert stored is not None
    assert stored.error_code == "JOB_COLLECT_FAILED"
    present = get_catalog_store().list_present_for_source(source.id)
    assert len(present) == 1
    assert present[0].name == "kept"
    assert present[0].business_name == "Kept"
