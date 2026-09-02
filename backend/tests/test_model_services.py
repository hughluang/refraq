"""Model Service lifecycle, purpose switches, and Catalog Search hybrid gate."""

from __future__ import annotations

import logging
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.model_services import (  # noqa: E402
    bind_catalog_embed_jobs,
    get_embedding_runtime,
    mark_embedding_ready,
)
from backend.admin.model_services.ports import (  # noqa: E402
    CatalogEmbedJobsPort,
    catalog_embed_jobs,
)
from backend.admin.model_services.store import get_model_service_store  # noqa: E402
from backend.admin.permissions import ALL_PERMISSIONS  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.session_store import MemorySessionStore, get_session_store  # noqa: E402
from backend.admin.user_store import MemoryUserStore, get_user_store  # noqa: E402
from backend.jobs.store import get_job_store, reset_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.metadata.catalog.embedding import (  # noqa: E402
    embedding_configured,
    embedding_write_enabled,
    set_embed_fn_for_tests,
)
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.catalog_embed_jobs import CatalogEmbedJobs  # noqa: E402
from backend.metadata.sources.service import require_source  # noqa: E402
from backend.metadata.sources.store import (  # noqa: E402
    SourceRecord,
    get_source_store,
    reset_source_store,
)
from backend.tests.problem import assert_problem  # noqa: E402
from backend.worker.parameters import assemble_system_parameters  # noqa: E402


class RecordingJobs(CatalogEmbedJobsPort):
    def __init__(self) -> None:
        self.minted: list[dict[str, object]] = []
        self.cancels = 0
        self.clears = 0
        self._status: str | None = None

    def mint(
        self,
        *,
        service_id: str,
        display_name: str,
        generation: int,
        actor_user_id: str,
    ) -> str:
        self.minted.append(
            {
                "service_id": service_id,
                "display_name": display_name,
                "generation": generation,
                "actor_user_id": actor_user_id,
            }
        )
        self._status = "queued"
        return f"job_{len(self.minted)}"

    def cancel_active(self) -> None:
        self.cancels += 1
        if self._status in {"queued", "running"}:
            self._status = "cancelled"

    def clear_index(self) -> None:
        self.clears += 1

    def latest_status(self) -> str | None:
        return self._status


@pytest.fixture
def jobs() -> RecordingJobs:
    port = RecordingJobs()
    bind_catalog_embed_jobs(port)
    yield port
    bind_catalog_embed_jobs(CatalogEmbedJobs())


@pytest.fixture
def stores():
    roles = MemoryRoleStore()
    seed_roles(roles)
    users = MemoryUserStore()
    root_role = roles.get_by_key("super_admin")
    operator_role = roles.get_by_key("operator")
    assert root_role is not None and operator_role is not None
    users.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=root_role.id,
    )
    users.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator_role.id,
    )
    sessions = MemorySessionStore()
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_role_store] = lambda: roles
    app.dependency_overrides[get_session_store] = lambda: sessions
    yield {"roles": roles, "users": users}
    app.dependency_overrides.clear()


@pytest.fixture
def client(stores, jobs):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.admin.model_services.service.probe_embeddings",
        lambda **kwargs: (8, kwargs["model"]),
    )
    set_embed_fn_for_tests(None)
    yield
    set_embed_fn_for_tests(None)


