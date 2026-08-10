"""Source / Job facade API tests (encrypted access blob)."""

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
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402


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


def _access(
    host: str = "127.0.0.1",
    port: int = 5432,
    username: str = "u",
    password: str = "p",
    ssl_mode: str = "require",
    extra: dict | None = None,
) -> dict:
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "ssl_mode": ssl_mode,
        "extra": extra if extra is not None else {},
    }


def _make_source(
    client: TestClient,
    key: str = "mes-prod",
    database_name: str = "MES",
    *,
    password: str = "p",
) -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "database_name": database_name,
            "engine": "postgresql",
            "access": _access(password=password),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["source"]
    assert body["has_access"] is True
    assert "password" not in (body.get("access") or {})
    assert body["engine"] == "postgresql"
    assert body["access"]["host"] == "127.0.0.1"
    return body


def test_access_schema_endpoint(client: TestClient) -> None:
    resp = client.get("/sources/access-schema/postgresql")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["engine"] == "postgresql"
    assert body["schema"]["$id"] == "postgresql.access.v1"
    assert body["schema"]["properties"]["password"]["x-secret"] is True
    assert "require" in body["schema"]["properties"]["ssl_mode"]["enum"]
    assert "ssl_root_cert" in body["schema"]["properties"]

    mssql = client.get("/sources/access-schema/mssql")
    assert mssql.status_code == 200, mssql.text
    mssql_schema = mssql.json()["schema"]
    assert mssql_schema["properties"]["ssl_mode"]["enum"] == ["disable"]
    assert "ssl_root_cert" not in mssql_schema["properties"]


