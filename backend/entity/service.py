"""Business Entity definition, save, publish, and deprecate orchestration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.entity.classify import (
    Classification,
    DefinitionShape,
    classify_shapes,
)
from backend.entity.errors import (
    EntityAlreadyDeprecated,
    EntityAlreadyPublished,
    EntityDeprecated,
    EntityNeverPublished,
    EntityNotFound,
    EntityNotPublished,
    EntityNotUnpublished,
    EntityPublishEmpty,
    EntityPublishing,
    EntityReferenced,
    EntityRequestInvalid,
    EntityVersionNotFound,
    EntityVersionSuperseded,
)
from backend.entity.ids import new_entity_id, new_version_id
from backend.entity.lifecycle import (
    PUBLISHED,
    PUBLISHING,
    UNPUBLISHED,
    EntityListStatus,
    any_publishing,
    ever_published,
    is_deprecated,
    status_filter_selection,
)
from backend.entity.present import (
    current_version_of,
    entity_out,
    inbound_references_for,
    latest_published_of,
    version_out,
)
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store
from backend.entity.validate import (
    bind_reference_self,
    require_reference_targets,
    require_table_name,
    validate_shape,
)

__all__ = [
    "classify_entity",
    "create_entity",
    "delete_entity",
    "deprecate_entity",
    "get_entity",
    "get_version",
    "list_entities",
    "list_versions",
    "open_version",
    "patch_entity",
    "patch_version",
    "require_entity",
    "require_version",
]


def require_entity(entity_id: str) -> BusinessEntityRecord:
    record = get_entity_store().get_entity(entity_id)
    if record is None:
        raise EntityNotFound()
    return record


def require_version(entity_id: str, version_id: str) -> EntityVersionRecord:
    require_entity(entity_id)
    version = get_entity_store().get_version(version_id)
    if version is None or version.entity_id != entity_id:
        raise EntityVersionNotFound()
    return version


def get_entity(entity_id: str) -> dict[str, Any]:
    entity = require_entity(entity_id)
    current = get_entity_store().current_version(entity.id)
    return entity_out(entity, current=current, include_inbound_references=True)


def list_entities(
    *,
    q: str | None,
    statuses: list[EntityListStatus] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    store = get_entity_store()
    records, total = store.list_entities(
        q=q,
        statuses=status_filter_selection(statuses),
        limit=limit,
        offset=offset,
    )
    items = []
    for entity in records:
        current = store.current_version(entity.id)
        items.append(entity_out(entity, current=current))
    return items, total


def list_versions(
    entity_id: str, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    entity = require_entity(entity_id)
    versions, total = get_entity_store().list_versions(
        entity_id, limit=limit, offset=offset
    )
    all_versions = get_entity_store().list_all_versions(entity_id)
    latest = latest_published_of(all_versions)
    return [
        version_out(
            version,
            entity=entity,
            include_attributes=False,
            latest_published=latest,
        )
        for version in versions
    ], total


def get_version(entity_id: str, version_id: str) -> dict[str, Any]:
    entity = require_entity(entity_id)
    version = require_version(entity_id, version_id)
    all_versions = get_entity_store().list_all_versions(entity_id)
    return version_out(
        version,
        entity=entity,
        include_attributes=True,
        latest_published=latest_published_of(all_versions),
    )


def create_entity(
    *,
    table_name: str,
    name: str,
    description: str,
    attributes: list[AttributeRecord],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    cleaned_table_name = require_table_name(table_name)
    cleaned_name = _require_text(name, "name")
    cleaned_description = _require_text(description, "description")
    attrs = validate_shape(attributes=attributes)
    entity_id = new_entity_id()
    attrs = bind_reference_self(attrs, entity_id=entity_id)
    require_reference_targets(
        get_entity_store(),
        attrs,
        entity_id=entity_id,
    )
    now = utc_now()
    entity = BusinessEntityRecord(
        id=entity_id,
        table_name=cleaned_table_name,
        name=cleaned_name,
        description=cleaned_description,
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=attrs,
        materialized_attributes=[],
        publish_status=UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.create",
        result="success",
        detail={"table_name": entity.table_name, "version_id": version.id},
    )
    return entity_out(entity, current=version, include_inbound_references=True)


def patch_entity(
    *,
    entity_id: str,
    name: str | None,
    description: str | None,
    attributes: list[AttributeRecord] | None = None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    assert current is not None
    _assert_unpublished_authoring(entity, versions, current)
    now = utc_now()
    new_name = entity.name
    new_description = entity.description
    changed_fields: list[str] = []
    if name is not None:
        cleaned = _require_text(name, "name")
        if cleaned != entity.name:
            changed_fields.append("name")
            new_name = cleaned
    if description is not None:
        cleaned = _require_text(description, "description")
        if cleaned != entity.description:
            changed_fields.append("description")
            new_description = cleaned
    proposed = current
    change_class = "unchanged"
    shape_changed = False
    if attributes is not None:
        proposed = _overlay_shape(
            current,
            attributes=attributes,
            validate_write=True,
            entity_id=entity.id,
        )
        result = classify_shapes(
            DefinitionShape(attributes=tuple(current.attributes)),
            DefinitionShape(attributes=tuple(proposed.attributes)),
        )
        change_class = result.change_class
        shape_changed = [attribute_to_dict(item) for item in proposed.attributes] != [
            attribute_to_dict(item) for item in current.attributes
        ]
    if not changed_fields and not shape_changed:
        return entity_out(entity, current=current, include_inbound_references=True)
    store = get_entity_store()
    saved_entity = entity
    saved_version = current
    updated_entity = (
        replace(
            entity,
            name=new_name,
            description=new_description,
            updated_at=now,
        )
        if changed_fields
        else None
    )
    updated_version = (
        replace(proposed, attributes=list(proposed.attributes), updated_at=now)
        if shape_changed
        else None
    )
    if updated_entity is not None and updated_version is not None:
        saved_entity, saved_version = store.save_entity_and_version(
            updated_entity,
            updated_version,
        )
    elif updated_entity is not None:
        saved_entity = store.save_entity(updated_entity)
    else:
        assert updated_version is not None
        saved_version = store.save_version(updated_version)
    detail: dict[str, Any] = {
        "class": change_class if shape_changed else "unchanged",
    }
    if changed_fields:
        detail["fields"] = changed_fields
    if shape_changed:
        detail["version_id"] = saved_version.id
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity_id,
        action="entity.patch",
        result="success",
        detail=detail,
    )
    return entity_out(
        saved_entity, current=saved_version, include_inbound_references=True
    )


def classify_entity(
    entity_id: str,
    *,
    attributes: list[AttributeRecord] | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    proposed = _overlay_shape(
        current,
        attributes=attributes,
        validate_write=False,
        entity_id=entity.id,
    )
    result = classify_shapes(
        DefinitionShape(attributes=tuple(current.attributes)),
        DefinitionShape(attributes=tuple(proposed.attributes)),
    )
    return _classification_out(result)


def patch_version(
    *,
    entity_id: str,
    version_id: str,
    attributes: list[AttributeRecord] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    version = require_version(entity_id, version_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    if current is None or current.id != version.id:
        raise EntityVersionSuperseded()
    _assert_unpublished_authoring(entity, versions, current)
    proposed = _overlay_shape(
        version,
        attributes=attributes,
        validate_write=True,
        entity_id=entity.id,
    )
    result = classify_shapes(
        DefinitionShape(attributes=tuple(version.attributes)),
        DefinitionShape(attributes=tuple(proposed.attributes)),
    )
    now = utc_now()
    updated = replace(
        version,
        attributes=list(proposed.attributes),
        updated_at=now,
    )
    saved = get_entity_store().save_version(updated)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.patch",
        result="success",
        detail={"class": result.change_class, "version_id": saved.id},
    )
    return version_out(
        saved,
        entity=entity,
        include_attributes=True,
        latest_published=latest_published_of(versions),
    )


def open_version(
    *,
    entity_id: str,
    attributes: list[AttributeRecord] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    assert current is not None
    _assert_not_deprecated(entity)
    _assert_not_publishing(versions)
    if current.publish_status != PUBLISHED:
        raise EntityNotPublished()
    proposed = _overlay_shape(
        current,
        attributes=attributes,
        validate_write=True,
        entity_id=entity.id,
    )
    result = classify_shapes(
        DefinitionShape(attributes=tuple(current.attributes)),
        DefinitionShape(attributes=tuple(proposed.attributes)),
    )
    now = utc_now()
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=current.version + 1,
        attributes=list(proposed.attributes),
        materialized_attributes=[],
        publish_status=UNPUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    saved = get_entity_store().create_version(version)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.version_open",
        result="success",
        detail={"class": result.change_class, "version_id": saved.id},
    )
    return version_out(
        saved,
        entity=entity,
        include_attributes=True,
        latest_published=latest_published_of(versions),
    )


def deprecate_entity(
    *,
    entity_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    assert current is not None
    _assert_not_publishing(versions)
    if is_deprecated(entity):
        raise EntityAlreadyDeprecated()
    if not ever_published(versions):
        raise EntityNeverPublished()
    if inbound_references_for(get_entity_store(), entity.id):
        raise EntityReferenced()
    now = utc_now()
    saved = get_entity_store().save_entity(replace(entity, deprecated_at=now, updated_at=now))
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.deprecate",
        result="success",
        detail={"table_name": entity.table_name},
    )
    return entity_out(saved, current=current, include_inbound_references=True)


def delete_entity(
    *,
    entity_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    entity = require_entity(entity_id)
    _assert_never_published(entity_id)
    if inbound_references_for(get_entity_store(), entity.id):
        raise EntityReferenced()
    get_entity_store().delete_entity(entity_id)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity_id,
        action="entity.delete",
        result="success",
        detail={"table_name": entity.table_name},
    )


def _assert_unpublished_authoring(
    entity: BusinessEntityRecord,
    versions: list[EntityVersionRecord],
    current: EntityVersionRecord,
) -> None:
    _assert_not_deprecated(entity)
    _assert_not_publishing(versions)
    if current.publish_status != UNPUBLISHED:
        raise EntityNotUnpublished()


def _assert_not_deprecated(entity: BusinessEntityRecord) -> None:
    if is_deprecated(entity):
        raise EntityDeprecated()


def _assert_not_publishing(versions: list[EntityVersionRecord]) -> None:
    if any_publishing(versions):
        raise EntityPublishing()


def _assert_never_published(entity_id: str) -> None:
    require_entity(entity_id)
    versions = get_entity_store().list_all_versions(entity_id)
    if ever_published(versions) or any_publishing(versions):
        raise EntityAlreadyPublished()


def prepare_publish(entity_id: str, version_id: str) -> EntityVersionRecord:
    """Validate publish and return the current unpublished version."""
    entity = require_entity(entity_id)
    version = require_version(entity_id, version_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    if current is None or current.id != version.id:
        raise EntityVersionSuperseded()
    _assert_not_deprecated(entity)
    if current.publish_status == PUBLISHING:
        return current
    if current.publish_status != UNPUBLISHED:
        raise EntityNotUnpublished()
    if not current.attributes:
        raise EntityPublishEmpty()
    return current


def _overlay_shape(
    current: EntityVersionRecord,
    *,
    attributes: list[AttributeRecord] | None,
    validate_write: bool,
    entity_id: str,
) -> EntityVersionRecord:
    attrs = current.attributes if attributes is None else attributes
    if validate_write:
        attrs = validate_shape(attributes=attrs)
    attrs = bind_reference_self(attrs, entity_id=entity_id)
    if validate_write:
        require_reference_targets(
            get_entity_store(),
            attrs,
            entity_id=entity_id,
        )
    return replace(current, attributes=list(attrs))


def _require_text(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise EntityRequestInvalid(f"{field} is required")
    return cleaned


def _classification_out(result: Classification) -> dict[str, Any]:
    return {
        "class": result.change_class,
        "changes": [
            {
                "field": change.field,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "class": change.change_class,
            }
            for change in result.changes
        ],
    }
