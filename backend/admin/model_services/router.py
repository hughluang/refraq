"""Model Service HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.model_services.errors import (
    ModelServiceNotFound,
    ModelServiceProtocolUnsupported,
    ModelServicePurposeUnsupported,
)
from backend.admin.model_services.records import (
    SUPPORTED_PROTOCOLS,
    SUPPORTED_PURPOSES,
    ModelServiceRecord,
    PurposeState,
)
from backend.admin.model_services.schemas import (
    ModelServiceCreateIn,
    ModelServiceList,
    ModelServiceOpenIn,
    ModelServiceOut,
    ModelServicePatchIn,
    ModelServiceSpecOut,
    ModelServiceTestOut,
    PurposeStateOut,
)
from backend.admin.model_services.service import (
    activate_service,
    cleanup_purpose,
    close_purpose,
    create_service,
    delete_service,
    index_status,
    open_purpose,
    patch_service,
    reindex_purpose,
    test_service,
)
from backend.admin.model_services.store import ModelServiceStore, get_model_service_store
from backend.admin.user_store import UserRecord
from backend.core.pagination import PageParams, page_params

router = APIRouter(prefix="/model-services", tags=["model-services"])


def _out(record: ModelServiceRecord, *, in_use_id: str | None) -> ModelServiceOut:
    return ModelServiceOut(
        id=record.id,
        purpose=record.purpose,
        protocol=record.protocol,
        display_name=record.display_name,
        url=record.url,
        model=record.model,
        has_secret=bool(record.secret),
        in_use=in_use_id == record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _purpose_out(state: PurposeState) -> PurposeStateOut:
    return PurposeStateOut(
        purpose=state.purpose,
        closed=state.closed,
        ready=state.ready,
        in_use_id=state.in_use_id,
        generation=state.generation,
        index_status=index_status(state.purpose),  # type: ignore[arg-type]
    )


@router.get("/spec")
def get_spec(
    purpose: str = "embedding",
    protocol: str = "openai_compat",
    _caller: UserRecord = Depends(require_permission("model_services:read")),
) -> ModelServiceSpecOut:
    if purpose not in SUPPORTED_PURPOSES:
        raise ModelServicePurposeUnsupported()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ModelServiceProtocolUnsupported()
    return ModelServiceSpecOut(
        purpose=purpose,
        protocol=protocol,
        spec={
            "fields": [
                {"name": "display_name", "type": "string", "required": True},
                {"name": "url", "type": "string", "required": True},
                {"name": "model", "type": "string", "required": True},
                {"name": "api_key", "type": "secret", "required": False},
            ]
        },
    )


@router.get("/purpose/{purpose}")
def get_purpose_state(
    purpose: str,
    store: ModelServiceStore = Depends(get_model_service_store),
    _caller: UserRecord = Depends(require_permission("model_services:read")),
) -> PurposeStateOut:
    if purpose not in SUPPORTED_PURPOSES:
        raise ModelServicePurposeUnsupported()
    return _purpose_out(store.get_purpose(purpose))


@router.get("")
def list_services(
    purpose: str | None = None,
    params: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    store: ModelServiceStore = Depends(get_model_service_store),
    _caller: UserRecord = Depends(require_permission("model_services:read")),
) -> ModelServiceList:
    items, total = store.list_services(
        purpose=purpose, limit=params.limit, offset=params.offset
    )
    in_use_by_purpose = {
        item.purpose: store.get_purpose(item.purpose).in_use_id for item in items
    }
    return ModelServiceList(
        items=[_out(item, in_use_id=in_use_by_purpose.get(item.purpose)) for item in items],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.post("")
def post_service(
    body: ModelServiceCreateIn,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: ModelServiceStore = Depends(get_model_service_store),
) -> ModelServiceOut:
    record = create_service(
        purpose=body.purpose,
        protocol=body.protocol,
        display_name=body.display_name,
        url=body.url,
        model=body.model,
        api_key=body.api_key,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return _out(record, in_use_id=store.get_purpose(record.purpose).in_use_id)


@router.get("/{service_id}")
def get_service(
    service_id: str,
    store: ModelServiceStore = Depends(get_model_service_store),
    _caller: UserRecord = Depends(require_permission("model_services:read")),
) -> ModelServiceOut:
    record = store.get(service_id)
    if record is None:
        raise ModelServiceNotFound()
    return _out(record, in_use_id=store.get_purpose(record.purpose).in_use_id)


@router.patch("/{service_id}")
def patch_service_http(
    service_id: str,
    body: ModelServicePatchIn,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: ModelServiceStore = Depends(get_model_service_store),
) -> ModelServiceOut:
    record = patch_service(
        service_id=service_id,
        display_name=body.display_name,
        url=body.url,
        model=body.model,
        protocol=body.protocol,
        api_key=body.api_key,
        clear_api_key=body.clear_api_key,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return _out(record, in_use_id=store.get_purpose(record.purpose).in_use_id)


@router.post("/{service_id}/test")
def test_service_http(
    service_id: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ModelServiceTestOut:
    return ModelServiceTestOut.model_validate(
        test_service(
            service_id=service_id,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
    )


@router.post("/{service_id}/activate")
def activate_service_http(
    service_id: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: ModelServiceStore = Depends(get_model_service_store),
) -> ModelServiceOut:
    record = activate_service(
        service_id=service_id,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )
    return _out(record, in_use_id=store.get_purpose(record.purpose).in_use_id)


@router.delete("/{service_id}", status_code=204)
def delete_service_http(
    service_id: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> None:
    delete_service(
        service_id=service_id,
        actor_user_id=caller.id,
        actor_token_id=actor_token_id,
    )


@router.post("/purpose/{purpose}/close")
def close_purpose_http(
    purpose: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        close_purpose(
            purpose=purpose,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
    )


@router.post("/purpose/{purpose}/open")
def open_purpose_http(
    purpose: str,
    body: ModelServiceOpenIn,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        open_purpose(
            purpose=purpose,
            rebuild=body.rebuild,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
    )


@router.post("/purpose/{purpose}/cleanup")
def cleanup_purpose_http(
    purpose: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        cleanup_purpose(
            purpose=purpose,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
    )


@router.post("/purpose/{purpose}/reindex")
def reindex_purpose_http(
    purpose: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        reindex_purpose(
            purpose=purpose,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
    )
