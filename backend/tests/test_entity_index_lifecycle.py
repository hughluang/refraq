"""Entity index sweep, schedule, fencing, and cleanup."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.model_services.embeddings import EmbeddingSpace, EmbeddingVectors  # noqa: E402
from backend.admin.model_services.errors import (  # noqa: E402
    ModelServiceControlRevisionMismatch,
    ModelServiceGenerationMismatch,
)
from backend.admin.model_services.records import (  # noqa: E402
    CURRENT_PROCESSING_CONTRACT,
    ModelServiceRecord,
    PurposeState,
)
from backend.admin.model_services.store import get_model_service_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.embed_jobs import EntityEmbedJobs  # noqa: E402
from backend.entity.embed_jobs.runner import run_entity_embed_job  # noqa: E402
from backend.entity.embed_jobs.schedule import (  # noqa: E402
    ENTITY_EMBED_SCHEDULE_KEY,
    ensure_entity_embed_schedule,
    fire_scheduled_entity_embed,
    run_entity_embed_schedule_now,
)
from backend.entity.kinds import KIND_EMBED  # noqa: E402
from backend.entity.locks import (  # noqa: E402
    reset_entity_table_locks_for_tests,
    try_acquire_entity_embed_lock,
)
from backend.entity.projection import (  # noqa: E402
    current_projection,
    definition_text,
    retain_projection,
)
from backend.entity.records import AttributeRecord  # noqa: E402
from backend.entity.service import (  # noqa: E402
    create_entity,
    deprecate_entity,
    open_version,
    patch_entity,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.jobs.store import create_queued_job, get_job_store  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.catalog.index_state import get_catalog_index_store  # noqa: E402
from backend.metadata.source_job_runner.kind_locks import (  # noqa: E402
    try_acquire_named_execution_lock,
)
from backend.worker.schedules import get_schedule_store  # noqa: E402

_SKU = AttributeRecord(name="sku", type="string", max_length=32, required=True, unique=True)
_SERVICE_ID = "msvc_entity_lifecycle"


def _vectors(generation: int) -> EmbeddingVectors:
    return EmbeddingVectors(
        vectors=[[1.0, 0.0]],
        space=EmbeddingSpace(
            service_id=_SERVICE_ID,
            generation=generation,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        ),
    )


def _seed_model(*, generation: int = 1, closed: bool = False, control_revision: int = 1) -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id=_SERVICE_ID,
            purpose="embedding",
            protocol="openai_compat",
            display_name="lifecycle",
            url="http://embed.test/v1/embeddings",
            model="qwen-test",
            timeout_sec=30,
            batch_limit=32,
            secret="sk-test",
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id=_SERVICE_ID,
            closed=closed,
            ready=False,
            generation=generation,
            control_revision=control_revision,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        )
    )


def _writer():
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.user_store import get_user_store

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    return get_user_store().create_user(
        account=f"entity_idx_{uuid.uuid4().hex[:8]}",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )


def _publish(entity_id: str, monkeypatch: pytest.MonkeyPatch) -> str:
    from backend.entity.align import run_entity_table_job
    from backend.entity.lifecycle import latest_published_of
    from backend.entity.publish import accept
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()

    def _inline(job: object) -> str:
        run_entity_table_job(getattr(job, "id"))
        return str(getattr(job, "id"))

    monkeypatch.setattr("backend.entity.jobs.dispatch_entity_job", _inline)
    monkeypatch.setattr(
        "backend.entity.embed_jobs.schedule.dispatch_entity_job",
        lambda job: getattr(job, "id"),
    )
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    job, created = accept(
        entity_id=entity_id,
        version_id=current.id,
        actor_user_id="usr_entity_index",
        actor_token_id=None,
    )
    assert created
    finished = get_job_store().get(job.id)
    assert finished is not None and finished.status == "succeeded", finished.error_summary
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return head.id


def _serving(monkeypatch: pytest.MonkeyPatch, *, table_name: str, name: str) -> str:
    _writer()
    saved = create_entity(
        table_name=table_name,
        name=name,
        description="A stock item",
        attributes=[_SKU],
        actor_user_id=None,
        actor_token_id=None,
    )
    entity_id = str(saved["id"])
    _publish(entity_id, monkeypatch)
    return entity_id


def _queue_embed() -> str:
    record = ensure_entity_embed_schedule()
    job = create_queued_job(
        kind=KIND_EMBED,
        input={},
        summary="entity_embed",
        trigger_kind="schedule",
        trigger_ref=record.id,
    )
    return job.id


@pytest.fixture(autouse=True)
def _reset() -> None:
    from backend.admin.model_services.ports import bind_entity_embed_jobs
    from backend.admin.model_services.store import reset_model_service_store
    from backend.admin.role_store import reset_role_store
    from backend.admin.user_store import reset_user_store
    from backend.entity.embed_jobs.index_state import reset_entity_index_store
    from backend.entity.projection import reset_entity_projection_store
    from backend.entity.store import reset_entity_store
    from backend.entity.table_port import reset_entity_table_port
    from backend.jobs.store import reset_job_store
    from backend.metadata.catalog.index_state import reset_catalog_index_store

    reset_entity_store()
    reset_entity_projection_store()
    reset_entity_index_store()
    reset_catalog_index_store()
    reset_job_store()
    reset_model_service_store()
    reset_user_store()
    reset_role_store()
    reset_entity_table_port()
    reset_entity_table_locks_for_tests()
    schedule_store = get_schedule_store()
    stale = schedule_store.get_by_key(ENTITY_EMBED_SCHEDULE_KEY)
    if stale is not None:
        schedule_store.delete(stale.id)
    bind_entity_embed_jobs(EntityEmbedJobs())
    yield
    reset_entity_table_locks_for_tests()
    leftover = schedule_store.get_by_key(ENTITY_EMBED_SCHEDULE_KEY)
    if leftover is not None:
        schedule_store.delete(leftover.id)
    ensure_entity_embed_schedule()
    bind_entity_embed_jobs(EntityEmbedJobs())


def test_entity_embed_schedule_is_minted_once_and_not_by_post_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.entity.embed_jobs.schedule.current_schedule_timezone",
        lambda: "UTC",
    )
    store = get_schedule_store()
    existing = store.get_by_key(ENTITY_EMBED_SCHEDULE_KEY)
    if existing is not None:
        store.delete(existing.id)
    seeded = ensure_entity_embed_schedule()
    assert seeded.key == "entity_embed:site"
    assert seeded.cron == "0 3 * * *"
    assert seeded.enabled is True
    assert seeded.undeletable is True
    assert seeded.locked is False
    assert seeded.commitment_timezone == "UTC"
    assert seeded.task_name == (
        "backend.entity.embed_jobs.schedule.fire_scheduled_entity_embed"
    )
    catalog = store.get_by_key("catalog_embed:site")
    assert catalog is None or catalog.id != seeded.id

    revised = store.upsert(replace(seeded, cron="15 4 * * *", enabled=False))
    again = ensure_entity_embed_schedule()
    assert again.id == revised.id
    assert again.cron == "15 4 * * *"
    assert again.enabled is False

    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.session_store import MemorySessionStore, get_session_store
    from backend.admin.user_store import get_user_store

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=admin.id,
        status="active",
    )
    sessions = MemorySessionStore()
    app.dependency_overrides[get_user_store] = lambda: get_user_store()
    app.dependency_overrides[get_role_store] = lambda: roles
    app.dependency_overrides[get_session_store] = lambda: sessions
    try:
        with TestClient(app) as client:
            assert client.post(
                "/auth/login", json={"account": "root", "password": "s3cret"}
            ).status_code == 200
            denied = client.post("/jobs", json={"kind": "entity_embed"})
            assert denied.status_code == 405
            assert get_job_store().list(kind=KIND_EMBED)[1] == 0
            ran = client.post(f"/schedules/{again.id}/run")
            assert ran.status_code == 202, ran.text
            body = ran.json()["job"]
            assert body["kind"] == "entity_embed"
            assert body["trigger_kind"] == "schedule"
            assert body["trigger_ref"] == again.id
    finally:
        app.dependency_overrides.clear()


def test_due_tick_sweeps_and_a_paused_schedule_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock

    _seed_model()
    monkeypatch.setattr("backend.worker.due.current_schedule_timezone", lambda: "UTC")
    monkeypatch.setattr(
        "backend.entity.projection.embed_texts",
        lambda texts, **kwargs: (_ for _ in ()).throw(AssertionError("no targets")),
    )
    store = get_schedule_store()
    existing = store.get_by_key(ENTITY_EMBED_SCHEDULE_KEY)
    if existing is not None:
        store.delete(existing.id)
    seeded = ensure_entity_embed_schedule()
    slot = parse_instant("2026-08-15T03:00:00Z")
    clock = FixedClock(parse_instant("2026-08-15T03:00:05Z"))
    set_clock(clock)
    try:
        paused = store.upsert(
            replace(
                seeded,
                enabled=False,
                next_run_at=slot,
                last_run_at=parse_instant("2026-08-14T03:00:00Z"),
                commitment_timezone="UTC",
            )
        )
        paused_result = fire_scheduled_entity_embed(paused.id, due_at=slot)
        assert paused_result["status"] == "cancelled"
        cancelled = get_job_store().get(str(paused_result["job_id"]))
        assert cancelled is not None and cancelled.status == "cancelled"
        assert get_catalog_index_store().get().ready is False
        view = EntityEmbedJobs().index_view()
        assert view.ready is False

        # A paused row does not sweep. Run-now still does, without enabling the cadence.
        job = run_entity_embed_schedule_now(actor_user_id="usr_ops", actor_token_id=None)
        assert job.kind == "entity_embed"
        finished = get_job_store().get(job.id)
        assert finished is not None and finished.status == "succeeded"
        ready = EntityEmbedJobs().index_view()
        assert ready.ready is True
        assert ready.generation == 1
        assert ready.written == 0
        assert ready.failed == 0
        assert ready.attempted == 0
        assert ready.rebuild_owed is False
        assert get_catalog_index_store().get().ready is False
    finally:
        reset_clock()


def test_initial_partial_failure_does_not_become_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model()
    good = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    bad = _serving(monkeypatch, table_name="broken_item", name="Broken")

    def _embed(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        generation = int(kwargs["expected_generation"])
        if "Broken" in texts[0]:
            raise RuntimeError("embed failed")
        return _vectors(generation)

    monkeypatch.setattr("backend.entity.projection.embed_texts", _embed)
    out = run_entity_embed_job(_queue_embed())
    assert out["status"] == "failed"
    view = EntityEmbedJobs().index_view()
    assert view.ready is False
    assert view.rebuild_owed is True
    assert view.written == 1
    assert view.failed == 1
    assert view.attempted == 2
    assert view.failure_summary == "1 current target failed"
    assert current_projection(good) is not None
    assert current_projection(good).embedding == (1.0, 0.0)
    assert current_projection(bad) is None
    assert get_catalog_index_store().get().ready is False


def test_full_sweep_with_zero_failures_becomes_ready_then_keeps_ready_on_one_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model()
    good = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    other = _serving(monkeypatch, table_name="beta_item", name="Beta")
    text = {
        good: definition_text(
            table_name="alpha_item",
            name="Alpha",
            description="A stock item",
            tag_names=(),
        ),
        other: definition_text(
            table_name="beta_item",
            name="Beta",
            description="A stock item",
            tag_names=(),
        ),
    }

    def _ok(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        assert texts[0] in text.values()
        return _vectors(int(kwargs["expected_generation"]))

    monkeypatch.setattr("backend.entity.projection.embed_texts", _ok)
    assert run_entity_embed_job(_queue_embed())["status"] == "succeeded"
    ready = EntityEmbedJobs().index_view()
    assert ready.ready is True
    assert ready.generation == 1
    assert ready.written == 2
    assert ready.failed == 0
    assert ready.attempted == 2
    assert ready.failure_summary is None
    assert ready.rebuild_owed is False

    def _one_fails(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        if texts[0] == text[other]:
            raise RuntimeError("embed failed")
        return _vectors(int(kwargs["expected_generation"]))

    monkeypatch.setattr("backend.entity.projection.embed_texts", _one_fails)
    assert run_entity_embed_job(_queue_embed())["status"] == "succeeded"
    gap = EntityEmbedJobs().index_view()
    assert gap.ready is True
    assert gap.generation == 1
    assert gap.written == 1
    assert gap.failed == 1
    assert gap.attempted == 2
    assert gap.failure_summary == "1 current target failed"
    assert current_projection(good) is not None
    assert current_projection(good).embedding == (1.0, 0.0)
    assert current_projection(other) is None


def test_stale_generation_and_control_revision_cannot_write_or_mark_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model(generation=1, control_revision=4)
    entity_id = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    kept = retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(0.25, 0.75),
        control_revision=4,
    )
    assert kept is not None

    def _bump_generation(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        assert kwargs["expected_generation"] == 1
        state = get_model_service_store().get_purpose("embedding")
        get_model_service_store().save_purpose(replace(state, generation=2))
        raise ModelServiceGenerationMismatch()

    monkeypatch.setattr("backend.entity.projection.embed_texts", _bump_generation)
    out = run_entity_embed_job(_queue_embed())
    assert out["status"] == "succeeded"
    assert out["outcome"] == "skipped"
    assert out["reason"] == "generation_changed"
    view = EntityEmbedJobs().index_view()
    assert view.ready is False
    current = current_projection(entity_id)
    assert current is not None and current.generation == 1
    assert current.embedding == (0.25, 0.75)

    _seed_model(generation=1, control_revision=4)
    refused = retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(1.0, 0.0),
        control_revision=3,
    )
    assert refused is None
    assert current_projection(entity_id).embedding == (0.25, 0.75)

    def _bump_revision(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        assert kwargs["expected_control_revision"] == 4
        state = get_model_service_store().get_purpose("embedding")
        get_model_service_store().save_purpose(
            replace(state, control_revision=5)
        )
        raise ModelServiceControlRevisionMismatch()

    monkeypatch.setattr("backend.entity.projection.embed_texts", _bump_revision)
    fenced = run_entity_embed_job(_queue_embed())
    assert fenced["outcome"] == "skipped"
    assert fenced["reason"] == "aborted"
    assert EntityEmbedJobs().index_view().ready is False
    assert current_projection(entity_id).embedding == (0.25, 0.75)


def test_authoring_enqueues_a_sweep_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model()
    entity_id = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    head = _head(entity_id)
    retain_projection(
        entity_id=entity_id,
        head_version_id=head,
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(1.0, 0.0),
        control_revision=1,
    )
    dispatched: list[str] = []

    def _record(job: object) -> str:
        dispatched.append(str(getattr(job, "id")))
        return dispatched[-1]

    monkeypatch.setattr("backend.entity.embed_jobs.schedule.dispatch_entity_job", _record)
    monkeypatch.setattr(
        "backend.entity.projection.embed_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    open_version(
        entity_id=entity_id,
        attributes=None,
        actor_user_id=None,
        actor_token_id=None,
    )
    saved = patch_entity(
        entity_id=entity_id,
        name="Renamed",
        description=None,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert saved["name"] == "Renamed"
    assert current_projection(entity_id) is None
    assert dispatched
    queued = get_job_store().get(dispatched[-1])
    assert queued is not None
    assert queued.kind == "entity_embed"
    assert queued.status == "queued"


def test_deprecation_drops_the_row_and_still_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model()
    entity_id = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(1.0, 0.0),
        control_revision=1,
    )
    dispatched: list[str] = []
    monkeypatch.setattr(
        "backend.entity.embed_jobs.schedule.dispatch_entity_job",
        lambda job: dispatched.append(str(job.id)) or job.id,
    )
    monkeypatch.setattr(
        "backend.entity.projection.embed_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    deprecate_entity(entity_id=entity_id, actor_user_id=None, actor_token_id=None)
    assert current_projection(entity_id) is None
    assert dispatched


def test_failed_enqueue_leaves_owed_sweep_for_the_next_enabled_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services.service import force_generation
    from backend.core.time import FixedClock, parse_instant, reset_clock, set_clock

    _seed_model(generation=1, control_revision=1)
    monkeypatch.setattr(
        "backend.admin.model_services.service.probe_embeddings",
        lambda **kwargs: (8, kwargs["model"]),
    )
    monkeypatch.setattr(
        "backend.metadata.catalog_embed_jobs.schedule.dispatch_queued_job",
        lambda job: job.id,
    )

    def _boom(job: object) -> str:
        raise RuntimeError("queue delivery failed")

    monkeypatch.setattr("backend.entity.embed_jobs.schedule.dispatch_entity_job", _boom)
    with pytest.raises(RuntimeError, match="queue delivery failed"):
        force_generation(
            purpose="embedding",
            actor_user_id="usr_ops",
            actor_token_id=None,
        )
    owed = EntityEmbedJobs().index_view()
    assert owed.ready is False
    assert owed.rebuild_owed is True
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.generation == 2
    assert get_catalog_index_store().get().rebuild_owed is True

    monkeypatch.setattr("backend.worker.due.current_schedule_timezone", lambda: "UTC")
    monkeypatch.setattr(
        "backend.entity.embed_jobs.schedule.dispatch_entity_job",
        lambda job: job.id,
    )
    # Dispatch is a no-op so the due tick's queued job is run explicitly below.
    slot = parse_instant("2026-08-15T03:00:00Z")
    clock = FixedClock(parse_instant("2026-08-15T03:00:05Z"))
    set_clock(clock)
    try:
        record = ensure_entity_embed_schedule()
        get_schedule_store().upsert(
            replace(
                record,
                enabled=True,
                cron="0 3 * * *",
                next_run_at=slot,
                last_run_at=parse_instant("2026-08-14T03:00:00Z"),
                commitment_timezone="UTC",
            )
        )
        minted = fire_scheduled_entity_embed(record.id, due_at=slot)
        assert minted["status"] == "queued"
    finally:
        reset_clock()
    monkeypatch.setattr(
        "backend.entity.projection.embed_texts",
        lambda texts, **kwargs: _vectors(int(kwargs["expected_generation"])),
    )
    assert run_entity_embed_job(str(minted["job_id"]))["status"] == "succeeded"
    settled = EntityEmbedJobs().index_view()
    assert settled.ready is True
    assert settled.generation == 2
    assert settled.rebuild_owed is False
    assert get_catalog_index_store().get().ready is False


def test_same_generation_sweeps_coalesce_without_gating_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_model()
    monkeypatch.setattr(
        "backend.entity.projection.embed_texts",
        lambda texts, **kwargs: _vectors(int(kwargs["expected_generation"])),
    )
    held = try_acquire_entity_embed_lock()
    assert held is not None
    try:
        skipped = run_entity_embed_job(_queue_embed())
    finally:
        held.release()
    assert skipped["status"] == "succeeded"
    assert skipped["outcome"] == "skipped"
    assert skipped["reason"] == "already_active"
    assert EntityEmbedJobs().index_view().ready is False

    catalog_lock = try_acquire_named_execution_lock("catalog_embed")
    assert catalog_lock is not None
    try:
        done = run_entity_embed_job(_queue_embed())
    finally:
        catalog_lock.release()
    assert done["status"] == "succeeded"
    assert EntityEmbedJobs().index_view().ready is True
    assert get_catalog_index_store().get().ready is False


def test_close_stops_new_calls_and_reopen_keeps_the_current_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services.service import close_purpose, open_purpose

    _seed_model(control_revision=2)
    monkeypatch.setattr(
        "backend.admin.model_services.service.probe_embeddings",
        lambda **kwargs: (8, kwargs["model"]),
    )
    entity_id = _serving(monkeypatch, table_name="alpha_item", name="Alpha")
    retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(0.25, 0.75),
        control_revision=2,
    )
    # Mark the index ready the way a finished sweep would, without another model call.
    from backend.entity.embed_jobs.index_state import publish_entity_index

    assert publish_entity_index(
        generation=1,
        control_revision=2,
        written=1,
        failed=0,
        attempted=1,
        progress="indexed 1 entities",
        failure_summary=None,
    )
    calls = {"n": 0}

    def _count(texts: list[str], **kwargs: object) -> EmbeddingVectors:
        calls["n"] += 1
        return _vectors(int(kwargs["expected_generation"]))

    monkeypatch.setattr("backend.entity.projection.embed_texts", _count)
    close_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)
    closed = run_entity_embed_job(_queue_embed())
    assert closed["outcome"] == "skipped"
    assert closed["reason"] == "closed"
    assert calls["n"] == 0
    assert current_projection(entity_id).embedding == (0.25, 0.75)
    assert EntityEmbedJobs().index_view().ready is True

    open_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)
    kept = current_projection(entity_id)
    assert kept is not None
    assert kept.generation == 1
    assert kept.embedding == (0.25, 0.75)
    assert kept.processing_contract == CURRENT_PROCESSING_CONTRACT


def test_cleanup_clears_entity_vectors_and_ready_without_a_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services.service import cleanup_purpose, close_purpose
    from backend.entity.embed_jobs.index_state import publish_entity_index

    _seed_model()
    entity_id = _serving(monkeypatch, table_name="cleanup_item", name="Cleanup")
    retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_hash(entity_id),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(0.4, 0.6),
        control_revision=1,
    )
    assert publish_entity_index(
        generation=1,
        control_revision=1,
        written=1,
        failed=0,
        attempted=1,
        progress="indexed 1 entities",
        failure_summary=None,
    )
    close_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)
    from backend.jobs.store import mark_cancelled

    queued, _ = get_job_store().list(kind=KIND_EMBED, status="queued")
    for record in queued:
        mark_cancelled(record.id)
    before = get_job_store().list(kind=KIND_EMBED)[1]
    cleanup_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)
    assert current_projection(entity_id) is None
    cleared = EntityEmbedJobs().index_view()
    assert cleared.ready is False
    assert cleared.rebuild_owed is False
    assert get_model_service_store().get(_SERVICE_ID) is not None
    assert get_job_store().list(kind=KIND_EMBED)[1] == before
    assert get_catalog_index_store().get().ready is False


def test_cleanup_is_busy_while_an_entity_embed_job_is_queued() -> None:
    from backend.admin.model_services.errors import ModelServiceCleanupBusy
    from backend.admin.model_services.service import cleanup_purpose, close_purpose

    _seed_model()
    close_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)
    create_queued_job(kind=KIND_EMBED, input={}, summary="entity_embed")
    with pytest.raises(ModelServiceCleanupBusy):
        cleanup_purpose(purpose="embedding", actor_user_id="usr_ops", actor_token_id=None)


def test_purpose_read_model_includes_the_entity_index() -> None:
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.session_store import MemorySessionStore, get_session_store
    from backend.admin.user_store import get_user_store

    _seed_model()
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=admin.id,
        status="active",
    )
    sessions = MemorySessionStore()
    app.dependency_overrides[get_user_store] = lambda: get_user_store()
    app.dependency_overrides[get_role_store] = lambda: roles
    app.dependency_overrides[get_session_store] = lambda: sessions
    try:
        with TestClient(app) as client:
            assert client.post(
                "/auth/login", json={"account": "root", "password": "s3cret"}
            ).status_code == 200
            body = client.get("/model-services/purpose/embedding").json()
    finally:
        app.dependency_overrides.clear()
    entity_index = body["entity_index"]
    assert entity_index["ready"] is False
    assert entity_index["generation"] is None
    assert entity_index["coverage"] == {
        "written": 0,
        "failed": 0,
        "attempted": 0,
    }
    assert entity_index["failure_summary"] is None
    assert entity_index["schedule"]["cron"] == "0 3 * * *"
    assert entity_index["schedule"]["enabled"] is True
    assert entity_index["rebuild_owed"] is False
    assert body["catalog_index"]["ready"] is False
    assert "entity_index" != "catalog_index"


def _head(entity_id: str) -> str:
    from backend.entity.lifecycle import latest_published_of

    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return head.id


def _hash(entity_id: str) -> str:
    from backend.entity.projection import canonical_text
    from hashlib import sha256

    return sha256(canonical_text(entity_id).encode("utf-8")).hexdigest()

