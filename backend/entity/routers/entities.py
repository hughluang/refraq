"""Business Entity HTTP routers."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, get_user_store
from backend.core.pagination import ENTITY_LIST, PageParams, page_params
from backend.entity.jobs import enqueue_drop, enqueue_publish
from backend.entity.errors import EntityAttributeInvalid
from backend.entity.records import AttributeRecord
from backend.entity.schemas.entities import (
    AttributeIn,
    BusinessEntityListResponse,
    BusinessEntityOut,
    BusinessEntityResponse,
    ClassificationOut,
    EntityCreateRequest,
    EntityJobEnqueueResponse,
    EntityPatchRequest,
    EntityVersionListResponse,
    EntityVersionOut,
    EntityVersionResponse,
    ShapeWriteRequest,
)
from backend.entity.service import (
    classify_entity,
    create_entity,
    delete_entity,
    deprecate_entity,
    get_entity,
    get_version,
    list_entities,
    list_versions,
    open_version,
    patch_entity,
    patch_version,
)
from backend.jobs.api import get_schedule_name_store, present_jobs
from backend.jobs.store import JobRecord

router = APIRouter(tags=["entities"])


def _attrs(items: list[AttributeIn] | None) -> list[AttributeRecord] | None:
    if items is None:
        return None

    return [_record(item) for item in items]


def _record(item: AttributeIn) -> AttributeRecord:
    assert item.type is not None and item.config is not None
    config = item.config
    return AttributeRecord(
        name=item.name,
        type=item.type,
        required=item.required,
        unique=item.unique,
        indexed=item.indexed,
        description=item.description,
        max_length=_config_int(item.name, "max_length", config.get("max_length"))
        if "max_length" in config
        else None,
        precision=_config_int(item.name, "precision", config.get("precision"))
        if "precision" in config
        else None,
        scale=_config_int(item.name, "scale", config.get("scale"))
        if "scale" in config
        else None,
        dictionary_id=_config_dictionary_id(item.name, config.get("dictionary_id"))
        if "dictionary_id" in config
        else None,
        target_entity_id=_optional_target(item.name, config.get("target_entity_id"))
        if "target_entity_id" in config
        else None,
    )


def _config_int(name: str, field: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' {field} must be an integer"
        )
    return value


def _optional_target(name: str, value: Any) -> str | None:
    """JSON null matches a stored reference that has no target entity."""
    if value is None:
        return None
    return _config_target(name, value)


def _config_target(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' target_entity_id must be a string"
        )
    return value.strip()


def _config_dictionary_id(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' dictionary_id must be a string"
        )
    return value.strip()


def _present_job(record: JobRecord) -> Any:
    return present_jobs(
        [record],
        users=get_user_store(),
        schedules=get_schedule_name_store(),
    )[0]


@router.get("/entities", response_model=BusinessEntityListResponse)
def http_list_entities(
    q: str | None = Query(default=None),
    status: list[Literal["not_serving", "serving", "deprecated"]] | None = Query(
        default=None
    ),
    page: PageParams = Depends(page_params(ENTITY_LIST)),
    _: UserRecord = Depends(require_permission("entity:read")),
) -> BusinessEntityListResponse:
    items, total = list_entities(
        q=q, statuses=status, limit=page.limit, offset=page.offset
    )
    return BusinessEntityListResponse(
        items=[BusinessEntityOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/entities",
    response_model=BusinessEntityResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_create_entity(
    body: EntityCreateRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> BusinessEntityResponse:
    attrs = _attrs(body.attributes)
    assert attrs is not None
    payload = create_entity(
        table_name=body.table_name,
        name=body.name,
        description=body.description,
        attributes=attrs,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return BusinessEntityResponse(entity=BusinessEntityOut.model_validate(payload))


@router.get("/entities/{entity_id}", response_model=BusinessEntityResponse)
def http_get_entity(
    entity_id: str,
    _: UserRecord = Depends(require_permission("entity:read")),
) -> BusinessEntityResponse:
    return BusinessEntityResponse(
        entity=BusinessEntityOut.model_validate(get_entity(entity_id))
    )


@router.patch("/entities/{entity_id}", response_model=BusinessEntityResponse)
def http_patch_entity(
    entity_id: str,
    body: EntityPatchRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> BusinessEntityResponse:
    provided = body.model_dump(exclude_unset=True)
    payload = patch_entity(
        entity_id=entity_id,
        name=body.name if "name" in provided else None,
        description=body.description if "description" in provided else None,
        attributes=_attrs(body.attributes) if "attributes" in provided else None,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return BusinessEntityResponse(entity=BusinessEntityOut.model_validate(payload))


@router.delete(
    "/entities/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def http_delete_entity(
    entity_id: str,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_entity(
        entity_id=entity_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/entities/{entity_id}/deprecate", response_model=BusinessEntityResponse)
def http_deprecate_entity(
    entity_id: str,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> BusinessEntityResponse:
    payload = deprecate_entity(
        entity_id=entity_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return BusinessEntityResponse(entity=BusinessEntityOut.model_validate(payload))


@router.post("/entities/{entity_id}/classify", response_model=ClassificationOut)
def http_classify_entity(
    entity_id: str,
    body: ShapeWriteRequest,
    _: UserRecord = Depends(require_permission("entity:read")),
) -> ClassificationOut:
    payload = classify_entity(
        entity_id,
        attributes=_attrs(body.attributes),
    )
    return ClassificationOut.model_validate(payload)


@router.get("/entities/{entity_id}/versions", response_model=EntityVersionListResponse)
def http_list_versions(
    entity_id: str,
    page: PageParams = Depends(page_params(ENTITY_LIST)),
    _: UserRecord = Depends(require_permission("entity:read")),
) -> EntityVersionListResponse:
    items, total = list_versions(entity_id, limit=page.limit, offset=page.offset)
    return EntityVersionListResponse(
        items=[EntityVersionOut.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/entities/{entity_id}/versions",
    response_model=EntityVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def http_open_version(
    entity_id: str,
    body: ShapeWriteRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> EntityVersionResponse:
    payload = open_version(
        entity_id=entity_id,
        attributes=_attrs(body.attributes),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return EntityVersionResponse(version=EntityVersionOut.model_validate(payload))


@router.get(
    "/entities/{entity_id}/versions/{version_id}",
    response_model=EntityVersionResponse,
)
def http_get_version(
    entity_id: str,
    version_id: str,
    _: UserRecord = Depends(require_permission("entity:read")),
) -> EntityVersionResponse:
    return EntityVersionResponse(
        version=EntityVersionOut.model_validate(get_version(entity_id, version_id))
    )


@router.patch(
    "/entities/{entity_id}/versions/{version_id}",
    response_model=EntityVersionResponse,
)
def http_patch_version(
    entity_id: str,
    version_id: str,
    body: ShapeWriteRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> EntityVersionResponse:
    payload = patch_version(
        entity_id=entity_id,
        version_id=version_id,
        attributes=_attrs(body.attributes),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    return EntityVersionResponse(version=EntityVersionOut.model_validate(payload))


@router.post(
    "/entities/{entity_id}/versions/{version_id}/publish",
    response_model=EntityJobEnqueueResponse,
)
def http_publish(
    entity_id: str,
    version_id: str,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response | EntityJobEnqueueResponse:
    job, minted = enqueue_publish(
        entity_id=entity_id,
        version_id=version_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    payload = EntityJobEnqueueResponse(job=_present_job(job), version=None)
    if minted:
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=payload.model_dump(mode="json"),
        )
    return payload


@router.post(
    "/entities/{entity_id}/versions/{version_id}/drop-table",
    response_model=EntityJobEnqueueResponse,
)
def http_drop_table(
    entity_id: str,
    version_id: str,
    user: UserRecord = Depends(require_permission("entity:drop_table")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response | EntityJobEnqueueResponse:
    result = enqueue_drop(
        entity_id=entity_id,
        version_id=version_id,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
    )
    job_out = _present_job(result.job) if result.job is not None else None
    version_out = (
        EntityVersionOut.model_validate(result.version)
        if result.version is not None
        else None
    )
    payload = EntityJobEnqueueResponse(job=job_out, version=version_out)
    if result.minted:
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=payload.model_dump(mode="json"),
        )
    return payload