def test_mssql_rejects_tls_ssl_mode(client: TestClient) -> None:
    resp = client.post(
        "/sources",
        json={
            "key": "mssql-tls",
            "name": "MSSQL TLS",
            "kind": "database",
            "database_name": "app",
            "engine": "mssql",
            "access": {
                "host": "127.0.0.1",
                "port": 1433,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "extra": {},
            },
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SOURCE_ACCESS_INVALID"


def test_source_requires_access(client: TestClient) -> None:
    resp = client.post(
        "/sources",
        json={
            "key": "no-access",
            "name": "NoAccess",
            "kind": "database",
            "database_name": "MES",
            "engine": "postgresql",
        },
    )
    assert resp.status_code == 422


def test_source_rejects_unknown_access_keys(client: TestClient) -> None:
    resp = client.post(
        "/sources",
        json={
            "key": "bad-access",
            "name": "Bad",
            "kind": "database",
            "database_name": "MES",
            "engine": "postgresql",
            "access": {**_access(), "sslmode": "require"},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SOURCE_ACCESS_INVALID"


def test_source_create_update_access(client: TestClient) -> None:
    source = _make_source(client, key="top")
    listed = client.get("/sources")
    assert listed.status_code == 200
    assert any(s["id"] == source["id"] for s in listed.json()["items"])

    patched = client.patch(
        f"/sources/{source['id']}",
        json={"access": _access(host="10.0.0.1", port=6543, password="p2")},
    )
    assert patched.status_code == 200
    assert patched.json()["source"]["access"]["host"] == "10.0.0.1"
    assert patched.json()["source"]["access"]["port"] == 6543
    assert "password" not in patched.json()["source"]["access"]

    full = client.get(f"/sources/{source['id']}/access")
    assert full.status_code == 200
    assert full.json()["access"]["password"] == "p2"
    assert full.json()["access"]["ssl_mode"] == "require"


def test_delete_source_requires_disabled(client: TestClient) -> None:
    source = _make_source(client, key="del-active")
    resp = client.delete(f"/sources/{source['id']}")
    assert resp.status_code == 409
    assert resp.json()["code"] == "SOURCE_NOT_DISABLED"


def test_delete_disabled_source_and_catalog(client: TestClient) -> None:
    source = _make_source(client, key="del-ok")
    now = datetime.utcnow()
    get_catalog_store().replace_structure_snapshot(
        source_id=source["id"],
        job_id="job_del",
        objects=[
            CatalogObjectRecord(
                id="obj_del",
                source_id=source["id"],
                locator_key="obj/postgresql/del-ok/public/table/t1",
                object_type="table",
                schema_name="public",
                name="t1",
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
                last_structure_job_id="job_del",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=[
                    CatalogColumnRecord(
                        id="col_del",
                        object_id="obj_del",
                        locator_key="col/postgresql/del-ok/public/table/t1/column/id",
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
        ],
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="del-ok",
    )
    assert get_catalog_store().list_present_for_source(source["id"])

    disabled = client.patch(
        f"/sources/{source['id']}",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["source"]["status"] == "disabled"

    deleted = client.delete(f"/sources/{source['id']}")
    assert deleted.status_code == 204

    listed = client.get("/sources")
    assert listed.status_code == 200
    assert all(s["id"] != source["id"] for s in listed.json()["items"])

    missing = client.get(f"/sources/{source['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "SOURCE_NOT_FOUND"
    assert get_catalog_store().list_objects(source["id"])[0] == []


def test_structure_job_single_flight(client: TestClient) -> None:
    source = _make_source(client, key="s1", database_name="db")
    from backend.jobs.store import create_queued_job, mark_running

    job = create_queued_job(
        kind="structure",
        input={"source_id": source["id"]},
    )
    mark_running(job.id)

    resp = client.post(
        f"/sources/{source['id']}/jobs",
        json={"kind": "structure"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "JOB_ALREADY_ACTIVE"


def test_structure_job_input_only_source_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata import runner as runner_mod

    monkeypatch.setattr(
        runner_mod,
        "run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="s2", database_name="db")
    resp = client.post(
        f"/sources/{source['id']}/jobs",
        json={"kind": "structure"},
    )
    assert resp.status_code == 202, resp.text
    job = resp.json()["job"]
    assert job["input"] == {"source_id": source["id"]}
    assert "connection_id" not in job["input"]


def test_source_probe_draft_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()

    class OkConnector:
        engine = "postgresql"

        def test_connection(self, endpoint) -> None:  # noqa: ANN001
            assert endpoint.database_name == "postgres"
            assert endpoint.host == "127.0.0.1"
            assert endpoint.password == "p"
            assert endpoint.ssl_mode == "require"
            return None

        def collect_structure(self, endpoint):  # noqa: ANN001
            raise AssertionError("not used")

    monkeypatch.setattr(
        "backend.metadata.sources.probe.get_connector",
        lambda engine: OkConnector(),
    )

    resp = client.post(
        "/sources/test",
        json={
            "engine": "postgresql",
            "access": _access(),
            "database_name": "postgres",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body.get("code") is None

    events, _ = get_audit_store().list_events(action="source.test")
    assert len(events) == 1
    assert events[0].resource_id == "draft"
    assert events[0].result == "success"
    assert "password" not in str(events[0].detail)


def test_source_probe_draft_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.metadata.connectors.base import ConnectorError
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()

    class FailConnector:
        engine = "postgresql"

        def test_connection(self, endpoint) -> None:  # noqa: ANN001
            raise ConnectorError("JOB_ENDPOINT_FAILED", "refused")

        def collect_structure(self, endpoint):  # noqa: ANN001
            raise AssertionError("not used")

    monkeypatch.setattr(
        "backend.metadata.sources.probe.get_connector",
        lambda engine: FailConnector(),
    )

    resp = client.post(
        "/sources/test",
        json={
            "engine": "postgresql",
            "access": _access(),
            "database_name": "postgres",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "SOURCE_TEST_FAILED"
    assert "refused" in body["message"]

    events, _ = get_audit_store().list_events(action="source.test")
    assert len(events) == 1
    assert events[0].result == "failure"


def test_source_probe_stored_uses_access(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()
    source = _make_source(client, key="probe-stored")

    seen: dict[str, str] = {}

    class OkConnector:
        engine = "postgresql"

        def test_connection(self, endpoint) -> None:  # noqa: ANN001
            seen["username"] = endpoint.username
            seen["password"] = endpoint.password
            seen["database_name"] = endpoint.database_name
            return None

        def collect_structure(self, endpoint):  # noqa: ANN001
            raise AssertionError("not used")

    monkeypatch.setattr(
        "backend.metadata.sources.probe.get_connector",
        lambda engine: OkConnector(),
    )

    resp = client.post(
        f"/sources/{source['id']}/test",
        json={"database_name": "MES"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert seen["username"] == "u"
    assert seen["password"] == "p"
    assert seen["database_name"] == "MES"

    events, _ = get_audit_store().list_events(action="source.test")
    assert any(e.resource_id == source["id"] and e.result == "success" for e in events)


def test_source_probe_timeout_returns_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from backend.metadata.sources import probe as probe_mod

    monkeypatch.setattr(probe_mod, "PROBE_TIMEOUT_SECONDS", 0.2)

    class HangConnector:
        engine = "postgresql"

        def test_connection(self, endpoint) -> None:  # noqa: ANN001
            time.sleep(30)

        def collect_structure(self, endpoint):  # noqa: ANN001
            raise AssertionError("not used")

    monkeypatch.setattr(probe_mod, "get_connector", lambda engine: HangConnector())

    started = time.monotonic()
    result = probe_mod.run_source_probe(
        engine="postgresql",
        access=_access(),
        database_name="db",
    )
    elapsed = time.monotonic() - started

    assert result.ok is False
    assert result.code == "SOURCE_TEST_TIMEOUT"
    assert elapsed < 2.0


def test_source_probe_requires_database_name(client: TestClient) -> None:
    resp = client.post(
        "/sources/test",
        json={
            "engine": "postgresql",
            "access": _access(),
        },
    )
    assert resp.status_code == 422


def test_source_probe_forbidden_without_write(client: TestClient) -> None:
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="ops",
        display_name="Ops",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    login = client.post("/auth/login", json={"account": "ops", "password": "secret"})
    assert login.status_code == 200

    resp = client.post(
        "/sources/test",
        json={
            "engine": "postgresql",
            "access": _access(),
            "database_name": "postgres",
        },
    )
    assert resp.status_code == 403


def test_fail_safe_aborts_without_absent() -> None:
    reset_catalog_store()
    now = datetime.utcnow()
    store = get_catalog_store()
    seeded = []
    for i in range(4):
        oid = f"obj_{i}"
        seeded.append(
            CatalogObjectRecord(
                id=oid,
                source_id="src_1",
                locator_key=f"obj/postgresql/orphan/public/table/t{i}",
                object_type="table",
                schema_name="public",
                name=f"t{i}",
                ddl=None,
                comment=None,
                primary_key=None,
                is_present=True,
                business_name="keep",
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
                        id=f"col_{i}",
                        object_id=oid,
                        locator_key=f"col/postgresql/orphan/public/table/t{i}/column/id",
                        name="id",
                        ordinal=1,
                        data_type="int",
                        nullable=False,
                        is_present=True,
                        default_value=None,
                        comment=None,
                        business_name="Id",
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
    store.replace_structure_snapshot(
        source_id="src_1",
        job_id="job_old",
        objects=seeded,
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="orphan",
    )
    with pytest.raises(CatalogWriteAborted) as exc:
        apply_structure_snapshot(
            source_id="src_1",
            job_id="job_new",
            collected=[seeded[0]],
            schema_scope=None,
            fail_safe_threshold=0.5,
            engine="postgresql",
            kind="database",
            source_key="orphan",
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

    from backend.jobs.store import create_queued_job
    from backend.metadata.catalog.store import CatalogObjectRecord, get_catalog_store
    from backend.metadata.connectors.base import ConnectorError
    from backend.metadata.runner import run_structure_job
    from backend.metadata.sources.service import create_source

    source = create_source(
        key="fail-src",
        name="F",
        kind="database",
        description=None,
        database_name="db",
        schema_filter=None,
        engine="postgresql",
        access=_access(),
    )
    now = datetime.utcnow()
    get_catalog_store().replace_structure_snapshot(
        source_id=source.id,
        job_id="old",
        objects=[
            CatalogObjectRecord(
                id="obj_keep",
                source_id=source.id,
                locator_key="obj/postgresql/fail-src/public/table/kept",
                object_type="table",
                schema_name="public",
                name="kept",
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
        schema_scope=None,
        engine="postgresql",
        kind="database",
        source_key="fail-src",
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
        input={"source_id": source.id},
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


def test_public_view_strips_secrets_and_includes_access_updated_at(
    client: TestClient,
) -> None:
    from backend.metadata.sources import service as source_service

    body = _make_source(client, key="pub-view")
    record = source_service.require_source(body["id"])
    view = source_service.public_view(record)
    assert view["access_updated_at"] is not None
    assert view["has_access"] is True
    assert view["access"] is not None
    assert "password" not in view["access"]
    assert view["access"]["host"] == "127.0.0.1"
    assert view["id"] == body["id"]


def test_enqueue_structure_job_audits_and_rejects_non_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from backend.admin.deps import resolve_pat_bearer
    from backend.metadata.errors import JobInputInvalid, JobSourceDisabled
    from backend.metadata.sources.store import SourceRecord, get_source_store
    from backend.metadata.source_jobs import enqueue_structure_job
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()
    monkeypatch.setattr(
        "backend.metadata.runner.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )

    source = _make_source(client, key="enq-ok")
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    tok = client.post("/tokens", json={"name": "enq-pat", "expires_at": expires})
    assert tok.status_code == 201, tok.text
    token_id = tok.json()["token"]["id"]
    secret = tok.json()["secret"]
    user, resolved_token_id = resolve_pat_bearer(secret)
    assert resolved_token_id == token_id

    job = enqueue_structure_job(
        source_id=source["id"],
        actor_user_id=user.id,
        actor_token_id=resolved_token_id,
    )
    assert job.kind == "structure"
    assert job.input == {"source_id": source["id"]}
    events, _ = get_audit_store().list_events(action="job.enqueue")
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert events[0].actor_token_id == token_id
    assert events[0].detail["source_id"] == source["id"]

    disabled = client.patch(f"/sources/{source['id']}", json={"status": "disabled"})
    assert disabled.status_code == 200
    with pytest.raises(JobSourceDisabled):
        enqueue_structure_job(
            source_id=source["id"],
            actor_user_id=user.id,
            actor_token_id=token_id,
        )

    now = datetime.utcnow()
    get_source_store().create_source(
        SourceRecord(
            id="src_nondb",
            key="file-like",
            locator_key="src/file/file-like",
            name="File",
            kind="file",
            status="active",
            description=None,
            database_name=None,
            schema_filter=None,
            engine=None,
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(JobInputInvalid) as exc:
        enqueue_structure_job(
            source_id="src_nondb",
            actor_user_id=user.id,
            actor_token_id=token_id,
        )
    assert "database" in exc.value.message


def test_structure_job_http_enqueue_writes_audit(client: TestClient, monkeypatch) -> None:
    from backend.admin.audit_store import get_audit_store, reset_audit_store

    reset_audit_store()
    monkeypatch.setattr(
        "backend.metadata.runner.run_structure_job",
        lambda job_id: {"status": "succeeded"},
    )
    source = _make_source(client, key="http-enq")
    resp = client.post(
        f"/sources/{source['id']}/jobs",
        json={"kind": "structure"},
    )
    assert resp.status_code == 202, resp.text
    events, _ = get_audit_store().list_events(action="job.enqueue")
    assert len(events) == 1
    assert events[0].resource_id == resp.json()["job"]["id"]
    assert events[0].detail["source_id"] == source["id"]
    assert events[0].actor_token_id is None
