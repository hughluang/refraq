"""Cross-consumer embedding acceptance: one shared call, two indexes.

Single-consumer cases that already exist are not repeated here:
batch splitting of the shared call, purpose generation on secret/timeout/batch
edits, and each domain's own stale-fence and cleanup tests.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace

import pytest

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.model_services import (  # noqa: E402
    bind_catalog_embed_jobs,
    bind_entity_embed_jobs,
    get_embedding_runtime,
)
from backend.admin.model_services.records import (  # noqa: E402
    CURRENT_PROCESSING_CONTRACT,
    ModelServiceRecord,
    PurposeState,
)
from backend.admin.model_services.service import (  # noqa: E402
    activate_service,
    cleanup_purpose,
    close_purpose,
    create_service,
    force_generation,
    open_purpose,
    patch_service,
)
from backend.admin.model_services.store import get_model_service_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.embed_jobs import EntityEmbedJobs  # noqa: E402
from backend.entity.embed_jobs.index_state import (  # noqa: E402
    publish_entity_index,
    reset_entity_index_store,
)
from backend.entity.embed_jobs.runner import run_entity_embed_job  # noqa: E402
from backend.entity.kinds import KIND_EMBED  # noqa: E402
from backend.entity.locks import try_acquire_entity_embed_lock  # noqa: E402
from backend.entity.projection import current_projection, retain_projection  # noqa: E402
from backend.entity.records import AttributeRecord  # noqa: E402
from backend.jobs.store import (  # noqa: E402
    create_queued_job,
    get_job_store,
    mark_cancelled,
)
from backend.metadata.catalog.embedding import (  # noqa: E402
    CatalogEmbeddingRecord,
    embedding_configured,
    set_embed_fn_for_tests,
)
from backend.metadata.catalog.index_embeddings import EmbeddingRefreshCounts  # noqa: E402
from backend.metadata.catalog.index_state import (  # noqa: E402
    get_catalog_index_store,
    publish_catalog_readiness,
)
from backend.metadata.catalog.store import get_catalog_store  # noqa: E402
from backend.metadata.catalog_embed_jobs import (  # noqa: E402
    CatalogEmbedJobs,
    run_catalog_embed_job,
)

_SKU = AttributeRecord(name="sku", type="string", max_length=32, required=True, unique=True)
_ACTOR = "usr_cross"


@pytest.fixture(autouse=True)
def _ports() -> None:
    from backend.worker.parameters import assemble_system_parameters

    reset_entity_index_store()
    assemble_system_parameters()
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    bind_entity_embed_jobs(EntityEmbedJobs())
    set_embed_fn_for_tests(None)
    yield
    set_embed_fn_for_tests(None)
    bind_catalog_embed_jobs(CatalogEmbedJobs())
    bind_entity_embed_jobs(EntityEmbedJobs())


def _probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.admin.model_services.service.probe_embeddings",
        lambda **kwargs: (8, kwargs["model"]),
    )


def _create(*, name: str = "Office embed", model: str = "qwen-test") -> str:
    record = create_service(
        purpose="embedding",
        protocol="openai_compat",
        display_name=name,
        url="http://embed.test/v1/embeddings",
        model=model,
        timeout_sec=30,
        batch_limit=32,
        api_key="sk-test",
        actor_user_id=_ACTOR,
        actor_token_id=None,
    )
    return record.id


def _publish_both() -> None:
    runtime = get_embedding_runtime()
    assert runtime is not None
    assert publish_catalog_readiness(
        service_id=runtime.service_id,
        generation=runtime.generation,
        control_revision=runtime.control_revision,
        counts=EmbeddingRefreshCounts(),
    )
    assert publish_entity_index(
        generation=runtime.generation,
        control_revision=runtime.control_revision,
        written=1,
        failed=0,
        attempted=1,
        progress="indexed 1 entities",
        failure_summary=None,
    )


def _assert_both_unready_and_owed() -> None:
    catalog = get_catalog_index_store().get()
    entity = EntityEmbedJobs().index_view()
    assert catalog.ready is False
    assert catalog.rebuild_owed is True
    assert entity.ready is False
    assert entity.rebuild_owed is True


def _serving(monkeypatch: pytest.MonkeyPatch) -> str:
    from backend.entity.align import run_entity_table_job
    from backend.entity.lifecycle import latest_published_of
    from backend.entity.publish import accept
    from backend.entity.service import create_entity
    from backend.entity.store import get_entity_store
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.user_store import get_user_store
    from backend.worker.parameters import assemble_system_parameters

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account=f"cross_{uuid.uuid4().hex[:8]}",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    assemble_system_parameters()
    def _inline(job: object) -> str:
        run_entity_table_job(getattr(job, "id"))
        return str(getattr(job, "id"))

    monkeypatch.setattr("backend.entity.jobs.dispatch_entity_job", _inline)
    monkeypatch.setattr(
        "backend.entity.embed_jobs.schedule.dispatch_entity_job",
        lambda job: job.id,
    )
    saved = create_entity(
        table_name=f"cross_item_{uuid.uuid4().hex[:8]}",
        name="Cross item",
        description="A stock item",
        attributes=[_SKU],
        actor_user_id=None,
        actor_token_id=None,
    )
    entity_id = str(saved["id"])
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    job, created = accept(
        entity_id=entity_id,
        version_id=current.id,
        actor_user_id=_ACTOR,
        actor_token_id=None,
    )
    assert created
    finished = get_job_store().get(job.id)
    assert finished is not None and finished.status == "succeeded"
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return entity_id


def _entity_hash(entity_id: str) -> str:
    from hashlib import sha256

    from backend.entity.projection import canonical_text

    return sha256(canonical_text(entity_id).encode("utf-8")).hexdigest()


def _head(entity_id: str) -> str:
    from backend.entity.lifecycle import latest_published_of
    from backend.entity.store import get_entity_store

    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return head.id


def _keep_vectors(entity_id: str, generation: int) -> None:
    get_catalog_store().upsert_embedding(
        CatalogEmbeddingRecord(
            id="emb_cross",
            kind="object",
            target_id="obj_cross",
            locator_key="obj/postgresql/embed-src/public/table/cross",
            content_hash="abc",
            embedding=[0.4, 0.6],
            indexed_at=utc_now(),
            generation=generation,
        )
    )
    assert retain_projection(
        entity_id=entity_id,
        head_version_id=_head(entity_id),
        content_hash=_entity_hash(entity_id),
        generation=generation,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=(0.4, 0.6),
        control_revision=get_embedding_runtime().control_revision,  # type: ignore[union-attr]
    )


def _cancel_embed_jobs() -> None:
    for kind in ("catalog_embed", KIND_EMBED):
        queued, _total = get_job_store().list(kind=kind)
        for record in queued:
            if record.status not in {"succeeded", "failed", "cancelled"}:
                mark_cancelled(record.id)


def test_batch_limit_below_32_splits_catalog_and_entity_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services import openai_compat
    from backend.entity.projection import embed_texts as entity_embed_texts
    from backend.metadata.catalog.embedding import embed_texts as catalog_embed_texts

    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id="msvc_cross",
            purpose="embedding",
            protocol="openai_compat",
            display_name="cross",
            url="http://embed.test/v1/embeddings",
            model="qwen-test",
            timeout_sec=30,
            batch_limit=2,
            secret=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id="msvc_cross",
            closed=False,
            ready=False,
            generation=1,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        )
    )
    seen: list[list[str]] = []

    def _urlopen(req: object, timeout: int = 0) -> object:
        payload = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        chunk = list(payload["input"])
        seen.append(chunk)

        class _Body:
            def __enter__(self) -> "_Body":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                rows = [
                    {"index": index, "embedding": [float(index), 1.0]}
                    for index in range(len(chunk))
                ]
                return json.dumps({"data": rows}).encode("utf-8")

        return _Body()

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    texts = ["one", "two", "three", "four", "five"]
    catalog_vectors = catalog_embed_texts(texts, expected_generation=1)
    assert [len(chunk) for chunk in seen] == [2, 2, 1]
    assert len(catalog_vectors) == 5
    seen.clear()
    entity_result = entity_embed_texts(texts, expected_generation=1)
    assert [len(chunk) for chunk in seen] == [2, 2, 1]
    assert len(entity_result.vectors) == 5
    assert entity_result.space.processing_contract == CURRENT_PROCESSING_CONTRACT


def test_secret_timeout_and_batch_limit_keep_both_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe(monkeypatch)
    service_id = _create()
    activate_service(service_id=service_id, actor_user_id=_ACTOR, actor_token_id=None)
    _publish_both()
    before = get_embedding_runtime()
    assert before is not None
    for body in (
        {"api_key": "sk-rotated"},
        {"timeout_sec": 90},
        {"batch_limit": 4},
    ):
        patch_service(
            service_id=service_id,
            display_name=None,
            url=None,
            model=None,
            protocol=None,
            timeout_sec=body.get("timeout_sec"),  # type: ignore[arg-type]
            batch_limit=body.get("batch_limit"),  # type: ignore[arg-type]
            api_key=body.get("api_key"),  # type: ignore[arg-type]
            clear_api_key=False,
            actor_user_id=_ACTOR,
            actor_token_id=None,
        )
    after = get_embedding_runtime()
    assert after is not None
    assert after.generation == before.generation
    assert after.control_revision == before.control_revision
    assert after.batch_limit == 4
    assert get_catalog_index_store().get().ready is True
    assert EntityEmbedJobs().index_view().ready is True


def test_url_model_switch_and_force_generation_clear_both_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe(monkeypatch)
    # Record the two schedule requests. An eager worker would finish the empty
    # Catalog sweep and publish ready again before this test can see the clear.
    triggered = {"catalog": 0, "entity": 0}

    def _catalog_trigger(self: object, **kwargs: object) -> str:
        triggered["catalog"] += 1
        return "job_catalog"

    def _entity_trigger(self: object, **kwargs: object) -> str:
        triggered["entity"] += 1
        return "job_entity"

    monkeypatch.setattr(
        "backend.metadata.catalog_embed_jobs.jobs.CatalogEmbedJobs.trigger_run",
        _catalog_trigger,
    )
    monkeypatch.setattr(
        "backend.entity.embed_jobs.jobs.EntityEmbedJobs.trigger_run",
        _entity_trigger,
    )
    service_id = _create()
    other_id = _create(name="Other embed", model="other-model")
    activate_service(service_id=service_id, actor_user_id=_ACTOR, actor_token_id=None)
    assert get_embedding_runtime().generation == 1  # type: ignore[union-attr]
    _publish_both()
    asked = dict(triggered)

    patch_service(
        service_id=service_id,
        display_name=None,
        url="http://embed.other/v1/embeddings",
        model=None,
        protocol=None,
        timeout_sec=None,
        batch_limit=None,
        api_key="sk-next",
        clear_api_key=False,
        actor_user_id=_ACTOR,
        actor_token_id=None,
    )
    assert get_embedding_runtime().generation == 2  # type: ignore[union-attr]
    _assert_both_unready_and_owed()
    assert triggered["catalog"] == asked["catalog"] + 1
    assert triggered["entity"] == asked["entity"] + 1
    _publish_both()

    patch_service(
        service_id=service_id,
        display_name=None,
        url=None,
        model="replaced-model",
        protocol=None,
        timeout_sec=None,
        batch_limit=None,
        api_key=None,
        clear_api_key=False,
        actor_user_id=_ACTOR,
        actor_token_id=None,
    )
    assert get_embedding_runtime().generation == 3  # type: ignore[union-attr]
    _assert_both_unready_and_owed()
    _publish_both()

    activate_service(service_id=other_id, actor_user_id=_ACTOR, actor_token_id=None)
    assert get_embedding_runtime().generation == 4  # type: ignore[union-attr]
    assert get_embedding_runtime().service_id == other_id  # type: ignore[union-attr]
    _assert_both_unready_and_owed()
    _publish_both()

    entity_id = _serving(monkeypatch)
    generation = get_embedding_runtime().generation  # type: ignore[union-attr]
    _keep_vectors(entity_id, generation)
    force_generation(purpose="embedding", actor_user_id=_ACTOR, actor_token_id=None)
    assert get_embedding_runtime().generation == generation + 1  # type: ignore[union-attr]
    _assert_both_unready_and_owed()
    stored = get_catalog_store().get_embedding(kind="object", target_id="obj_cross")
    assert stored is not None and stored.embedding == [0.4, 0.6]
    kept = current_projection(entity_id)
    assert kept is not None and kept.generation == generation


def test_close_keeps_both_vectors_and_reopen_can_use_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe(monkeypatch)
    service_id = _create()
    activate_service(service_id=service_id, actor_user_id=_ACTOR, actor_token_id=None)
    _publish_both()
    entity_id = _serving(monkeypatch)
    generation = get_embedding_runtime().generation  # type: ignore[union-attr]
    _keep_vectors(entity_id, generation)
    close_purpose(purpose="embedding", actor_user_id=_ACTOR, actor_token_id=None)
    closed = get_embedding_runtime()
    assert closed is not None
    assert closed.closed is True
    assert closed.generation == generation
    assert embedding_configured() is False
    assert get_catalog_index_store().get().ready is True
    assert EntityEmbedJobs().index_view().ready is True
    assert get_catalog_store().get_embedding(kind="object", target_id="obj_cross") is not None
    assert current_projection(entity_id) is not None
    assert current_projection(entity_id).generation == generation  # type: ignore[union-attr]

    open_purpose(purpose="embedding", actor_user_id=_ACTOR, actor_token_id=None)
    opened = get_embedding_runtime()
    assert opened is not None
    assert opened.closed is False
    assert opened.generation == generation
    assert embedding_configured() is True
    entity_index = EntityEmbedJobs().index_view()
    assert entity_index.ready is True
    assert entity_index.generation == generation
    assert current_projection(entity_id).embedding == (0.4, 0.6)  # type: ignore[union-attr]


def test_cleanup_clears_both_indexes_and_does_not_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _probe(monkeypatch)
    service_id = _create()
    activate_service(service_id=service_id, actor_user_id=_ACTOR, actor_token_id=None)
    _publish_both()
    entity_id = _serving(monkeypatch)
    generation = get_embedding_runtime().generation  # type: ignore[union-attr]
    _keep_vectors(entity_id, generation)
    close_purpose(purpose="embedding", actor_user_id=_ACTOR, actor_token_id=None)
    _cancel_embed_jobs()
    before = (
        get_job_store().list(kind="catalog_embed")[1]
        + get_job_store().list(kind=KIND_EMBED)[1]
    )
    cleanup_purpose(purpose="embedding", actor_user_id=_ACTOR, actor_token_id=None)
    catalog = get_catalog_index_store().get()
    entity = EntityEmbedJobs().index_view()
    assert catalog.ready is False and catalog.rebuild_owed is False
    assert entity.ready is False and entity.rebuild_owed is False
    assert get_catalog_store().get_embedding(kind="object", target_id="obj_cross") is None
    assert current_projection(entity_id) is None
    after = (
        get_job_store().list(kind="catalog_embed")[1]
        + get_job_store().list(kind=KIND_EMBED)[1]
    )
    assert after == before
    assert get_embedding_runtime().generation == generation  # type: ignore[union-attr]


def test_catalog_and_entity_rebuilds_do_not_wait_for_each_other() -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id="msvc_cross",
            purpose="embedding",
            protocol="openai_compat",
            display_name="cross",
            url="http://embed.test/v1/embeddings",
            model="qwen-test",
            timeout_sec=30,
            secret=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id="msvc_cross",
            closed=False,
            ready=False,
            generation=1,
            control_revision=1,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        )
    )
    held = try_acquire_entity_embed_lock()
    assert held is not None
    try:
        catalog_job = create_queued_job(kind="catalog_embed", input={})
        assert run_catalog_embed_job(catalog_job.id)["status"] == "succeeded"
        assert get_catalog_index_store().get().ready is True
        assert EntityEmbedJobs().index_view().ready is False
    finally:
        held.release()

    entity_job = create_queued_job(kind=KIND_EMBED, input={}, summary="entity_embed")
    assert run_entity_embed_job(entity_job.id)["status"] == "succeeded"
    assert EntityEmbedJobs().index_view().ready is True
    assert get_catalog_index_store().get().ready is True


@pytest.mark.parametrize(
    "service_id,generation,revision",
    [("stale_service", 1, 4), ("msvc_cross", 0, 4), ("msvc_cross", 1, 3)],
)
def test_stale_fence_cannot_publish_either_ready_bit(
    service_id: str, generation: int, revision: int,
) -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id="msvc_cross",
            purpose="embedding",
            protocol="openai_compat",
            display_name="cross",
            url="http://embed.test/v1/embeddings",
            model="qwen-test",
            timeout_sec=30,
            secret=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id="msvc_cross",
            closed=False,
            ready=False,
            generation=1,
            control_revision=4,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        )
    )
    assert publish_catalog_readiness(
        service_id=service_id,
        generation=generation,
        control_revision=revision,
        counts=EmbeddingRefreshCounts(),
    ) is False
    assert (
        publish_entity_index(
            generation=0,
            control_revision=4,
            written=1,
            failed=0,
            attempted=1,
        )
        is False
    )
    assert (
        publish_catalog_readiness(
            counts=EmbeddingRefreshCounts(),
            service_id="msvc_cross",
            generation=1,
            control_revision=3,
        )
        is False
    )
    assert (
        publish_entity_index(
            generation=1,
            control_revision=3,
            written=1,
            failed=0,
            attempted=1,
        )
        is False
    )
    assert get_catalog_index_store().get().ready is False
    assert EntityEmbedJobs().index_view().ready is False

    assert publish_catalog_readiness(
        counts=EmbeddingRefreshCounts(),
        service_id="msvc_cross",
        generation=1,
        control_revision=4,
    )
    assert get_catalog_index_store().get().ready is True
    assert EntityEmbedJobs().index_view().ready is False
    state = store.get_purpose("embedding")
    store.save_purpose(replace(state, ready=False))
    assert publish_entity_index(
        generation=1,
        control_revision=4,
        written=1,
        failed=0,
        attempted=1,
    )
    assert store.get_purpose("embedding").ready is False
    state = store.get_purpose("embedding")
    store.save_purpose(replace(state, control_revision=5))
    from backend.metadata.catalog.index_state import clear_catalog_index_ready
    from backend.entity.embed_jobs.index_state import clear_entity_index_ready

    clear_catalog_index_ready(rebuild_owed=False)
    clear_entity_index_ready(rebuild_owed=False)
    assert (
        publish_catalog_readiness(
            counts=EmbeddingRefreshCounts(),
            service_id="msvc_cross",
            generation=1,
            control_revision=4,
        )
        is False
    )
    assert (
        publish_entity_index(
            generation=1,
            control_revision=4,
            written=1,
            failed=0,
            attempted=1,
        )
        is False
    )
    assert get_catalog_index_store().get().ready is False
    assert EntityEmbedJobs().index_view().ready is False
