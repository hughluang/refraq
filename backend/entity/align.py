"""Align and drop Entity Tables against a version definition."""

from __future__ import annotations

from dataclasses import replace

from celery import current_task

from backend.core.time import utc_now
from backend.entity.ddl import attr_wants_index
from backend.entity.entity_db import entity_db_schema
from backend.entity.errors import EntityTableInService
from backend.entity.kinds import KIND_DROP, KIND_RECONCILE
from backend.entity.lifecycle import PUBLISHED, PUBLISHING, UNPUBLISHED, is_deprecated
from backend.entity.locks import try_acquire_entity_table_lock
from backend.entity.present import (
    compose_physical_table_name,
    latest_published_of,
    occupies_live_table,
    physical_table_name,
    table_present,
)
from backend.entity.records import attribute_to_dict
from backend.entity.store import get_entity_store
from backend.entity.table_port import (
    EntityTableHasRows,
    EntityTableNameConflict,
    get_entity_table_port,
)
from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_queued,
    get_job_store,
    mark_failed,
    mark_succeeded,
    occupancy_worker_id,
)


def run_entity_table_job(job_id: str) -> dict[str, str]:
    current = claim_queued(
        job_id, celery_task_id=job_id, claimed_by=_claim_worker_id()
    )
    if current is None:
        existing = get_job_store().get(job_id)
        if existing is None:
            return {"status": "missing"}
        return {"status": existing.status}
    version_id = current.input.get("entity_version_id")
    if not isinstance(version_id, str):
        return _fail(job_id, "JOB_INPUT_INVALID", "entity_version_id is required")
    version = get_entity_store().get_version(version_id)
    if version is None:
        return _fail(job_id, "ENTITY_VERSION_NOT_FOUND", "Entity Version not found")
    entity = get_entity_store().get_entity(version.entity_id)
    if entity is None:
        return _fail(job_id, "ENTITY_NOT_FOUND", "Business Entity not found")
    lock = try_acquire_entity_table_lock(entity.id)
    if lock is None:
        if current.kind == KIND_RECONCILE:
            _rollback_publish(version, accept_published=False)
        return _fail(
            job_id,
            "JOB_ALREADY_ACTIVE",
            f"entity table lock held for {entity.id}",
        )
    try:
        if current.kind == KIND_RECONCILE:
            return _reconcile(job_id, version_id)
        if current.kind == KIND_DROP:
            return _drop(job_id, version_id)
        return _fail(job_id, "JOB_INPUT_INVALID", f"No handler for job kind: {current.kind}")
    finally:
        lock.release()


def _reconcile(job_id: str, version_id: str) -> dict[str, str]:
    version = get_entity_store().get_version(version_id)
    if version is None:
        return _fail(job_id, "ENTITY_VERSION_NOT_FOUND", "Entity Version not found")
    entity = get_entity_store().get_entity(version.entity_id)
    if entity is None:
        return _fail(job_id, "ENTITY_NOT_FOUND", "Business Entity not found")
    schema = entity_db_schema()
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
    definition = list(version.attributes)
    created = False
    published_saved = False
    try:
        port = get_entity_table_port()
        append_job_log(
            job_id,
            level="info",
            message=f"creating {schema}.{physical}",
        )
        port.create_physical_table(schema, physical, definition, comment=comment)
        created = True
        unique_added = sum(1 for attr in definition if attr.unique)
        indexes_added = sum(1 for attr in definition if attr_wants_index(attr))
        get_entity_store().save_version(
            replace(
                version,
                publish_status=PUBLISHED,
                materialized_attributes=[
                    attribute_to_dict(attr) for attr in definition
                ],
                latest_reconcile_job_id=job_id,
                updated_at=utc_now(),
            )
        )
        published_saved = True
        port.swap_stem_view(
            schema,
            stem,
            physical=physical,
            expected_target=expected_target,
        )
    except EntityTableNameConflict as exc:
        if created:
            _revert_physical_table(job_id, schema, physical)
        _rollback_publish(version, accept_published=published_saved)
        return _fail(
            job_id,
            "ENTITY_TABLE_NAME_CONFLICT",
            f"{exc.table} already exists in {schema}",
        )
    except Exception as exc:  # noqa: BLE001
        if created:
            _revert_physical_table(job_id, schema, physical)
        _rollback_publish(version, accept_published=published_saved)
        return _fail(job_id, "JOB_EXECUTION_FAILED", str(exc))
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


def _rollback_publish(version, *, accept_published: bool) -> None:
    fresh = get_entity_store().get_version(version.id)
    if fresh is None:
        return
    allowed = (PUBLISHING, PUBLISHED) if accept_published else (PUBLISHING,)
    if fresh.publish_status not in allowed:
        return
    get_entity_store().save_version(
        replace(
            fresh,
            publish_status=UNPUBLISHED,
            materialized_attributes=[],
            updated_at=utc_now(),
        )
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


def _drop(job_id: str, version_id: str) -> dict[str, str]:
    version = get_entity_store().get_version(version_id)
    if version is None:
        return _fail(job_id, "ENTITY_VERSION_NOT_FOUND", "Entity Version not found")
    entity = get_entity_store().get_entity(version.entity_id)
    if entity is None:
        return _fail(job_id, "ENTITY_NOT_FOUND", "Business Entity not found")
    versions = get_entity_store().list_all_versions(entity.id)
    latest = latest_published_of(versions)
    is_head = occupies_live_table(version, latest)
    if is_head and not is_deprecated(entity):
        refusal = EntityTableInService()
        return _fail(job_id, refusal.code, refusal.message)
    schema = entity_db_schema()
    table = physical_table_name(version, entity.table_name)
    if table is None:
        mark_succeeded(
            job_id,
            result={
                "schema": "entity_table_drop.v1",
                "entity_version_id": version_id,
                "table_name": None,
            },
        )
        return {"status": "succeeded"}
    try:
        port = get_entity_table_port()
        if is_head:
            port.drop_head(schema, table, entity.table_name)
        elif port.table_exists(schema, table):
            port.drop_table(schema, table)
    except EntityTableHasRows as exc:
        return _fail(job_id, "ENTITY_TABLE_NOT_EMPTY", f"{exc.table} is not empty")
    except Exception as exc:  # noqa: BLE001
        return _fail(job_id, "JOB_EXECUTION_FAILED", str(exc))
    get_entity_store().save_version(
        replace(
            version,
            materialized_attributes=[],
            updated_at=utc_now(),
        )
    )
    append_job_log(job_id, level="info", message=f"dropped {schema}.{table}")
    mark_succeeded(
        job_id,
        result={
            "schema": "entity_table_drop.v1",
            "entity_version_id": version_id,
            "table_name": table,
        },
    )
    return {"status": "succeeded"}


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


def _claim_worker_id() -> str:
    try:
        request = getattr(current_task, "request", None)
        hostname = getattr(request, "hostname", None) if request is not None else None
        return occupancy_worker_id(hostname if hostname else None)
    except Exception:  # noqa: BLE001
        return occupancy_worker_id(None)