def _login(client: TestClient, account: str = "root", password: str = "s3cret") -> None:
    response = client.post("/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200


def _create(client: TestClient, **overrides: object) -> dict:
    body = {
        "display_name": "Office TEI",
        "url": "http://embed.internal:8080/v1/embeddings",
        "model": "Qwen3-Embedding-8B",
        "api_key": "sk-test",
    }
    body.update(overrides)
    response = client.post("/model-services", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_unbound_catalog_embed_port_fails() -> None:
    bind_catalog_embed_jobs(None)
    try:
        with pytest.raises(RuntimeError, match="catalog embed jobs port is not bound"):
            catalog_embed_jobs()
    finally:
        bind_catalog_embed_jobs(CatalogEmbedJobs())


def test_operator_lacks_write(client: TestClient) -> None:
    _login(client, "op", "op-pass")
    denied = client.post(
        "/model-services",
        json={
            "display_name": "x",
            "url": "http://embed.example/v1/embeddings",
            "model": "m",
        },
    )
    assert denied.status_code == 403
    listed = client.get("/model-services")
    assert listed.status_code == 403


def test_existing_custom_roles_do_not_gain_write(client: TestClient, stores) -> None:
    _login(client)
    roles = stores["roles"]
    created = client.post(
        "/roles",
        json={"key": "reviewer", "name": "Reviewer", "permissions": ["console:access"]},
    )
    assert created.status_code == 201
    stored = roles.get_by_key("reviewer")
    assert stored is not None
    assert "model_services:write" not in stored.permissions
    assert "model_services:write" in ALL_PERMISSIONS


def test_create_list_spec_and_secret_write_only(client: TestClient) -> None:
    _login(client)
    spec = client.get("/model-services/spec")
    assert spec.status_code == 200
    assert spec.json()["purpose"] == "embedding"
    created = _create(client)
    assert created["has_secret"] is True
    assert created["in_use"] is False
    assert "api_key" not in created
    assert "secret" not in created
    listed = client.get("/model-services")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == created["id"]


def test_reject_v1_base_url(client: TestClient) -> None:
    _login(client)
    response = client.post(
        "/model-services",
        json={
            "display_name": "bad",
            "url": "http://embed.internal/v1",
            "model": "m",
        },
    )
    assert_problem(response, status=400, code="MODEL_SERVICE_INVALID_CONFIG")


def test_activate_mints_job_clears_ready_and_is_lexical(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    assert embedding_configured() is False
    activated = client.post(f"/model-services/{created['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["in_use"] is True
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["ready"] is False
    assert purpose.json()["index_status"] == "indexing"
    assert purpose.json()["generation"] == 1
    assert len(jobs.minted) == 1
    assert jobs.minted[0]["service_id"] == created["id"]
    runtime = get_embedding_runtime()
    assert runtime is not None
    assert runtime.ready is False
    assert embedding_configured() is False
    assert embedding_write_enabled(incremental=True) is True


def test_in_use_locks_model_and_protocol(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    locked = client.patch(
        f"/model-services/{created['id']}",
        json={"model": "other"},
    )
    assert_problem(locked, status=409, code="MODEL_SERVICE_WIRE_IMMUTABLE")
    protocol = client.patch(
        f"/model-services/{created['id']}",
        json={"protocol": "openai_compat", "model": created["model"]},
    )
    assert protocol.status_code == 200


def test_url_change_requires_secret_and_rebuilds(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs.minted.clear()
    denied = client.patch(
        f"/model-services/{created['id']}",
        json={"url": "http://embed.other:8080/v1/embeddings"},
    )
    assert_problem(denied, status=409, code="MODEL_SERVICE_SECRET_REQUIRED")
    updated = client.patch(
        f"/model-services/{created['id']}",
        json={
            "url": "http://embed.other:8080/v1/embeddings",
            "api_key": "sk-new",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["url"].endswith("/embeddings")
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["ready"] is False
    assert purpose.json()["generation"] == 2
    assert len(jobs.minted) == 1


def test_secret_only_keeps_hybrid_without_rebuild(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    store = get_model_service_store()
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.minted.clear()
    patched = client.patch(
        f"/model-services/{created['id']}",
        json={"api_key": "sk-rotated"},
    )
    assert patched.status_code == 200
    assert embedding_configured() is True
    assert jobs.minted == []
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["ready"] is True
    assert purpose.json()["generation"] == 1


def test_close_is_lexical_and_stops_incremental_writes(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    assert embedding_configured() is True
    closed = client.post("/model-services/purpose/embedding/close")
    assert closed.status_code == 200
    assert closed.json()["closed"] is True
    assert closed.json()["ready"] is True
    assert embedding_configured() is False
    assert embedding_write_enabled(incremental=True) is False
    assert embedding_write_enabled(incremental=False) is True
    assert jobs.cancels == 1
    jobs.minted.clear()
    client.post(f"/model-services/{created['id']}/activate")
    assert len(jobs.minted) == 1
    assert get_model_service_store().get_purpose("embedding").closed is True


def test_open_none_restores_hybrid_when_ready(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    client.post("/model-services/purpose/embedding/close")
    jobs.minted.clear()
    opened = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert opened.status_code == 200
    assert opened.json()["closed"] is False
    assert opened.json()["ready"] is True
    assert jobs.minted == []
    assert embedding_configured() is True


def test_open_none_without_ready_stays_lexical(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    client.post("/model-services/purpose/embedding/close")
    jobs.minted.clear()
    opened = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert opened.json()["ready"] is False
    assert jobs.minted == []
    assert embedding_configured() is False


def test_open_full_clears_ready_and_mints(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    client.post("/model-services/purpose/embedding/close")
    jobs.minted.clear()
    opened = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "full"},
    )
    assert opened.json()["closed"] is False
    assert opened.json()["ready"] is False
    assert opened.json()["generation"] == 2
    assert len(jobs.minted) == 1
    assert embedding_configured() is False


def test_open_without_in_use_rejected(client: TestClient) -> None:
    _login(client)
    response = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert_problem(response, status=409, code="MODEL_SERVICE_NOT_IN_USE")


def test_cleanup_forbidden_while_open_and_in_use(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    denied = client.post("/model-services/purpose/embedding/cleanup")
    assert_problem(denied, status=409, code="MODEL_SERVICE_CLEANUP_FORBIDDEN")
    client.post("/model-services/purpose/embedding/close")
    jobs.cancels = 0
    cleaned = client.post("/model-services/purpose/embedding/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["ready"] is False
    assert jobs.clears == 1
    assert jobs.cancels == 1


def test_reindex_clears_ready_and_mints(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.minted.clear()
    rebuilt = client.post("/model-services/purpose/embedding/reindex")
    assert rebuilt.json()["ready"] is False
    assert rebuilt.json()["generation"] == 2
    assert len(jobs.minted) == 1
    assert embedding_configured() is False


def test_delete_in_use_cancels_and_is_lexical(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.cancels = 0
    deleted = client.delete(f"/model-services/{created['id']}")
    assert deleted.status_code == 204
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["in_use_id"] is None
    assert jobs.cancels == 1
    assert jobs.clears == 0
    assert get_embedding_runtime() is None
    assert embedding_configured() is False


def test_delete_draft_does_not_cancel(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    in_use = _create(client, display_name="live")
    draft = _create(client, display_name="draft")
    client.post(f"/model-services/{in_use['id']}/activate")
    jobs.cancels = 0
    deleted = client.delete(f"/model-services/{draft['id']}")
    assert deleted.status_code == 204
    assert jobs.cancels == 0
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["in_use_id"] == in_use["id"]


def test_display_name_only_skips_probe_and_rebuild(
    client: TestClient, jobs: RecordingJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.minted.clear()
    called = {"n": 0}

    def boom(**kwargs):
        called["n"] += 1
        raise AssertionError("probe must not run")

    monkeypatch.setattr("backend.admin.model_services.service.probe_embeddings", boom)
    patched = client.patch(
        f"/model-services/{created['id']}",
        json={"display_name": "Renamed"},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Renamed"
    assert called["n"] == 0
    assert jobs.minted == []
    assert embedding_configured() is True


def test_audit_omits_secret(client: TestClient) -> None:
    _login(client)
    created = _create(client, api_key="sk-secret-value")
    events, _ = get_audit_store().list_events()
    blob = str([event.detail for event in events if event.resource_id == created["id"]])
    assert "sk-secret-value" not in blob


def test_dead_embedding_env_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("REFRAQ_EMBEDDING_API_URL", "http://legacy/v1/embeddings")
    monkeypatch.setenv("REFRAQ_EMBEDDING_MODEL", "legacy")
    with caplog.at_level(logging.WARNING, logger="backend.worker.parameters"):
        assemble_system_parameters()
    assert "REFRAQ_EMBEDDING_API_URL" in caplog.text
    assert "ignored" in caplog.text
    assert embedding_configured() is False


def _finish_catalog_embed(job_id: str):
    from backend.metadata.catalog_embed_jobs import run_catalog_embed_job

    current = get_job_store().get(job_id)
    assert current is not None
    if current.status == "queued":
        run_catalog_embed_job(job_id)
        current = get_job_store().get(job_id)
        assert current is not None
    return current


def _seed_embed_target(
    *,
    source_id: str = "src_embed",
    object_count: int = 1,
    columns_per_object: int = 1,
) -> None:
    reset_source_store()
    reset_catalog_store()
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id=source_id,
            key="embed-src",
            locator_key="src/postgresql/embed-src",
            name="Embed",
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
    collected: list[CatalogObjectRecord] = []
    for i in range(object_count):
        obj_id = f"obj_embed_{i}"
        name = f"t{i}"
        collected.append(
            CatalogObjectRecord(
                id=obj_id,
                source_id=source_id,
                locator_key=f"obj/postgresql/embed-src/public/table/{name}",
                object_type="table",
                schema_name="public",
                name=name,
                ddl=f"CREATE TABLE {name} (id int)",
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
                    CatalogColumnRecord(
                        id=f"col_embed_{i}_{j}",
                        object_id=obj_id,
                        locator_key=(
                            f"col/postgresql/embed-src/public/table/{name}/column/c{j}"
                        ),
                        name=f"c{j}",
                        ordinal=j,
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
                    for j in range(columns_per_object)
                ],
            )
        )
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="job_embed_seed",
        collected=collected,
        schema_scope=None,
        fail_safe_threshold=1.0,
    )


def test_real_catalog_embed_job_marks_ready(client: TestClient) -> None:
    reset_source_store()
    reset_catalog_store()
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    _login(client)
    created = _create(client)
    activated = client.post(f"/model-services/{created['id']}/activate")
    assert activated.status_code == 200
    jobs, total = get_job_store().list(kind="catalog_embed")
    assert total == 1
    assert jobs[0].trigger_kind == "user"
    assert jobs[0].input["model_service_id"] == created["id"]
    record = _finish_catalog_embed(jobs[0].id)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["objects_written"] == 0
    assert record.result["objects_attempted"] == 0
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is True
    assert embedding_configured() is True


def test_catalog_embed_zero_writes_fails(client: TestClient) -> None:
    _seed_embed_target()
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())

    def boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    set_embed_fn_for_tests(boom)
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs, _ = get_job_store().list(kind="catalog_embed")
    record = _finish_catalog_embed(jobs[0].id)
    assert record.status == "failed"
    assert record.error_code == "JOB_EXECUTION_FAILED"
    assert record.error_summary is not None
    assert "embed down" in record.error_summary
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is False
    set_embed_fn_for_tests(None)


def test_catalog_embed_partial_row_failure_still_ready(client: TestClient) -> None:
    # 8 objects × 4 columns = 40 pending items (two embed batches).
    _seed_embed_target(object_count=8, columns_per_object=4)
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())

    calls = {"n": 0}

    def flaky(texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("column embed failed")
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(flaky)
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs, _ = get_job_store().list(kind="catalog_embed")
    record = _finish_catalog_embed(jobs[0].id)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["objects_written"] + record.result["columns_written"] == 32
    assert record.result["objects_failed"] + record.result["columns_failed"] == 8
    assert record.result["failure_reasons"] == [
        {"message": "column embed failed", "count": 8}
    ]
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is True
    set_embed_fn_for_tests(None)
