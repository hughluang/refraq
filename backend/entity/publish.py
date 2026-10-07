"""One Publish attempt: accept a version, then create its table and store published."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.entity.access.compiler import compile_policy
from backend.entity.access.seed import ensure_creator_grant
from backend.entity.access.plan import load_policy, make_head
from backend.entity.access.store import get_access_store
from backend.entity.access.views import (
    persist_ready,
    profile_view_statements,
    restore_profile_views,
)
from backend.entity.classify import classify_shapes
from backend.entity.ddl import ENTITY_DATA_SCHEMA, attr_wants_index
from backend.entity.dictionary_binding import (
    bind_publish,
    freeze_publish_bindings,
    frozen_bindings_cover,
    require_attribute_dictionaries,
)
from backend.entity.errors import (
    EntityAttributeInvalid,
    EntityNotUnpublished,
    EntityPublishEmpty,
    EntityVersionSuperseded,
)
from backend.entity.ids import new_attribute_id
from backend.entity.kinds import KIND_RECONCILE
from backend.entity.lifecycle import (
    PUBLISHED,
    PUBLISHING,
    UNPUBLISHED,
    current_version_of,
    latest_published_of,
)
from backend.entity.reference_binding import (
    bind_reference_publish,
    freeze_reference_bindings,
    frozen_reference_bindings_cover,
    require_business_key_stable,
)
from backend.entity.records import (
    AttributeRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.service import (
    _assert_not_deprecated,
    _require_writable_shape,
    require_entity,
    require_version,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import (
    compose_physical_table_name,
    physical_table_name,
    table_present,
)
from backend.entity.table_port import (
    EntityTableHasRows,
    EntityTableNameConflict,
    get_entity_table_port,
)
from backend.jobs.store import (
    TERMINAL,
    JobRecord,
    append_job_log,
    create_queued_job,
    format_job_log_line,
    get_job_store,
    mark_failed,
    mark_succeeded,
)

__all__ = [
    "accept",
    "assign_attribute_ids",
    "execute",
    "rollback_status",
]


def accept(
    *,
    entity_id: str,
    version_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[JobRecord, bool]:
    """Validate, freeze dictionary bindings, mark publishing, and enqueue."""
    from backend.entity import jobs as entity_jobs

    entity = require_entity(entity_id)
    version = _prepare(entity_id, version_id)
    inflight = entity_jobs.find_inflight_entity_table_job(version.id)
    if inflight is not None:
        return inflight, False
    job = create_queued_job(
        kind=KIND_RECONCILE,
        input={
            "entity_version_id": version.id,
            "dictionary_bindings": freeze_publish_bindings(version.attributes),
            "reference_bindings": freeze_reference_bindings(
                get_entity_store(),
                version.attributes,
                entity_id=entity.id,
            ),
        },
        created_by=actor_user_id,
        summary=f"entity_reconcile · {entity.table_name}",
        trigger_kind="user",
        trigger_ref=actor_user_id,
        log_body=format_job_log_line(level="info", message="queued entity table publish"),
    )
    get_entity_store().save_version(
        replace(
            version,
            publish_status=PUBLISHING,
            latest_reconcile_job_id=job.id,
            updated_at=utc_now(),
        )
    )
    entity_jobs.dispatch_entity_job(job)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.publish_enqueue",
        result="success",
        detail={"job_id": job.id, "version_id": version.id},
    )
    return job, True


def execute(job_id: str, job_input: dict[str, Any]) -> dict[str, str]:
    """Create the table, swap the stem view, then store published. Or roll back."""
    version_id = job_input.get("entity_version_id")
    version = get_entity_store().get_version(version_id)
    if version is None:
        return _fail(job_id, "ENTITY_VERSION_NOT_FOUND", "Entity Version not found")
    entity = get_entity_store().get_entity(version.entity_id)
    if entity is None:
        return _fail(job_id, "ENTITY_NOT_FOUND", "Business Entity not found")
    bindings = frozen_bindings_cover(
        version.attributes, job_input.get("dictionary_bindings")
    )
    reference_bindings = frozen_reference_bindings_cover(
        version.attributes, job_input.get("reference_bindings")
    )
    if bindings is None or reference_bindings is None:
        rollback_status(version)
        return _fail(
            job_id,
            "JOB_INPUT_INVALID",
            "publish bindings do not cover the version's dictionary and reference attributes",
        )
    schema = ENTITY_DATA_SCHEMA
    stem = entity.table_name
    physical, comment = compose_physical_table_name(stem, version.version, version.id)
    versions = get_entity_store().list_all_versions(entity.id)
    previous = latest_published_of(versions)
    expected_target: str | None = None
    if (
        previous is not None
        and previous.id != version.id
        and table_present(previous)
    ):
        expected_target = physical_table_name(previous, stem)
    attributes = assign_attribute_ids(version.attributes, previous)
    try:
        definition, snapshots = bind_publish(attributes, bindings)
        definition, reference_snapshots = bind_reference_publish(
            get_entity_store(),
            definition,
            reference_bindings,
            entity_id=entity.id,
        )
    except EntityAttributeInvalid as exc:
        rollback_status(version)
        return _fail(job_id, exc.code, exc.message)
    access_store = get_access_store()
    policy_revision = access_store.revision(entity.id)
    previous_bindings = access_store.bindings(entity.id)
    previous_views_revision = access_store.views_revision(entity.id)
    planned = replace(
        version,
        attributes=definition,
        dictionary_snapshots=snapshots,
        reference_snapshots=reference_snapshots,
    )
    head = make_head(
        entity_id=entity.id,
        table_name=entity.table_name,
        version_id=version.id,
        version=planned,
        attributes=tuple(definition),
        physical=physical,
    )
    created = False
    swapped = False
    persisted = False
    view_names: list[str] = []
    unique_added = 0
    indexes_added = 0
    try:
        if previous is None:
            job = get_job_store().get(job_id)
            publisher = job.created_by if job is not None else None
            if isinstance(publisher, str) and publisher:
                grant_id = ensure_creator_grant(entity.id, publisher, definition)
                policy_revision = access_store.revision(entity.id)
                if grant_id is not None:
                    persist_audit_event(
                        actor_user_id=publisher,
                        actor_token_id=None,
                        resource_type="entity_access_grant",
                        resource_id=grant_id,
                        action="create",
                        result="success",
                        detail={
                            "entity_id": entity.id,
                            "policy_revision": policy_revision,
                            "creator_grant": True,
                        },
                    )
        compiled = compile_policy(load_policy(head, policy_revision))
        view_names = [item.view_name for item in compiled.bindings]
        view_statements = profile_view_statements(
            compiled, [item.view_name for item in previous_bindings]
        )
        port = get_entity_table_port()
        append_job_log(
            job_id,
            level="info",
            message=f"creating {schema}.{physical}",
        )
        with port.ddl_transaction():
            port.create_physical_table(schema, physical, definition, comment=comment)
            port.swap_stem_view(
                schema,
                stem,
                physical=physical,
                expected_target=expected_target,
            )
            port.execute_ddl(view_statements)
        created = True
        swapped = True
        unique_added = sum(1 for attr in definition if attr.unique)
        indexes_added = sum(1 for attr in definition if attr_wants_index(attr))
        materialized = [
            {**attribute_to_dict(attr), "attribute_id": attr.attribute_id}
            for attr in definition
        ]
        persist_ready(head, compiled, policy_revision)
        persisted = True
        get_entity_store().save_version(
            replace(
                version,
                attributes=attributes,
                publish_status=PUBLISHED,
                materialized_attributes=materialized,
                dictionary_snapshots=snapshots,
                reference_snapshots=reference_snapshots,
                latest_reconcile_job_id=job_id,
                updated_at=utc_now(),
            )
        )
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, EntityTableNameConflict):
            code = "ENTITY_TABLE_NAME_CONFLICT"
            summary = f"{exc.table} already exists in {schema}"
        else:
            code = "JOB_EXECUTION_FAILED"
            summary = str(exc)
        undo_error = _undo_entity_changes(
            job_id,
            schema=schema,
            stem=stem,
            physical=physical,
            expected_target=expected_target,
            created=created,
            swapped=swapped,
            view_scripts=[(item.view_name, item.sql) for item in previous_bindings],
            view_names=[item.view_name for item in previous_bindings] + view_names,
        )
        if persisted:
            access_store.replace_bindings(entity.id, previous_bindings)
            access_store.set_views_revision(entity.id, previous_views_revision)
        if undo_error is not None:
            summary = f"{summary}; restore view failed: {undo_error}"
        rollback_status(version)
        return _fail(job_id, code, summary)
    result = {
        "schema": "entity_reconcile.v1",
        "entity_version_id": version_id,
        "table_name": physical,
        "action": "created",
        "columns_added": len(definition),
        "nullability_relaxed": 0,
        "types_widened": 0,
        "unique_added": unique_added,
        "unique_dropped": 0,
        "indexes_added": indexes_added,
        "indexes_dropped": 0,
    }
    append_job_log(job_id, level="info", message="publish created")
    mark_succeeded(job_id, result=result)
    return {"status": "succeeded"}


def assign_attribute_ids(
    attributes: list[AttributeRecord],
    previous: EntityVersionRecord | None,
) -> list[AttributeRecord]:
    """Carry each id from the same-named attribute of the latest published version.

    Any other name, including a rename, is a new attribute with a new id.
    """
    carried = {
        attr.name: attr.attribute_id
        for attr in (previous.attributes if previous is not None else [])
        if attr.attribute_id is not None
    }
    return [
        replace(attr, attribute_id=carried.get(attr.name) or new_attribute_id())
        for attr in attributes
    ]


def _prepare(entity_id: str, version_id: str) -> EntityVersionRecord:
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
    accepted = latest_published_of(versions)
    if accepted is None or not _shape_unchanged(
        accepted.attributes, current.attributes, versions=versions
    ):
        _require_writable_shape(
            current.attributes, entity_id=entity.id, previous=current.attributes
        )
    require_attribute_dictionaries(current.attributes, previous=current.attributes)
    if accepted is not None:
        require_business_key_stable(
            get_entity_store(),
            entity.id,
            accepted.attributes,
            current.attributes,
        )
    return current


def _shape_unchanged(
    before: list[AttributeRecord],
    after: list[AttributeRecord],
    *,
    versions: list[EntityVersionRecord],
) -> bool:
    return (
        classify_shapes(before, after, versions=versions).change_class == "unchanged"
    )


def rollback_status(version: EntityVersionRecord) -> None:
    fresh = get_entity_store().get_version(version.id)
    if fresh is None or fresh.publish_status != PUBLISHING:
        return
    get_entity_store().save_version(
        replace(
            fresh,
            publish_status=UNPUBLISHED,
            materialized_attributes=[],
            dictionary_snapshots={},
            reference_snapshots={},
            updated_at=utc_now(),
        )
    )


def _undo_entity_changes(
    job_id: str,
    *,
    schema: str,
    stem: str,
    physical: str,
    expected_target: str | None,
    created: bool,
    swapped: bool,
    view_scripts: list[tuple[str, str]],
    view_names: list[str],
) -> Exception | None:
    if swapped:
        try:
            _restore_stem_view(
                schema=schema,
                stem=stem,
                physical=physical,
                expected_target=expected_target,
            )
        except Exception as exc:  # noqa: BLE001
            return exc
    if created:
        _revert_physical_table(job_id, schema, physical)
        try:
            restore_profile_views(view_scripts, view_names)
        except Exception as exc:  # noqa: BLE001
            return exc
    return None


def _restore_stem_view(
    *,
    schema: str,
    stem: str,
    physical: str,
    expected_target: str | None,
) -> None:
    port = get_entity_table_port()
    if expected_target is None:
        port.drop_stem_view(schema, stem)
    else:
        port.swap_stem_view(
            schema,
            stem,
            physical=expected_target,
            expected_target=physical,
        )


def _revert_physical_table(job_id: str, schema: str, table: str) -> None:
    try:
        get_entity_table_port().revert_physical_table(schema, table)
    except EntityTableHasRows as exc:
        append_job_log(
            job_id,
            level="warn",
            message=f"{exc.table} has rows and was left in place",
        )
        return
    except Exception as exc:  # noqa: BLE001
        append_job_log(
            job_id,
            level="error",
            message=f"revert failed: {exc}",
        )
        return


def _fail(job_id: str, error_code: str, error_summary: str) -> dict[str, str]:
    current = get_job_store().get(job_id)
    if current is not None and current.status in TERMINAL:
        return {"status": current.status}
    append_job_log(
        job_id,
        level="error",
        message=f"failed: {error_code} — {error_summary}",
    )
    mark_failed(job_id, error_code=error_code, error_summary=error_summary)
    return {"status": "failed", "error_code": error_code}
