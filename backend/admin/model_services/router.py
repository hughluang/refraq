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
    CatalogCoverageOut,
    CatalogIndexOut,
    EmbedScheduleOut,
    EntityCoverageOut,
    EntityIndexOut,
    ModelServiceCreateIn,
    ModelServiceList,
    ModelServiceOut,
    ModelServicePatchIn,
    ModelServiceSpecOut,
    ModelServiceTestOut,
    PurposeStateOut,
)
from backend.admin.model_services.ports import catalog_embed_jobs, entity_embed_jobs
from backend.admin.model_services.service import (
    activate_service,
    cleanup_purpose,
    close_purpose,
    create_service,
    force_generation,
    delete_service,
    index_status,
    open_purpose,
    patch_service,
    test_service,
)
from backend.admin.model_services.store import ModelServiceStore, get_model_service_store
from backend.admin.user_store import UserRecord
from backend.core.admission import await_admitted
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
        timeout_sec=record.timeout_sec,
        batch_limit=record.batch_limit,
        has_secret=bool(record.secret),
        in_use=in_use_id == record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _index_status_of(*, ready: bool, active: bool, latest: str | None) -> str:
    if ready:
        return "ready"
    if active:
        return "indexing"
    if latest == "failed":
        return "failed"
    return "none"


def _purpose_out(state: PurposeState) -> PurposeStateOut:
    jobs = catalog_embed_jobs()
    entity_jobs = entity_embed_jobs()
    view = jobs.schedule_view()
    embed_schedule = None
    if view is not None:
        embed_schedule = EmbedScheduleOut(
            id=view.id,
            enabled=view.enabled,
            cron=view.cron,
            interval_seconds=view.interval_seconds,
            next_run_at=view.next_run_at,
        )
    index = jobs.index_view()
    status = index_status()
    entity_view = entity_jobs.index_view()
    entity_status = _index_status_of(
        ready=entity_view.ready,
        active=entity_jobs.has_active(),
        latest=entity_jobs.latest_sweep_status(),
    )
    entity_schedule = entity_jobs.schedule_view()
    entity_schedule_out = None
    if entity_schedule is not None:
        entity_schedule_out = EmbedScheduleOut(
            id=entity_schedule.id,
            enabled=entity_schedule.enabled,
            cron=entity_schedule.cron,
            interval_seconds=entity_schedule.interval_seconds,
            next_run_at=entity_schedule.next_run_at,
        )
    return PurposeStateOut(
        purpose=state.purpose,
        closed=state.closed,
        ready=index.ready,
        in_use_id=state.in_use_id,
        generation=state.generation,
        control_revision=state.control_revision,
        index_status=status,  # type: ignore[arg-type]
        catalog_index=CatalogIndexOut(
            ready=index.ready,
            generation_last_swept=index.generation_last_swept,
            index_status=status,  # type: ignore[arg-type]
            coverage=CatalogCoverageOut(
                objects_written=index.objects_written,
                columns_written=index.columns_written,
                objects_failed=index.objects_failed,
                columns_failed=index.columns_failed,
                objects_attempted=index.objects_attempted,
                columns_attempted=index.columns_attempted,
            ),
            progress=index.progress,
            failure_summary=index.failure_summary,
            rebuild_owed=index.rebuild_owed,
        ),
        entity_index=EntityIndexOut(
            ready=entity_view.ready,
            generation=entity_view.generation,
            index_status=entity_status,  # type: ignore[arg-type]
            coverage=EntityCoverageOut(
                written=entity_view.written,
                failed=entity_view.failed,
                attempted=entity_view.attempted,
            ),
            progress=entity_view.progress,
            failure_summary=entity_view.failure_summary,
            schedule=entity_schedule_out,
            rebuild_owed=entity_view.rebuild_owed,
        ),
        embed_schedule=embed_schedule,
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
                {"name": "timeout_sec", "type": "integer", "required": True},
                {"name": "batch_limit", "type": "integer", "required": False},
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
            timeout_sec=body.timeout_sec,
            batch_limit=body.batch_limit,
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
async def patch_service_http(
    service_id: str,
    body: ModelServicePatchIn,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: ModelServiceStore = Depends(get_model_service_store),
) -> ModelServiceOut:
    def _run() -> ModelServiceRecord:
        return patch_service(
            service_id=service_id,
            display_name=body.display_name,
            url=body.url,
            model=body.model,
            protocol=body.protocol,
            timeout_sec=body.timeout_sec,
            batch_limit=body.batch_limit,
            api_key=body.api_key,
            clear_api_key=body.clear_api_key,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )

    probes = body.url is not None or body.api_key is not None
    record = await await_admitted(caller.id, _run) if probes else _run()
    return _out(record, in_use_id=store.get_purpose(record.purpose).in_use_id)


@router.post("/{service_id}/test")
async def test_service_http(
    service_id: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> ModelServiceTestOut:
    return ModelServiceTestOut.model_validate(
        await await_admitted(
            caller.id,
            lambda: test_service(
                service_id=service_id,
                actor_user_id=caller.id,
                actor_token_id=actor_token_id,
            ),
        )
    )


@router.post("/{service_id}/activate")
async def activate_service_http(
    service_id: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
    store: ModelServiceStore = Depends(get_model_service_store),
) -> ModelServiceOut:
    record = await await_admitted(
        caller.id,
        lambda: activate_service(
            service_id=service_id,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        ),
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


@router.post("/purpose/{purpose}/force-generation")
def force_generation_http(
    purpose: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        force_generation(
            purpose=purpose,
            actor_user_id=caller.id,
            actor_token_id=actor_token_id,
        )
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
async def open_purpose_http(
    purpose: str,
    caller: UserRecord = Depends(require_permission("model_services:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> PurposeStateOut:
    return _purpose_out(
        await await_admitted(
            caller.id,
            lambda: open_purpose(
                purpose=purpose,
                actor_user_id=caller.id,
                actor_token_id=actor_token_id,
            ),
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

