"""Model Service lifecycle, purpose switches, and Catalog Search hybrid gate."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.model_services import (  # noqa: E402
    bind_catalog_embed_jobs,
    bind_entity_embed_jobs,
    get_embedding_runtime,
    mark_embedding_ready,
)
from backend.admin.model_services.errors import ModelServiceTimeout  # noqa: E402
from backend.admin.model_services.ports import (  # noqa: E402
    CatalogEmbedJobsPort,
    EntityEmbedJobsPort,
    catalog_embed_jobs,
)
from backend.admin.model_services.records import (  # noqa: E402
    CatalogIndexView,
    EntityIndexView,
)
from backend.admin.model_services.store import get_model_service_store  # noqa: E402
from backend.admin.permissions import ALL_PERMISSIONS  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.session_store import MemorySessionStore, get_session_store  # noqa: E402
from backend.admin.user_store import MemoryUserStore, get_user_store  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    claim_queued,
    create_queued_job,
    get_job_store,
    mark_failed,
    mark_succeeded,
    reset_job_store,
)
from backend.main import app  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.metadata.catalog.embedding import (  # noqa: E402
    embedding_configured,
    embedding_write_enabled,
    set_embed_fn_for_tests,
)
from backend.metadata.catalog.service import search_objects  # noqa: E402
from backend.metadata.errors import CatalogSearchEmbedFailed  # noqa: E402
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.entity.embed_jobs import EntityEmbedJobs  # noqa: E402
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
        self.triggered: list[dict[str, object]] = []
        self.clears = 0
        self._status: str | None = None
        self.fail_trigger = False
        self._index = CatalogIndexView()

    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str:
        if self.fail_trigger:
            raise RuntimeError("queue delivery failed")
        self.triggered.append(
            {
                "actor_user_id": actor_user_id,
                "actor_token_id": actor_token_id,
            }
        )
        self._status = "queued"
        return f"job_{len(self.triggered)}"

    def has_active(self) -> bool:
        return self._status in {"queued", "running"}

    def clear_index(self) -> None:
        self.clears += 1

    def latest_sweep_status(self) -> str | None:
        return self._status

    def schedule_view(self):
        return None

    def index_view(self) -> CatalogIndexView:
        return self._index

    def publish_index(
        self,
        *,
        generation: int,
        objects_written: int = 0,
        columns_written: int = 0,
        objects_failed: int = 0,
        columns_failed: int = 0,
        objects_attempted: int = 0,
        columns_attempted: int = 0,
        progress: str | None = None,
        failure_summary: str | None = None,
    ) -> None:
        self._index = CatalogIndexView(
            ready=True,
            generation_last_swept=generation,
            objects_written=objects_written,
            columns_written=columns_written,
            objects_failed=objects_failed,
            columns_failed=columns_failed,
            objects_attempted=objects_attempted,
            columns_attempted=columns_attempted,
            progress=progress,
            failure_summary=failure_summary,
            rebuild_owed=False,
        )

    def clear_index_ready(self, *, rebuild_owed: bool) -> None:
        self._index = replace(self._index, ready=False, rebuild_owed=rebuild_owed)

    def note_index_failure(
        self,
        *,
        failure_summary: str,
        objects_written: int = 0,
        columns_written: int = 0,
        objects_failed: int = 0,
        columns_failed: int = 0,
        objects_attempted: int = 0,
        columns_attempted: int = 0,
        progress: str | None = None,
    ) -> None:
        self._index = replace(
            self._index,
            objects_written=objects_written,
            columns_written=columns_written,
            objects_failed=objects_failed,
            columns_failed=columns_failed,
            objects_attempted=objects_attempted,
            columns_attempted=columns_attempted,
            progress=progress if progress is not None else failure_summary,
            failure_summary=failure_summary,
        )


class RecordingEntityJobs(EntityEmbedJobsPort):
    """Keeps Catalog tests off the Entity sweep."""

    def __init__(self) -> None:
        self._index = EntityIndexView()

    def owns_schedule(self, key: str) -> bool:
        return False

    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str:
        return "job_entity_recorded"

    def has_active(self) -> bool:
        return False

    def clear_index(self) -> None:
        return None

    def latest_sweep_status(self) -> str | None:
        return None

    def schedule_view(self):
        return None

    def index_view(self) -> EntityIndexView:
        return self._index

    def clear_index_ready(self, *, rebuild_owed: bool) -> None:
        self._index = replace(self._index, ready=False, rebuild_owed=rebuild_owed)


@pytest.fixture
def jobs() -> RecordingJobs:
    port = RecordingJobs()
    bind_catalog_embed_jobs(port)
    bind_entity_embed_jobs(RecordingEntityJobs())
    yield port
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    bind_entity_embed_jobs(EntityEmbedJobs())


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
        "timeout_sec": 30,
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


def test_publish_failure_does_not_mark_the_sweep_ready(client: TestClient) -> None:
    _login(client)
    created = _create(client)
    activated = client.post(f"/model-services/{created['id']}/activate")
    assert activated.status_code == 200
    state = get_model_service_store().get_purpose("embedding")
    bind_catalog_embed_jobs(None)
    try:
        with pytest.raises(RuntimeError, match="catalog embed jobs port is not bound"):
            mark_embedding_ready(
                purpose="embedding",
                service_id=created["id"],
                generation=state.generation,
                control_revision=state.control_revision,
            )
        assert get_model_service_store().get_purpose("embedding").ready is False
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
            "timeout_sec": 30,
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


def test_test_service_reports_probe_elapsed(client: TestClient) -> None:
    _login(client)
    created = _create(client)
    response = client.post(f"/model-services/{created['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["dimension"] == 8
    assert "search_timeout_sec" not in body
    assert "within_search_timeout" not in body
    assert body["output_dim"] == 1024
    assert body["elapsed_ms"] >= 0
    assert body["timeout_sec"] == 30


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
            "timeout_sec": 30,
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
    assert len(jobs.triggered) == 1
    assert jobs.triggered[0]["actor_user_id"]
    runtime = get_embedding_runtime()
    assert runtime is not None
    assert runtime.ready is False
    assert embedding_configured() is False
    assert embedding_write_enabled() is True


def test_catalog_index_ready_selects_vector_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Search follows the Catalog index, not the purpose ready bit."""
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    store = get_model_service_store()
    state = store.get_purpose("embedding")
    store.save_purpose(replace(state, ready=True))

    lexical = search_objects("cust", visible_source_ids=None, limit=5, offset=0)
    assert lexical.rank_mode == "lexical"
    assert embedding_configured() is False
    body = client.get("/model-services/purpose/embedding").json()
    assert body["catalog_index"]["ready"] is False
    assert body["catalog_index"]["generation_last_swept"] is None
    assert body["catalog_index"]["rebuild_owed"] is True
    assert body["entity_index"]["ready"] is False
    assert body["entity_index"]["rebuild_owed"] is True

    mark_embedding_ready(
        purpose="embedding", service_id=created["id"], generation=1, control_revision=1
    )
    store.save_purpose(replace(store.get_purpose("embedding"), ready=False))
    calls = {"n": 0}

    def _embed(_texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        return [[0.2, 0.8]]

    monkeypatch.setattr(
        "backend.metadata.catalog.search_hybrid.embed_texts", _embed
    )
    vector = search_objects("cust", visible_source_ids=None, limit=5, offset=0)
    assert vector.rank_mode == "vector"
    assert calls["n"] == 1
    assert embedding_configured() is True
    shown = client.get("/model-services/purpose/embedding").json()
    assert shown["ready"] is True
    assert shown["catalog_index"]["ready"] is True
    assert shown["catalog_index"]["generation_last_swept"] == 1
    assert shown["catalog_index"]["rebuild_owed"] is False
    assert shown["catalog_index"]["index_status"] == "ready"
    assert shown["entity_index"]["ready"] is False

    def _boom(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embed down")

    monkeypatch.setattr(
        "backend.metadata.catalog.search_hybrid.embed_texts", _boom
    )
    with pytest.raises(CatalogSearchEmbedFailed):
        search_objects("cust", visible_source_ids=None, limit=5, offset=0)


def test_batch_limit_defaults_to_32_and_rejects_out_of_range(client: TestClient) -> None:
    _login(client)
    created = _create(client)
    assert created["batch_limit"] == 32
    shown = client.get(f"/model-services/{created['id']}")
    assert shown.json()["batch_limit"] == 32
    for bad in (0, 33, -1):
        rejected = client.post(
            "/model-services",
            json={
                "display_name": "Office TEI",
                "url": "http://embed.internal:8080/v1/embeddings",
                "model": "Qwen3-Embedding-8B",
                "timeout_sec": 30,
                "batch_limit": bad,
            },
        )
        assert_problem(rejected, status=400, code="MODEL_SERVICE_INVALID_CONFIG")


def test_timeout_sec_is_required_and_bounded(client: TestClient) -> None:
    _login(client)
    missing = client.post(
        "/model-services",
        json={
            "display_name": "Office TEI",
            "url": "http://embed.internal:8080/v1/embeddings",
            "model": "Qwen3-Embedding-8B",
        },
    )
    assert missing.status_code == 422
    for bad in (14, 301):
        rejected = client.post(
            "/model-services",
            json={
                "display_name": "Office TEI",
                "url": "http://embed.internal:8080/v1/embeddings",
                "model": "Qwen3-Embedding-8B",
                "timeout_sec": bad,
            },
        )
        assert_problem(rejected, status=400, code="MODEL_SERVICE_INVALID_CONFIG")


def test_batch_limit_edit_does_not_advance_generation_or_clear_ready(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    updated = client.patch(
        f"/model-services/{created['id']}",
        json={"batch_limit": 8},
    )
    assert updated.status_code == 200
    assert updated.json()["batch_limit"] == 8
    purpose = client.get("/model-services/purpose/embedding").json()
    assert purpose["generation"] == 1
    assert purpose["ready"] is True
    assert jobs.triggered == []
    assert embedding_configured() is True
    runtime = get_embedding_runtime()
    assert runtime is not None
    assert runtime.batch_limit == 8


def test_patch_timeout_does_not_rebuild(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client, timeout_sec=30)
    client.post(f"/model-services/{created['id']}/activate")
    purpose_before = client.get("/model-services/purpose/embedding").json()
    minted = len(jobs.triggered)
    updated = client.patch(
        f"/model-services/{created['id']}",
        json={"timeout_sec": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["timeout_sec"] == 120
    purpose_after = client.get("/model-services/purpose/embedding").json()
    assert purpose_after["ready"] == purpose_before["ready"]
    assert purpose_after["generation"] == purpose_before["generation"]
    assert len(jobs.triggered) == minted
    kept = client.patch(
        f"/model-services/{created['id']}",
        json={"display_name": "Office TEI renamed"},
    )
    assert kept.status_code == 200
    assert kept.json()["timeout_sec"] == 120
    runtime = get_embedding_runtime()
    assert runtime is not None
    assert runtime.timeout_sec == 120


def test_in_use_model_change_advances_generation_and_keeps_protocol(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    draft = _create(client, display_name="Draft")
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    updated = client.patch(
        f"/model-services/{created['id']}",
        json={"model": "other-embed"},
    )
    assert updated.status_code == 200
    assert updated.json()["model"] == "other-embed"
    assert updated.json()["protocol"] == "openai_compat"
    purpose = client.get("/model-services/purpose/embedding").json()
    assert purpose["generation"] == 2
    assert purpose["ready"] is False
    assert len(jobs.triggered) == 1
    assert embedding_configured() is False
    untouched = client.patch(
        f"/model-services/{draft['id']}",
        json={"model": "draft-model"},
    )
    assert untouched.status_code == 200
    assert untouched.json()["model"] == "draft-model"
    after_draft = client.get("/model-services/purpose/embedding").json()
    assert after_draft["generation"] == 2
    assert len(jobs.triggered) == 1


def test_in_use_protocol_stays_openai_compat(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs.triggered.clear()
    rejected = client.patch(
        f"/model-services/{created['id']}",
        json={"protocol": "vendor_native"},
    )
    assert rejected.status_code == 422
    kept = client.patch(
        f"/model-services/{created['id']}",
        json={"protocol": "openai_compat"},
    )
    assert kept.status_code == 200
    assert kept.json()["protocol"] == "openai_compat"
    purpose = client.get("/model-services/purpose/embedding").json()
    assert purpose["generation"] == 1
    assert jobs.triggered == []


def test_url_change_requires_secret_and_rebuilds(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs.triggered.clear()
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
    assert len(jobs.triggered) == 1


def test_secret_only_keeps_hybrid_without_rebuild(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    store = get_model_service_store()
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    patched = client.patch(
        f"/model-services/{created['id']}",
        json={"api_key": "sk-rotated"},
    )
    assert patched.status_code == 200
    assert embedding_configured() is True
    assert jobs.triggered == []
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["ready"] is True
    assert purpose.json()["generation"] == 1


def test_control_revision_fences_lifecycle_without_joining_generation(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    activated = client.post(f"/model-services/{created['id']}/activate")
    assert activated.status_code == 200
    after_activate = client.get("/model-services/purpose/embedding").json()
    assert after_activate["generation"] == 1
    assert after_activate["control_revision"] == 1
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    closed = client.post("/model-services/purpose/embedding/close")
    assert closed.status_code == 200
    assert closed.json()["generation"] == 1
    assert closed.json()["ready"] is True
    assert closed.json()["control_revision"] == 2
    opened = client.post("/model-services/purpose/embedding/open")
    assert opened.json()["generation"] == 1
    assert opened.json()["ready"] is True
    assert opened.json()["control_revision"] == 3
    jobs._status = None
    client.post("/model-services/purpose/embedding/close")
    cleaned = client.post("/model-services/purpose/embedding/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["generation"] == 1
    assert cleaned.json()["ready"] is False
    assert cleaned.json()["control_revision"] == 5
    assert jobs.clears == 1
    assert len(jobs.triggered) == 1


def test_secret_timeout_and_batch_edits_do_not_bump_control_revision(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    before = client.get("/model-services/purpose/embedding").json()["control_revision"]
    for body in (
        {"api_key": "sk-rotated"},
        {"timeout_sec": 90},
        {"batch_limit": 4},
        {"display_name": "Renamed embedding"},
    ):
        patched = client.patch(f"/model-services/{created['id']}", json=body)
        assert patched.status_code == 200
    after = client.get("/model-services/purpose/embedding").json()
    assert after["control_revision"] == before
    assert after["generation"] == 1
    assert after["ready"] is True
    assert jobs.triggered == []


def test_failed_enqueue_keeps_catalog_rebuild_for_the_next_sweep(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    jobs.fail_trigger = True
    with pytest.raises(RuntimeError, match="queue delivery failed"):
        client.post("/model-services/purpose/embedding/force-generation")
    purpose = client.get("/model-services/purpose/embedding").json()
    assert purpose["generation"] == 2
    assert purpose["ready"] is False
    assert purpose["catalog_index"]["ready"] is False
    assert purpose["catalog_index"]["rebuild_owed"] is True
    assert purpose["control_revision"] == 2
    assert jobs.triggered == []
    assert jobs.clears == 0

    reset_job_store()
    owed = create_queued_job(kind="catalog_embed", input={})
    record = _finish_catalog_embed(owed.id)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["generation"] == 2
    assert record.result["outcome"] == "completed"
    settled = get_model_service_store().get_purpose("embedding")
    assert settled.generation == 2
    assert settled.ready is True
    settled_index = client.get("/model-services/purpose/embedding").json()["catalog_index"]
    assert settled_index["ready"] is True
    assert settled_index["generation_last_swept"] == 2
    assert settled_index["rebuild_owed"] is False


def test_force_generation_rebuilds_without_deleting_vectors(
    client: TestClient, jobs: RecordingJobs
) -> None:
    from backend.metadata.catalog.embedding import CatalogEmbeddingRecord
    from backend.metadata.catalog.store import get_catalog_store

    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
    kept = CatalogEmbeddingRecord(
        id="emb_kept",
        kind="object",
        target_id="obj_kept",
        locator_key="obj/postgresql/embed-src/public/table/kept",
        content_hash="abc",
        embedding=[0.1, 0.2],
        indexed_at=utc_now(),
        generation=1,
    )
    get_catalog_store().upsert_embedding(kept)
    forced = client.post("/model-services/purpose/embedding/force-generation")
    assert forced.status_code == 200
    body = forced.json()
    assert body["generation"] == 2
    assert body["ready"] is False
    assert body["catalog_index"]["ready"] is False
    assert body["catalog_index"]["rebuild_owed"] is True
    assert body["control_revision"] == 2
    assert body["in_use_id"] == created["id"]
    assert len(jobs.triggered) == 1
    assert jobs.clears == 0
    stored = get_catalog_store().get_embedding(kind="object", target_id="obj_kept")
    assert stored is not None
    assert stored.embedding == [0.1, 0.2]
    shown = client.get(f"/model-services/{created['id']}").json()
    assert shown["url"] == created["url"]
    assert shown["model"] == created["model"]
    missing = client.post("/model-services/purpose/embedding/force-generation")
    # Still in use, so a second force advances again.
    assert missing.status_code == 200
    assert missing.json()["generation"] == 3
    client.delete(f"/model-services/{created['id']}")
    denied = client.post("/model-services/purpose/embedding/force-generation")
    assert_problem(denied, status=409, code="MODEL_SERVICE_NOT_IN_USE")


def test_close_is_lexical(
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
    assert closed.json()["catalog_index"]["ready"] is True
    assert closed.json()["catalog_index"]["rebuild_owed"] is False
    assert embedding_configured() is False
    assert len(jobs.triggered) == 1
    assert jobs.clears == 0
    jobs.triggered.clear()
    client.post(f"/model-services/{created['id']}/activate")
    assert len(jobs.triggered) == 1
    assert get_model_service_store().get_purpose("embedding").closed is True


def test_open_none_restores_hybrid_when_ready(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    client.post("/model-services/purpose/embedding/close")
    jobs.triggered.clear()
    opened = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert opened.status_code == 200
    assert opened.json()["closed"] is False
    assert opened.json()["ready"] is True
    assert jobs.triggered == []
    assert embedding_configured() is True


def test_open_none_without_ready_stays_lexical(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    client.post("/model-services/purpose/embedding/close")
    jobs.triggered.clear()
    opened = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert opened.json()["ready"] is False
    assert jobs.triggered == []
    assert embedding_configured() is False


def test_open_does_not_mint(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    client.post("/model-services/purpose/embedding/close")
    jobs.triggered.clear()
    opened = client.post("/model-services/purpose/embedding/open")
    assert opened.json()["closed"] is False
    assert opened.json()["ready"] is True
    assert opened.json()["generation"] == 1
    assert jobs.triggered == []
    assert embedding_configured() is True


def test_open_without_in_use_rejected(client: TestClient) -> None:
    _login(client)
    response = client.post(
        "/model-services/purpose/embedding/open",
        json={"rebuild": "none"},
    )
    assert_problem(response, status=409, code="MODEL_SERVICE_NOT_IN_USE")


def test_cleanup_deletes_catalog_vectors_without_refill(client: TestClient) -> None:
    from backend.metadata.catalog.embedding import CatalogEmbeddingRecord
    from backend.metadata.catalog.store import get_catalog_store

    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    _login(client)
    created = _create(client)
    activated = client.post(f"/model-services/{created['id']}/activate")
    assert activated.status_code == 200
    queued, total = get_job_store().list(kind="catalog_embed")
    assert total == 1
    finished = _finish_catalog_embed(queued[0].id)
    assert finished.status == "succeeded"
    kept = CatalogEmbeddingRecord(
        id="emb_cleanup",
        kind="object",
        target_id="obj_cleanup",
        locator_key="obj/postgresql/embed-src/public/table/cleanup",
        content_hash="abc",
        embedding=[0.4, 0.6],
        indexed_at=utc_now(),
        generation=1,
    )
    get_catalog_store().upsert_embedding(kept)
    closed = client.post("/model-services/purpose/embedding/close")
    assert closed.status_code == 200
    assert closed.json()["generation"] == 1
    assert closed.json()["catalog_index"]["ready"] is True
    assert get_catalog_store().get_embedding(kind="object", target_id="obj_cleanup") is not None
    cleaned = client.post("/model-services/purpose/embedding/cleanup")
    assert cleaned.status_code == 200
    body = cleaned.json()
    assert body["generation"] == 1
    assert body["catalog_index"]["ready"] is False
    assert body["catalog_index"]["rebuild_owed"] is False
    assert body["in_use_id"] == created["id"]
    assert get_catalog_store().get_embedding(kind="object", target_id="obj_cleanup") is None
    _jobs, after = get_job_store().list(kind="catalog_embed")
    assert after == 1


def test_cleanup_forbidden_while_open_and_in_use(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    denied = client.post("/model-services/purpose/embedding/cleanup")
    assert_problem(denied, status=409, code="MODEL_SERVICE_CLEANUP_FORBIDDEN")
    client.post("/model-services/purpose/embedding/close")
    jobs._status = None
    cleaned = client.post("/model-services/purpose/embedding/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["ready"] is False
    assert jobs.clears == 1


def test_cleanup_refused_while_embed_job_active(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    client.post("/model-services/purpose/embedding/close")
    denied = client.post("/model-services/purpose/embedding/cleanup")
    assert_problem(denied, status=409, code="MODEL_SERVICE_CLEANUP_BUSY")
    assert jobs.clears == 0


def test_delete_in_use_leaves_index_and_is_lexical(
    client: TestClient, jobs: RecordingJobs
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    deleted = client.delete(f"/model-services/{created['id']}")
    assert deleted.status_code == 204
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["in_use_id"] is None
    assert jobs.clears == 0
    assert get_embedding_runtime() is None
    assert embedding_configured() is False


def test_delete_draft_does_not_cancel(client: TestClient, jobs: RecordingJobs) -> None:
    _login(client)
    in_use = _create(client, display_name="live")
    draft = _create(client, display_name="draft")
    client.post(f"/model-services/{in_use['id']}/activate")
    deleted = client.delete(f"/model-services/{draft['id']}")
    assert deleted.status_code == 204
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.json()["in_use_id"] == in_use["id"]


def test_display_name_only_skips_probe_and_rebuild(
    client: TestClient, jobs: RecordingJobs, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    mark_embedding_ready(purpose="embedding", service_id=created["id"], generation=1)
    jobs.triggered.clear()
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
    assert jobs.triggered == []
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
    )


def _mint_catalog_embed(*, created_at, trigger_ref: str):
    return create_queued_job(
        kind="catalog_embed",
        input={},
        summary="catalog_embed",
        trigger_kind="schedule",
        trigger_ref=trigger_ref,
        created_at=created_at,
    )


def _skip_catalog_embed(job_id: str) -> None:
    assert claim_queued(job_id) is not None
    marked = mark_succeeded(
        job_id,
        result={
            "schema": "catalog_embed.v1",
            "outcome": "skipped",
            "reason": "already_active",
        },
    )
    assert marked is not None
    assert marked.status == "succeeded"


def test_index_status_stays_indexing_when_a_later_job_skips(
    client: TestClient,
) -> None:
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    earlier = utc_now() - timedelta(seconds=5)
    sweep = _mint_catalog_embed(created_at=earlier, trigger_ref="sched_site")
    assert claim_queued(sweep.id) is not None
    skipped = _mint_catalog_embed(created_at=utc_now(), trigger_ref="sched_site")
    _skip_catalog_embed(skipped.id)
    _login(client)
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.status_code == 200
    assert purpose.json()["index_status"] == "indexing"
    assert purpose.json()["ready"] is False


def test_index_status_stays_failed_when_a_later_job_skips(
    client: TestClient,
) -> None:
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    earlier = utc_now() - timedelta(seconds=5)
    sweep = _mint_catalog_embed(created_at=earlier, trigger_ref="sched_site")
    failed = mark_failed(
        sweep.id, error_code="JOB_EXECUTION_FAILED", error_summary="embed down"
    )
    assert failed is not None
    assert failed.status == "failed"
    skipped = _mint_catalog_embed(created_at=utc_now(), trigger_ref="sched_site")
    _skip_catalog_embed(skipped.id)
    _login(client)
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.status_code == 200
    assert purpose.json()["index_status"] == "failed"


def test_embed_schedule_omits_sweep_projection(client: TestClient) -> None:
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    _login(client)
    purpose = client.get("/model-services/purpose/embedding")
    assert purpose.status_code == 200
    embed = purpose.json()["embed_schedule"]
    assert embed is not None
    assert "last_sweep_job_id" not in embed
    assert "last_sweep_job_status" not in embed
    assert "last_sweep_job_finished_at" not in embed


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
    assert jobs[0].trigger_kind == "schedule"
    assert jobs[0].input == {}
    record = _finish_catalog_embed(jobs[0].id)
    assert record.status == "succeeded"
    assert record.result is not None
    assert record.result["objects_written"] == 0
    assert record.result["objects_attempted"] == 0
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is True
    assert embedding_configured() is True
    index = client.get("/model-services/purpose/embedding").json()["catalog_index"]
    assert index["ready"] is True
    assert index["generation_last_swept"] == 1
    assert index["rebuild_owed"] is False
    assert index["failure_summary"] is None
    assert index["coverage"]["objects_attempted"] == 0
    assert index["coverage"]["columns_attempted"] == 0


def test_catalog_sweep_zero_writes_stays_unready_and_records_failure(
    client: TestClient,
) -> None:
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
    index = client.get("/model-services/purpose/embedding").json()["catalog_index"]
    assert index["ready"] is False
    assert index["rebuild_owed"] is True
    assert index["generation_last_swept"] is None
    assert index["failure_summary"] == (
        "catalog_embed wrote no vectors for a non-empty catalog: embed down"
    )
    assert index["coverage"]["objects_written"] == 0
    assert index["coverage"]["columns_written"] == 0
    assert index["coverage"]["objects_failed"] == 1
    assert index["coverage"]["columns_failed"] == 1
    set_embed_fn_for_tests(None)


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


def test_catalog_sweep_records_coverage_and_still_marks_ready(
    client: TestClient,
) -> None:
    # 8 objects × 4 columns = 40 targets. The second batch of 8 fails.
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
    index = client.get("/model-services/purpose/embedding").json()["catalog_index"]
    coverage = index["coverage"]
    assert index["ready"] is True
    assert index["generation_last_swept"] == 1
    assert index["rebuild_owed"] is False
    assert coverage["objects_written"] == 7
    assert coverage["columns_written"] == 25
    assert coverage["objects_failed"] == 1
    assert coverage["columns_failed"] == 7
    assert coverage["objects_attempted"] == 8
    assert coverage["columns_attempted"] == 32
    assert index["failure_summary"] == "column embed failed"
    assert index["progress"] == (
        "indexed 7 objects and 25 columns (failed 1/7); "
        "last error: column embed failed (×8)"
    )
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


def test_catalog_sweep_timeouts_exceeding_writes_stay_unready(
    client: TestClient,
) -> None:
    _seed_embed_target(object_count=8, columns_per_object=4)
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())

    def timed_out(_texts: list[str]) -> list[list[float]]:
        raise ModelServiceTimeout(
            "Embeddings request timed out after 30s calling http://embed.test/v1/embeddings"
        )

    set_embed_fn_for_tests(timed_out)
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs, _ = get_job_store().list(kind="catalog_embed")
    record = _finish_catalog_embed(jobs[0].id)
    assert record.status == "failed"
    index = client.get("/model-services/purpose/embedding").json()["catalog_index"]
    assert index["ready"] is False
    assert index["rebuild_owed"] is True
    assert index["failure_summary"] == (
        "catalog_embed stopped: embedding timeouts exceed writes: "
        "Embeddings request timed out after 30s calling http://embed.test/v1/embeddings"
    )
    assert index["coverage"]["objects_written"] == 0
    assert index["coverage"]["columns_written"] == 0
    assert index["coverage"]["objects_failed"] == 7
    assert index["coverage"]["columns_failed"] == 25
    set_embed_fn_for_tests(None)


def test_catalog_embed_timeouts_exceeding_writes_does_not_ready(
    client: TestClient,
) -> None:
    # 8 objects × 4 columns = 40 pending items (two embed batches).
    _seed_embed_target(object_count=8, columns_per_object=4)
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())

    calls = {"n": 0}

    def timed_out(_texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        raise ModelServiceTimeout(
            "Embeddings request timed out after 30s calling http://embed.test/v1/embeddings"
        )

    set_embed_fn_for_tests(timed_out)
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs, _ = get_job_store().list(kind="catalog_embed")
    record = _finish_catalog_embed(jobs[0].id)
    assert calls["n"] == 1
    assert record.status == "failed"
    assert record.error_code == "JOB_EXECUTION_FAILED"
    assert record.error_summary is not None
    assert "embedding timeouts exceed writes" in record.error_summary
    assert "timed out" in record.error_summary
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is False
    set_embed_fn_for_tests(None)


def test_catalog_embed_timeout_while_ahead_still_ready(client: TestClient) -> None:
    # First batch of 32 writes; the tail batch of 8 times out.
    _seed_embed_target(object_count=8, columns_per_object=4)
    reset_job_store()
    bind_catalog_embed_jobs(CatalogEmbedJobs())

    calls = {"n": 0}

    def mostly_ok(texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise ModelServiceTimeout(
                "Embeddings request timed out after 30s calling http://embed.test/v1/embeddings"
            )
        return [[1.0, 0.0] for _ in texts]

    set_embed_fn_for_tests(mostly_ok)
    _login(client)
    created = _create(client)
    client.post(f"/model-services/{created['id']}/activate")
    jobs, _ = get_job_store().list(kind="catalog_embed")
    record = _finish_catalog_embed(jobs[0].id)
    assert calls["n"] == 2
    assert record.status == "succeeded"
    assert record.result is not None
    written = record.result["objects_written"] + record.result["columns_written"]
    failed = record.result["objects_failed"] + record.result["columns_failed"]
    assert written == 32
    assert failed == 8
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.ready is True
    set_embed_fn_for_tests(None)
