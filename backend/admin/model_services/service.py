"""Model Service use cases."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

from backend.admin.audit import persist_audit_event
from backend.admin.model_services.errors import (
    ModelServiceCleanupBusy,
    ModelServiceCleanupForbidden,
    ModelServiceInvalidConfig,
    ModelServiceNotFound,
    ModelServiceNotInUse,
    ModelServiceProtocolUnsupported,
    ModelServicePurposeUnsupported,
    ModelServiceSecretRequired,
    ModelServiceWireImmutable,
)
from backend.admin.model_services.openai_compat import (
    EMBEDDING_OUTPUT_DIM,
    TIMEOUT_SEC_MAX,
    TIMEOUT_SEC_MIN,
    probe_embeddings,
)
from backend.admin.model_services.ports import catalog_embed_jobs, entity_embed_jobs
from backend.admin.model_services.records import (
    CURRENT_PROCESSING_CONTRACT,
    SUPPORTED_PROTOCOLS,
    SUPPORTED_PURPOSES,
    EmbeddingRuntime,
    ModelServiceRecord,
    PurposeState,
)
from backend.admin.model_services.store import ModelServiceStore, get_model_service_store
from backend.core.time import utc_now


def _require_purpose(purpose: str) -> str:
    if purpose not in SUPPORTED_PURPOSES:
        raise ModelServicePurposeUnsupported()
    return purpose


def _require_protocol(protocol: str) -> str:
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ModelServiceProtocolUnsupported()
    return protocol


def _clean_name(value: str) -> str:
    text = value.strip()
    if not text:
        raise ModelServiceInvalidConfig("Display name is required")
    return text


def _clean_url(value: str) -> str:
    text = value.strip()
    if not text.startswith("http://") and not text.startswith("https://"):
        raise ModelServiceInvalidConfig("URL must be an http(s) embeddings endpoint")
    if text.rstrip("/").endswith("/v1"):
        raise ModelServiceInvalidConfig("Use the full embeddings URL, not a /v1 base")
    return text


def _clean_model(value: str) -> str:
    text = value.strip()
    if not text:
        raise ModelServiceInvalidConfig("Model is required")
    return text


def _clean_timeout(value: int) -> int:
    if value < TIMEOUT_SEC_MIN or value > TIMEOUT_SEC_MAX:
        raise ModelServiceInvalidConfig(
            "timeout_sec must be an integer from 15 to 300"
        )
    return value


_BATCH_LIMIT_MIN = 1
_BATCH_LIMIT_MAX = 32


def _clean_batch_limit(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < _BATCH_LIMIT_MIN
        or value > _BATCH_LIMIT_MAX
    ):
        raise ModelServiceInvalidConfig(
            "batch_limit must be an integer from 1 to 32"
        )
    return value


def _require(store: ModelServiceStore, service_id: str) -> ModelServiceRecord:
    record = store.get(service_id)
    if record is None:
        raise ModelServiceNotFound()
    return record


def _audit(
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    resource_id: str,
    action: str,
    detail: dict[str, object] | None = None,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="model_service",
        resource_id=resource_id,
        action=action,
        result="success",
        detail=detail or {},
    )


def _begin_rebuild(
    store: ModelServiceStore,
    state: PurposeState,
    record: ModelServiceRecord,
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> PurposeState:
    """Advance generation and ask the site schedule to run. Does not manage Jobs."""
    next_state = replace(
        state,
        in_use_id=record.id,
        ready=False,
        generation=state.generation + 1,
        control_revision=state.control_revision + 1,
    )
    store.save_purpose(next_state)
    _owe_consumer_rebuilds()
    _enqueue_consumer_rebuilds(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    return next_state


def _ensure_processing_contract(
    store: ModelServiceStore, state: PurposeState
) -> PurposeState:
    """Advance generation when the stored projection contract is not current.

    Shipping the current contract does not call this path. A mismatch commits
    the new generation before the Catalog enqueue, so a failed enqueue leaves
    the rebuild owed to the existing schedule.
    """
    if state.processing_contract == CURRENT_PROCESSING_CONTRACT:
        return state
    next_state = replace(
        state,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        ready=False,
        generation=state.generation + 1,
        control_revision=state.control_revision + 1,
    )
    store.save_purpose(next_state)
    _owe_consumer_rebuilds()
    _enqueue_consumer_rebuilds(actor_user_id="system", actor_token_id=None)
    return next_state


def _owe_consumer_rebuilds() -> None:
    """Commit both consumers' rebuild intent before either enqueue."""

    catalog_embed_jobs().clear_index_ready(rebuild_owed=True)
    entity_embed_jobs().clear_index_ready(rebuild_owed=True)


