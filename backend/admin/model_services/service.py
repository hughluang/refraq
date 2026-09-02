"""Model Service use cases."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

from backend.admin.audit import persist_audit_event
from backend.admin.model_services.errors import (
    ModelServiceCleanupForbidden,
    ModelServiceInvalidConfig,
    ModelServiceNotFound,
    ModelServiceNotInUse,
    ModelServiceProtocolUnsupported,
    ModelServicePurposeUnsupported,
    ModelServiceSecretRequired,
    ModelServiceWireImmutable,
)
from backend.admin.model_services.openai_compat import probe_embeddings
from backend.admin.model_services.ports import catalog_embed_jobs
from backend.admin.model_services.records import (
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
) -> PurposeState:
    next_state = PurposeState(
        purpose=state.purpose,
        in_use_id=record.id,
        closed=state.closed,
        ready=False,
        generation=state.generation + 1,
    )
    store.save_purpose(next_state)
    jobs = catalog_embed_jobs()
    jobs.cancel_active()
    jobs.mint(
        service_id=record.id,
        display_name=record.display_name,
        generation=next_state.generation,
        actor_user_id=actor_user_id,
    )
    return next_state


def get_embedding_runtime() -> EmbeddingRuntime | None:
    store = get_model_service_store()
    state = store.get_purpose("embedding")
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
        closed=state.closed,
        ready=state.ready,
        generation=state.generation,
    )


def mark_embedding_ready(*, purpose: str, service_id: str, generation: int) -> bool:
    store = get_model_service_store()
    state = store.get_purpose(purpose)
    if state.in_use_id != service_id or state.generation != generation:
        return False
    store.save_purpose(
        PurposeState(
            purpose=state.purpose,
            in_use_id=state.in_use_id,
            closed=state.closed,
            ready=True,
            generation=state.generation,
        )
    )
    return True


def index_status(purpose: str) -> str:
    store = get_model_service_store()
    state = store.get_purpose(purpose)
    if state.ready:
        return "ready"
    latest = catalog_embed_jobs().latest_status()
    if latest in {"queued", "running"}:
        return "indexing"
    if latest == "failed":
        return "failed"
    return "none"


def create_service(
    *,
    purpose: str,
    protocol: str,
    display_name: str,
    url: str,
    model: str,
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
    if in_use and (next_model != record.model or next_protocol != record.protocol):
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
    wire_changed = url_changed or next_secret != record.secret
    if wire_changed:
        probe_embeddings(url=next_url, model=next_model, api_key=next_secret)
    updated = replace(
        record,
        display_name=next_name,
        url=next_url,
        model=next_model,
        protocol=next_protocol,
        secret=next_secret,
        updated_at=utc_now(),
    )
    saved = store.save(updated)
    if in_use and url_changed:
        _begin_rebuild(store, state, saved, actor_user_id=actor_user_id)
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
        url=record.url, model=record.model, api_key=record.secret
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=record.id,
        action="test",
        detail={"dimension": dimension},
    )
    return {
        "ok": True,
        "dimension": dimension,
        "elapsed_ms": elapsed_ms,
        "model": model,
    }


def activate_service(
    *, service_id: str, actor_user_id: str, actor_token_id: str | None
) -> ModelServiceRecord:
    store = get_model_service_store()
    record = _require(store, service_id)
    probe_embeddings(url=record.url, model=record.model, api_key=record.secret)
    state = store.get_purpose(record.purpose)
    _begin_rebuild(store, state, record, actor_user_id=actor_user_id)
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
        catalog_embed_jobs().cancel_active()
        store.save_purpose(
            PurposeState(
                purpose=state.purpose,
                in_use_id=None,
                closed=state.closed,
                ready=state.ready,
                generation=state.generation,
            )
        )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=record.id,
        action="delete",
        detail={"was_in_use": was_in_use},
    )


def close_purpose(
    *, purpose: str, actor_user_id: str, actor_token_id: str | None
) -> PurposeState:
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    updated = store.save_purpose(
        PurposeState(
            purpose=state.purpose,
            in_use_id=state.in_use_id,
            closed=True,
            ready=state.ready,
            generation=state.generation,
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
    rebuild: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> PurposeState:
    if rebuild not in {"none", "full"}:
        raise ModelServiceInvalidConfig("rebuild must be none or full")
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    if not state.in_use_id:
        raise ModelServiceNotInUse()
    record = _require(store, state.in_use_id)
    probe_embeddings(url=record.url, model=record.model, api_key=record.secret)
    opened = store.save_purpose(
        PurposeState(
            purpose=state.purpose,
            in_use_id=state.in_use_id,
            closed=False,
            ready=state.ready,
            generation=state.generation,
        )
    )
    if rebuild == "full":
        opened = _begin_rebuild(store, opened, record, actor_user_id=actor_user_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="open",
        detail={"rebuild": rebuild},
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
    jobs.cancel_active()
    jobs.clear_index()
    updated = store.save_purpose(
        PurposeState(
            purpose=state.purpose,
            in_use_id=state.in_use_id,
            closed=state.closed,
            ready=False,
            generation=state.generation,
        )
    )
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="cleanup",
    )
    return updated


def reindex_purpose(
    *, purpose: str, actor_user_id: str, actor_token_id: str | None
) -> PurposeState:
    store = get_model_service_store()
    state = store.get_purpose(_require_purpose(purpose))
    if not state.in_use_id:
        raise ModelServiceNotInUse()
    record = _require(store, state.in_use_id)
    updated = _begin_rebuild(store, state, record, actor_user_id=actor_user_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_id=purpose,
        action="reindex",
    )
    return updated
