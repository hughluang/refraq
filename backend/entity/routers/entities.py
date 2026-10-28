"""Business Entity HTTP routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, get_user_store
from backend.core.pagination import ENTITY_LIST, PageParams, page_params
from backend.core.time import parse_instant
from backend.entity.attribute_type import resolve
from backend.entity.change_log import (
    CHANGE_LOG_PAGE_LIMIT,
    SOURCE_USER,
    ChangeLogEntry,
    ChangeLogTable,
    ensure_shared_relations,
    read_change_log,
    read_change_log_entry,
)
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import EntityNotFound, EntityRequestInvalid
from backend.entity.jobs import enqueue_drop
from backend.entity.publish import accept
from backend.entity.records import AttributeRecord
from backend.entity.reference_binding import business_key_attr
from backend.entity.schemas.entities import (
    AttributeIn,
    BusinessEntityListResponse,
    BusinessEntityOut,
    BusinessEntityResponse,
    ChangeLogDetailOut,
    ChangeLogEntryOut,
    ChangeLogPageOut,
    ClassificationOut,
    EntityBulkTagsRequest,
    EntityBulkTagsResponse,
    EntityCreateRequest,
    EntityJobEnqueueResponse,
    EntityPatchRequest,
    EntityTagsReplaceRequest,
    EntityTagsReplaceResponse,
    EntityVersionListResponse,
    EntityVersionOut,
    EntityVersionResponse,
    ShapeWriteRequest,
)
from backend.entity.service import (
    add_entity_tags,
    change_log_on_entity_database,
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
    remove_entity_tags,
    replace_entity_tags,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import physical_table_name, published_attributes
from backend.jobs.api import get_schedule_name_store, present_jobs
from backend.jobs.store import JobRecord

router = APIRouter(tags=["entities"])


def _attrs(items: list[AttributeIn] | None) -> list[AttributeRecord] | None:
    if items is None:
        return None

    return [_record(item) for item in items]


def _record(item: AttributeIn) -> AttributeRecord:
    assert item.type is not None and item.config is not None
    fields = resolve(item.type).parse_config(item.name, item.config)
    return AttributeRecord(
        name=item.name,
        type=item.type,
        required=item.required,
        unique=item.unique,
        indexed=item.indexed,
        business_key=item.business_key,
        description=item.description,
        **fields,
    )


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
    tag_id: list[str] | None = Query(default=None),
    page: PageParams = Depends(page_params(ENTITY_LIST)),
    user: UserRecord = Depends(require_permission("entity:read")),
) -> BusinessEntityListResponse:
    items, total = list_entities(
        q=q,
        statuses=status,
        tag_ids=tag_id,
        limit=page.limit,
        offset=page.offset,
        user=user,
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
    tags = body.tags
    payload = create_entity(
        table_name=body.table_name,
        name=body.name,
        description=body.description,
        attributes=attrs,
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
        tag_ids=list(tags.tag_ids) if tags is not None else [],
        names=list(tags.names) if tags is not None else [],
        change_log_enabled=body.change_log_enabled,
        change_log_retention_days=body.change_log_retention_days,
    )
    return BusinessEntityResponse(entity=BusinessEntityOut.model_validate(payload))


@router.get("/entities/{entity_id}", response_model=BusinessEntityResponse)
def http_get_entity(
    entity_id: str,
    user: UserRecord = Depends(require_permission("entity:read")),
) -> BusinessEntityResponse:
    return BusinessEntityResponse(
        entity=BusinessEntityOut.model_validate(get_entity(entity_id, user=user))
    )


@router.get("/entities/{entity_id}/change-log", response_model=ChangeLogPageOut)
def http_list_change_log(
    entity_id: str,
    before_sequence: int | None = Query(default=None, ge=1),
    operation: Literal["insert", "update", "delete"] | None = None,
    source: Literal["user", "channel_run", "unattributed"] | None = None,
    subject: str | None = None,
    row_identity: str | None = None,
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    user: UserRecord = Depends(require_permission("entity:data_read")),
) -> ChangeLogPageOut:
    tables = _change_log_tables(entity_id, user)
    if not change_log_on_entity_database():
        return ChangeLogPageOut(items=[], limit=CHANGE_LOG_PAGE_LIMIT, next_before_sequence=None)
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        page = read_change_log(
            conn,
            entity_id,
            tables,
            before_sequence=before_sequence,
            operation=operation,
            source=source,
            subject=_blank(subject),
            row_identity=_blank(row_identity),
            occurred_from=_bound(occurred_from),
            occurred_to=_bound(occurred_to),
        )
    return ChangeLogPageOut(
        items=[_change_log_item(entry, tables) for entry in page.items],
        limit=page.limit,
        next_before_sequence=page.next_before_sequence,
    )


@router.get(
    "/entities/{entity_id}/change-log/{sequence}",
    response_model=ChangeLogDetailOut,
)
def http_get_change_log_entry(
    entity_id: str,
    sequence: int,
    user: UserRecord = Depends(require_permission("entity:data_read")),
) -> ChangeLogDetailOut:
    if sequence < 1:
        raise EntityRequestInvalid("sequence must be at least 1")
    tables = _change_log_tables(entity_id, user)
    if not change_log_on_entity_database():
        raise EntityNotFound("Change log entry not found")
    with get_entity_engine().begin() as conn:
        ensure_shared_relations(conn)
        entry = read_change_log_entry(conn, entity_id, tables, sequence)
    if entry is None:
        raise EntityNotFound("Change log entry not found")
    item = _change_log_item(entry, tables)
    return ChangeLogDetailOut(
        **item.model_dump(),
        before=entry.before,
        after=entry.after,
    )


def _change_log_tables(entity_id: str, user: UserRecord) -> list[ChangeLogTable]:
    """Physical tables of this entity. Missing or invisible entity is not found."""
    get_entity(entity_id, user=user)
    entity = get_entity_store().get_entity(entity_id)
    assert entity is not None
    tables: list[ChangeLogTable] = []
    for version in get_entity_store().list_all_versions(entity_id):
        name = physical_table_name(version, entity.table_name)
        if name is None:
            continue
        attributes = tuple(published_attributes(version))
        key = business_key_attr(attributes)
        tables.append(
            ChangeLogTable(
                physical_table=qualified_table(ENTITY_DATA_SCHEMA, name),
                attributes=attributes,
                reference_snapshots=dict(version.reference_snapshots),
                business_key=None if key is None else key.name,
            )
        )
    return tables


def _change_log_item(entry: ChangeLogEntry, tables: list[ChangeLogTable]) -> ChangeLogEntryOut:
    image = entry.after if entry.after is not None else entry.before
    row: dict[str, Any] = {} if image is None else image
    key_name = next(
        (table.business_key for table in tables if table.physical_table == entry.physical_table),
        None,
    )
    row_id = row.get("row_id")
    return ChangeLogEntryOut(
        sequence=entry.sequence,
        occurred_at=entry.occurred_at,
        operation=entry.operation,
        row_id=None if row_id is None else int(row_id),
        business_key=None if key_name is None else row.get(key_name),
        physical_table=entry.physical_table,
        source=entry.source,
        subject=entry.subject,
        subject_label=_subject_label(entry.source, entry.subject),
    )


def _subject_label(source: str | None, subject: str | None) -> str | None:
    if source is None or subject is None:
        return None
    if source == SOURCE_USER:
        found = get_user_store().get_by_id(subject)
        if found is None:
            return subject
        return found.display_name
    return subject


def _blank(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def _bound(value: str | None) -> datetime | None:
    cleaned = _blank(value)
    if cleaned is None:
        return None
    try:
        return parse_instant(cleaned)
    except ValueError as exc:
        raise EntityRequestInvalid("occurred_at bound must be an Instant") from exc


@router.put(
    "/entities/{entity_id}/tags",
    response_model=EntityTagsReplaceResponse,
)
def http_replace_entity_tags(
    entity_id: str,
    body: EntityTagsReplaceRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> EntityTagsReplaceResponse:
    payload = replace_entity_tags(
        entity_id=entity_id,
        base_revision=body.base_revision,
        tag_ids=list(body.tag_ids),
        names=list(body.names),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
        user=user,
    )
    return EntityTagsReplaceResponse.model_validate(payload)


@router.post("/entities/tags/add", response_model=EntityBulkTagsResponse)
def http_add_entity_tags(
    body: EntityBulkTagsRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> EntityBulkTagsResponse:
    payload = add_entity_tags(
        entity_ids=list(body.entity_ids),
        tag_ids=list(body.tag_ids),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
        user=user,
    )
    return EntityBulkTagsResponse.model_validate(payload)


@router.post("/entities/tags/remove", response_model=EntityBulkTagsResponse)
def http_remove_entity_tags(
    body: EntityBulkTagsRequest,
    user: UserRecord = Depends(require_permission("entity:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> EntityBulkTagsResponse:
    payload = remove_entity_tags(
        entity_ids=list(body.entity_ids),
        tag_ids=list(body.tag_ids),
        actor_user_id=user.id,
        actor_token_id=actor_token_id,
        user=user,
    )
    return EntityBulkTagsResponse.model_validate(payload)


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
        change_log_enabled=body.change_log_enabled,
        change_log_retention_days=body.change_log_retention_days,
        change_log_retention_set="change_log_retention_days" in provided,
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
    user: UserRecord = Depends(require_permission("entity:read")),
) -> EntityVersionListResponse:
    items, total = list_versions(
        entity_id, limit=page.limit, offset=page.offset, user=user
    )
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
    user: UserRecord = Depends(require_permission("entity:read")),
) -> EntityVersionResponse:
    return EntityVersionResponse(
        version=EntityVersionOut.model_validate(
            get_version(entity_id, version_id, user=user)
        )
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
    job, minted = accept(
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


@router.post("/entities/{entity_id}/versions/{version_id}/publish/preview")
def http_publish_preview(
    entity_id: str,
    version_id: str,
    user: UserRecord = Depends(require_permission("entity:write")),
) -> dict[str, Any]:
    from backend.entity.publish_confirmation import (
        change_log_publish_effect,
        incompatible_write_nodes,
    )
    from backend.entity.service import get_version, live_change_log

    version = get_version(entity_id, version_id, user=user)
    effective_enabled, effective_days = live_change_log(entity_id)
    return {
        "incompatible_write_nodes": incompatible_write_nodes(
            entity_id, version.get("attributes") or []
        ),
        "change_log_effect": change_log_publish_effect(
            effective_recording=effective_enabled,
            effective_retention_days=effective_days,
            draft_recording=bool(version.get("change_log_enabled")),
            draft_retention_days=version.get("change_log_retention_days"),
        ),
    }


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