def _enqueue_consumer_rebuilds(
    *, actor_user_id: str, actor_token_id: str | None
) -> None:
    """Ask each site schedule to run. Entity goes first so a Catalog broker
    failure still leaves Entity's job queued when Entity's own publish worked.
    Both intents are already committed. If both enqueues fail, the Catalog
    error is raised with the Entity error as its cause.
    """

    try:
        entity_embed_jobs().trigger_run(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    except Exception as entity_error:  # noqa: BLE001 — broker failure must not drop Catalog
        try:
            catalog_embed_jobs().trigger_run(
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
            )
        except Exception as catalog_error:  # noqa: BLE001 — keep the Entity failure visible
            raise catalog_error from entity_error
        raise
    catalog_embed_jobs().trigger_run(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def get_embedding_runtime() -> EmbeddingRuntime | None:
    store = get_model_service_store()
    state = _ensure_processing_contract(store, store.get_purpose("embedding"))
    if not state.in_use_id:
        return None
    record = store.get(state.in_use_id)
    if record is None:
        return None
    return EmbeddingRuntime(
        service_id=record.id,
        url=record.url,
        model=record.model,
        secret=record.secret,
        timeout_sec=record.timeout_sec,
        batch_limit=record.batch_limit,
        closed=state.closed,
        ready=state.ready,
        generation=state.generation,
        control_revision=state.control_revision,
    )


def mark_embedding_ready(
    *,
    purpose: str,
    service_id: str,
    generation: int,
    control_revision: int | None = None,
    objects_written: int = 0,
    columns_written: int = 0,
    objects_failed: int = 0,
    columns_failed: int = 0,
    objects_attempted: int = 0,
    columns_attempted: int = 0,
    progress: str | None = None,
    failure_summary: str | None = None,
) -> bool:
    store = get_model_service_store()
    state = store.get_purpose(purpose)
    if state.in_use_id != service_id or state.generation != generation:
        return False
    if (
        control_revision is not None
        and state.control_revision != control_revision
    ):
        return False
    catalog_embed_jobs().publish_index(
        generation=generation,
        objects_written=objects_written,
        columns_written=columns_written,
        objects_failed=objects_failed,
        columns_failed=columns_failed,
        objects_attempted=objects_attempted,
        columns_attempted=columns_attempted,
        progress=progress,
        failure_summary=failure_summary,
    )
    store.save_purpose(replace(state, ready=True))
    return True


def index_status() -> str:
    jobs = catalog_embed_jobs()
    if jobs.index_view().ready:
        return "ready"
    if jobs.has_active():
        return "indexing"
    if jobs.latest_sweep_status() == "failed":
        return "failed"
    return "none"


def create_service(
    *,
    purpose: str,
    protocol: str,
    display_name: str,
    url: str,
    model: str,
    timeout_sec: int,
    batch_limit: int = 32,
    api_key: str | None,
    actor_user_id: str,
    actor_token_id: str | None,
) -> ModelServiceRecord:
    store = get_model_service_store()
    now = utc_now()
    record = ModelServiceRecord(
        id=f"msvc_{uuid.uuid4().hex[:12]}",
        purpose=_require_purpose(purpose),
        protocol=_require_protocol(protocol),
        display_name=_clean_name(display_name),
        url=_clean_url(url),
        model=_clean_model(model),
        timeout_sec=_clean_timeout(timeout_sec),
        batch_limit=_clean_batch_limit(batch_limit),
        secret=api_key.strip() if api_key else None,
        created_at=now,
        updated_at=now,
    )
    saved = store.save(record)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=saved.id,
        action="create",
        detail={"purpose": saved.purpose},
    )
    return saved


def patch_service(
    *,
    service_id: str,
    display_name: str | None,
    url: str | None,
    model: str | None,
    protocol: str | None,
    timeout_sec: int | None,
    batch_limit: int | None,
    api_key: str | None,
    clear_api_key: bool,
    actor_user_id: str,
    actor_token_id: str | None,
) -> ModelServiceRecord:
    store = get_model_service_store()
    record = _require(store, service_id)
    state = store.get_purpose(record.purpose)
    in_use = state.in_use_id == record.id
    next_url = _clean_url(url) if url is not None else record.url
    next_model = _clean_model(model) if model is not None else record.model
    next_protocol = _require_protocol(protocol) if protocol is not None else record.protocol
    if in_use and next_protocol != record.protocol:
        raise ModelServiceWireImmutable()
    url_changed = next_url != record.url
    if url_changed and api_key is None and not clear_api_key:
        raise ModelServiceSecretRequired()
    if url_changed:
        next_secret = None if clear_api_key else (api_key.strip() if api_key else None)
    elif clear_api_key:
        next_secret = None
    elif api_key is not None:
        next_secret = api_key.strip() or None
    else:
        next_secret = record.secret
    next_name = _clean_name(display_name) if display_name is not None else record.display_name
    next_timeout = (
        _clean_timeout(timeout_sec) if timeout_sec is not None else record.timeout_sec
    )
    next_batch_limit = (
        _clean_batch_limit(batch_limit)
        if batch_limit is not None
        else record.batch_limit
    )
    model_changed = next_model != record.model
    wire_changed = url_changed or next_secret != record.secret or model_changed
    if wire_changed:
        probe_embeddings(
            url=next_url,
            model=next_model,
            api_key=next_secret,
            timeout=next_timeout,
        )
    updated = replace(
        record,
        display_name=next_name,
        url=next_url,
        model=next_model,
        protocol=next_protocol,
        timeout_sec=next_timeout,
        batch_limit=next_batch_limit,
        secret=next_secret,
        updated_at=utc_now(),
    )
    saved = store.save(updated)
    if in_use and (url_changed or model_changed):
        _begin_rebuild(
            store,
            state,
            saved,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=saved.id,
        action="update",
        detail={"url_changed": url_changed},
    )
    return saved


def test_service(*, service_id: str, actor_user_id: str, actor_token_id: str | None) -> dict[str, object]:
    store = get_model_service_store()
    record = _require(store, service_id)
    started = time.perf_counter()
    dimension, model = probe_embeddings(
        url=record.url,
        model=record.model,
        api_key=record.secret,
        timeout=record.timeout_sec,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=record.id,
        action="test",
        detail={
            "dimension": dimension,
            "elapsed_ms": elapsed_ms,
            "timeout_sec": record.timeout_sec,
        },
    )
    return {
        "ok": True,
        "dimension": dimension,
        "elapsed_ms": elapsed_ms,
        "model": model,
        "output_dim": EMBEDDING_OUTPUT_DIM,
        "timeout_sec": record.timeout_sec,
    }


def activate_service(
    *, service_id: str, actor_user_id: str, actor_token_id: str | None
) -> ModelServiceRecord:
    store = get_model_service_store()
    record = _require(store, service_id)
    probe_embeddings(
        url=record.url,
        model=record.model,
        api_key=record.secret,
        timeout=record.timeout_sec,
    )
    state = store.get_purpose(record.purpose)
    _begin_rebuild(
        store,
        state,
        record,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=record.id,
        action="activate",
        detail={"purpose": record.purpose},
    )
    return record


def delete_service(
    *, service_id: str, actor_user_id: str, actor_token_id: str | None
) -> None:
    store = get_model_service_store()
    record = _require(store, service_id)
    state = store.get_purpose(record.purpose)
    was_in_use = state.in_use_id == record.id
    store.delete(service_id)
    if was_in_use:
        store.save_purpose(replace(state, in_use_id=None))
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=record.id,
        action="delete",
        detail={"was_in_use": was_in_use},
    )


