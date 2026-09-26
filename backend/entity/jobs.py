"""Mint entity_reconcile (publish) and entity_table_drop Jobs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.entity.errors import EntityVersionNotSuperseded
from backend.entity.kinds import ENTITY_TABLE_KINDS, KIND_DROP, KIND_RECONCILE
from backend.entity.lifecycle import PUBLISHING, is_deprecated
from backend.entity.present import (
    current_version_of,
    latest_published_of,
    occupies_live_table,
    physical_table_name,
    table_present,
    version_out,
)
from backend.entity.service import prepare_publish, require_entity, require_version
from backend.entity.store import get_entity_store
from backend.entity.tasks import run_job
from backend.jobs.store import (
    JobRecord,
    create_queued_job,
    format_job_log_line,
    get_job_store,
    set_celery_task_id,
)

IN_FLIGHT = frozenset({"queued", "running"})

__all__ = [
    "EnqueueResult",
    "dispatch_entity_job",
    "enqueue_drop",
    "enqueue_publish",
    "find_inflight_entity_table_job",
]


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job: JobRecord | None
    version: dict[str, Any] | None
    minted: bool


def find_inflight_entity_table_job(entity_version_id: str) -> JobRecord | None:
    store = get_job_store()
    for kind in ENTITY_TABLE_KINDS:
        records, _ = store.list(kind=kind)
        for record in records:
            if record.status not in IN_FLIGHT:
                continue
            if record.input.get("entity_version_id") == entity_version_id:
                return record
    return None


def enqueue_publish(
    *,
    entity_id: str,
    version_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[JobRecord, bool]:
    entity = require_entity(entity_id)
    version = prepare_publish(entity_id, version_id)
    inflight = find_inflight_entity_table_job(version.id)
    if inflight is not None:
        return inflight, False
    job = create_queued_job(
        kind=KIND_RECONCILE,
        input={"entity_version_id": version.id},
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
    dispatch_entity_job(job)
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


def enqueue_drop(
    *,
    entity_id: str,
    version_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> EnqueueResult:
    entity = require_entity(entity_id)
    version = require_version(entity_id, version_id)
    versions = get_entity_store().list_all_versions(entity_id)
    current = current_version_of(versions)
    current_n = current.version if current is not None else version.version
    latest = latest_published_of(versions)
    if occupies_live_table(version, latest) and not is_deprecated(entity):
        raise EntityVersionNotSuperseded()
    presented = version_out(
        version,
        entity=entity,
        current_version_number=current_n,
        include_attributes=True,
        latest_published=latest,
    )
    if not table_present(version):
        return EnqueueResult(job=None, version=presented, minted=False)
    inflight = find_inflight_entity_table_job(version.id)
    if inflight is not None:
        return EnqueueResult(job=inflight, version=None, minted=False)
    physical = physical_table_name(
        stem=entity.table_name,
        version=version,
        latest_published=latest,
    )
    job = create_queued_job(
        kind=KIND_DROP,
        input={"entity_version_id": version.id},
        created_by=actor_user_id,
        summary=f"entity_table_drop · {physical or entity.table_name}",
        trigger_kind="user",
        trigger_ref=actor_user_id,
        log_body=format_job_log_line(level="info", message="queued entity table drop"),
    )
    dispatch_entity_job(job)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="entity",
        resource_id=entity.id,
        action="entity.drop_table_enqueue",
        result="success",
        detail={"job_id": job.id, "version_id": version.id},
    )
    return EnqueueResult(job=job, version=None, minted=True)


def dispatch_entity_job(job: JobRecord) -> str:
    async_result = run_job.apply_async(args=[job.id], task_id=job.id)
    set_celery_task_id(job.id, async_result.id)
    return async_result.id
