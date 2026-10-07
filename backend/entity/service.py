"""Business Entity definition, save, and deprecate orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, TypeVar

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.entity.classify import Classification, classify_shapes
from backend.entity.dictionary_binding import require_attribute_dictionaries
from backend.entity.errors import (
    EntityAlreadyDeprecated,
    EntityAlreadyPublished,
    EntityDeprecated,
    EntityNeverPublished,
    EntityNotFound,
    EntityNotPublished,
    EntityNotUnpublished,
    EntityPublishing,
    EntityReferenced,
    EntityRequestInvalid,
    EntityVersionIdConflict,
    EntityVersionNotFound,
    EntityVersionSuperseded,
)
from backend.entity.ids import new_entity_id, new_version_id
from backend.admin.roles import effective_permissions
from backend.admin.role_store import get_role_store
from backend.admin.subjects import user_group_ids
from backend.admin.user_store import UserRecord
from backend.entity.access.compiler import compile_policy, subject_outcome
from backend.entity.access.facts import Person
from backend.entity.access.plan import load_head, load_policy
from backend.entity.access.store import get_access_store
from backend.entity.inbound import inbound_references_for
from backend.entity.reference_binding import require_business_key_stable
from backend.entity.lifecycle import (
    PUBLISHED,
    UNPUBLISHED,
    EntityListStatus,
    any_publishing,
    current_version_of,
    ever_published,
    is_deprecated,
    status_filter_selection,
)
from backend.entity.present import entity_out, version_out
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import physical_table_name, table_present
from backend.entity.validate import (
    bind_reference_self,
    require_reference_targets,
    require_table_name,
    validate_shape,
)
from backend.jobs.store import get_job_store

__all__ = [
    "alignment_state",
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

_VERSION_ID_ATTEMPTS = 5
_T = TypeVar("_T")


def _with_fresh_version_id(insert: Callable[[str], _T]) -> _T:
    for _attempt in range(_VERSION_ID_ATTEMPTS - 1):
        try:
            return insert(new_version_id())
        except EntityVersionIdConflict:
            pass
    return insert(new_version_id())


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


def alignment_state(version: EntityVersionRecord) -> dict[str, Any]:
    job_id = version.latest_reconcile_job_id
    job = get_job_store().get(job_id) if job_id else None
    return {
        "table_present": table_present(version),
        "latest_job_id": version.latest_reconcile_job_id,
        "latest_job_status": job.status if job is not None else None,
    }


def _project_entity(
    entity: BusinessEntityRecord,
    current: EntityVersionRecord | None,
    *,
    include_inbound: bool,
    user: UserRecord | None = None,
) -> dict[str, Any]:
    _visible, see_physical, _names = _definition(user, entity.id)
    physical = None
    alignment = None
    if current is not None:
        if see_physical:
            physical = physical_table_name(current, entity.table_name)
        alignment = alignment_state(current)
    inbound = None
    if include_inbound:
        inbound = _visible_inbound(entity.id, user)
    return entity_out(
        entity,
        current=current,
        physical_table=physical,
        alignment=alignment,
        inbound_references=inbound,
    )


def _catalog_permissions(user: UserRecord) -> set[str]:
    if not user.role_id:
        return set()
    role = get_role_store().get_by_id(user.role_id)
    if role is None:
        return set()
    return set(effective_permissions(role))


def _sees_every_definition(user: UserRecord) -> bool:
    perms = _catalog_permissions(user)
    return "entity:write" in perms or "entity:access_manage" in perms


def _definition(
    user: UserRecord | None, entity_id: str
) -> tuple[bool, bool, set[str] | None]:
    if user is None or _sees_every_definition(user):
        return True, "entity:write" in _catalog_permissions(user) if user else True, None
    head = load_head(entity_id)
    revision = get_access_store().revision(entity_id)
    policy = load_policy(head, revision)
    compiled = compile_policy(policy)
    person = Person(
        user_id=user.id,
        role_id=user.role_id,
        group_ids=user_group_ids(user.id),
    )
    outcome = subject_outcome(compiled, policy, person, action="read", narrow=None)
    if not outcome.grant_ids and not outcome.over_limit:
        return False, False, set()
    return True, False, {column.attr.name for column in outcome.columns}


def _require_visible(user: UserRecord | None, entity_id: str) -> None:
    if user is None:
        return
    visible, _physical, _names = _definition(user, entity_id)
    if not visible:
        raise EntityNotFound()


def _visible_inbound(
    entity_id: str, user: UserRecord | None
) -> list[dict[str, str]]:
    rows = inbound_references_for(get_entity_store(), entity_id)
    if user is None or _sees_every_definition(user):
        return rows
    return [
        row
        for row in rows
        if _definition(user, row["entity_id"])[0]
    ]


def _project_version(
    version: EntityVersionRecord,
    *,
    entity: BusinessEntityRecord,
    include_attributes: bool,
    user: UserRecord | None = None,
) -> dict[str, Any]:
    _visible, see_physical, names = _definition(user, entity.id)
    return version_out(
        version,
        entity=entity,
        include_attributes=include_attributes,
        physical_table=(
            physical_table_name(version, entity.table_name) if see_physical else None
        ),
        alignment=alignment_state(version),
        attribute_names=None if names is None else frozenset(names),
    )


def get_entity(entity_id: str, *, user: UserRecord | None = None) -> dict[str, Any]:
    entity = require_entity(entity_id)
    _require_visible(user, entity.id)
    current = get_entity_store().current_version(entity.id)
    return _project_entity(entity, current, include_inbound=True, user=user)


def list_entities(
    *,
    q: str | None,
    statuses: list[EntityListStatus] | None,
    limit: int,
    offset: int,
    user: UserRecord | None = None,
) -> tuple[list[dict[str, Any]], int]:
    store = get_entity_store()
    full = user is None or _sees_every_definition(user)
    if full:
        records, total = store.list_entities(
            q=q,
            statuses=status_filter_selection(statuses),
            limit=limit,
            offset=offset,
        )
    else:
        records, _total = store.list_entities(
            q=q,
            statuses=status_filter_selection(statuses),
            limit=1_000_000,
            offset=0,
        )
        records = [entity for entity in records if _definition(user, entity.id)[0]]
        total = len(records)
        records = records[offset : offset + limit]
    items = [
        _project_entity(
            entity,
            store.current_version(entity.id),
            include_inbound=False,
            user=user,
        )
        for entity in records
    ]
    return items, total


def list_versions(
    entity_id: str, *, limit: int, offset: int, user: UserRecord | None = None
) -> tuple[list[dict[str, Any]], int]:
    entity = require_entity(entity_id)
    _require_visible(user, entity.id)
    versions, total = get_entity_store().list_versions(
        entity_id, limit=limit, offset=offset
    )
    return [
        _project_version(
            version,
            entity=entity,
            include_attributes=False,
            user=user,
        )
        for version in versions
    ], total


def get_version(
    entity_id: str, version_id: str, *, user: UserRecord | None = None
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    _require_visible(user, entity.id)
    version = require_version(entity_id, version_id)
    return _project_version(
        version,
        entity=entity,
        include_attributes=True,
        user=user,
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
    entity_id = new_entity_id()
    attrs = _require_writable_shape(
        attributes, entity_id=entity_id, previous=[]
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

    def _insert(version_id: str) -> EntityVersionRecord:
        version = EntityVersionRecord(
            id=version_id,
            entity_id=entity.id,
            version=1,
            attributes=attrs,
            materialized_attributes=[],
            publish_status=UNPUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        )
        _saved_entity, saved_version = get_entity_store().create_entity(entity, version)
        return saved_version

    version = _with_fresh_version_id(_insert)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.create",
        result="success",
        detail={"table_name": entity.table_name, "version_id": version.id},
    )
    return _project_entity(entity, version, include_inbound=True)


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
            current.attributes, proposed.attributes, versions=versions
        )
        change_class = result.change_class
        shape_changed = [attribute_to_dict(item) for item in proposed.attributes] != [
            attribute_to_dict(item) for item in current.attributes
        ]
    if not changed_fields and not shape_changed:
        return _project_entity(entity, current, include_inbound=True)
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
    return _project_entity(saved_entity, saved_version, include_inbound=True)


def classify_entity(
    entity_id: str,
    *,
    attributes: list[AttributeRecord] | None,
) -> dict[str, Any]:
    entity = require_entity(entity_id)
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    versions = get_entity_store().list_all_versions(entity_id)
    proposed = _overlay_shape(
        current,
        attributes=attributes,
        validate_write=False,
        entity_id=entity.id,
    )
    result = classify_shapes(
        current.attributes, proposed.attributes, versions=versions
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
        version.attributes, proposed.attributes, versions=versions
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
    return _project_version(
        saved,
        entity=entity,
        include_attributes=True,
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
    proposed_attributes = (
        list(current.attributes) if attributes is None else list(attributes)
    )
    result = classify_shapes(
        current.attributes, proposed_attributes, versions=versions
    )
    if result.change_class == "unchanged":
        stored_attributes = list(current.attributes)
    else:
        overlaid = _overlay_shape(
            current,
            attributes=proposed_attributes,
            validate_write=True,
            entity_id=entity.id,
        )
        stored_attributes = list(overlaid.attributes)
        result = classify_shapes(
            current.attributes, stored_attributes, versions=versions
        )
    now = utc_now()

    def _insert(version_id: str) -> EntityVersionRecord:
        version = EntityVersionRecord(
            id=version_id,
            entity_id=entity.id,
            version=current.version + 1,
            attributes=stored_attributes,
            materialized_attributes=[],
            publish_status=UNPUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        )
        return get_entity_store().create_version(version)

    saved = _with_fresh_version_id(_insert)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.version_open",
        result="success",
        detail={"class": result.change_class, "version_id": saved.id},
    )
    return _project_version(
        saved,
        entity=entity,
        include_attributes=True,
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
    return _project_entity(saved, current, include_inbound=True)


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
    _assert_not_publishing(versions)
    if ever_published(versions):
        raise EntityAlreadyPublished()


def _require_writable_shape(
    attributes: list[AttributeRecord],
    *,
    entity_id: str,
    previous: list[AttributeRecord],
) -> list[AttributeRecord]:
    """Apply write rules. The caller decides whether to store the result."""
    attrs = validate_shape(attributes=attributes)
    attrs = bind_reference_self(attrs, entity_id=entity_id)
    require_reference_targets(
        get_entity_store(),
        attrs,
        entity_id=entity_id,
    )
    require_attribute_dictionaries(attrs, previous=previous)
    require_business_key_stable(get_entity_store(), entity_id, previous, attrs)
    return attrs


def _overlay_shape(
    current: EntityVersionRecord,
    *,
    attributes: list[AttributeRecord] | None,
    validate_write: bool,
    entity_id: str,
) -> EntityVersionRecord:
    attrs = current.attributes if attributes is None else attributes
    if validate_write:
        attrs = _require_writable_shape(
            attrs, entity_id=entity_id, previous=current.attributes
        )
    else:
        attrs = bind_reference_self(attrs, entity_id=entity_id)
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