def force_generation(
    *, purpose: str, actor_user_id: str, actor_token_id: str | None
) -> PurposeState:
    """Bump generation for an undisclosed provider-side model replacement.

    URL, model, and stored vectors stay. Catalog rebuild intent is the purpose
    commit plus the existing site schedule.
    """
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    if not state.in_use_id:
        raise ModelServiceNotInUse()
    record = _require(store, state.in_use_id)
    updated = _begin_rebuild(
        store,
        state,
        record,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="force_generation",
    )
    return updated


def close_purpose(
    *, purpose: str, actor_user_id: str, actor_token_id: str | None
) -> PurposeState:
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    updated = store.save_purpose(
        replace(
            state,
            closed=True,
            control_revision=state.control_revision + 1,
        )
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="close",
    )
    return updated


def open_purpose(
    *,
    purpose: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> PurposeState:
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    if not state.in_use_id:
        raise ModelServiceNotInUse()
    record = _require(store, state.in_use_id)
    probe_embeddings(
        url=record.url,
        model=record.model,
        api_key=record.secret,
        timeout=record.timeout_sec,
    )
    opened = store.save_purpose(
        replace(
            state,
            closed=False,
            control_revision=state.control_revision + 1,
        )
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="open",
    )
    return opened


def cleanup_purpose(
    *, purpose: str, actor_user_id: str, actor_token_id: str | None
) -> PurposeState:
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    if not state.closed and state.in_use_id:
        raise ModelServiceCleanupForbidden()
    jobs = catalog_embed_jobs()
    entity_jobs = entity_embed_jobs()
    if jobs.has_active() or entity_jobs.has_active():
        raise ModelServiceCleanupBusy()
    jobs.clear_index()
    jobs.clear_index_ready(rebuild_owed=False)
    entity_jobs.clear_index()
    entity_jobs.clear_index_ready(rebuild_owed=False)
    updated = store.save_purpose(
        replace(
            state,
            ready=False,
            control_revision=state.control_revision + 1,
        )
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="cleanup",
    )
    return updated

