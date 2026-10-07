"""Enqueue profile-view rebuilds for Entities whose views lag the policy revision."""

from __future__ import annotations

import logging

from backend.entity.access.jobs import enqueue_view_job
from backend.entity.access.plan import load_head
from backend.entity.access.store import get_access_store
from backend.entity.errors import EntityNotFound
from backend.entity.records import BusinessEntityRecord
from backend.entity.store import get_entity_store

__all__ = ["enqueue_stale_view_jobs"]

logger = logging.getLogger(__name__)


def enqueue_stale_view_jobs() -> int:
    """Startup reconciliation. One Entity failing never stops the others."""
    queued = 0
    failed = 0
    for entity in get_entity_store().list_all_entities():
        try:
            queued += _reconcile_one(entity)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.exception(
                "entity access view reconciliation failed for %s", entity.id
            )
    if failed:
        logger.error("entity access view reconciliation skipped %d entities", failed)
    return queued


def _reconcile_one(entity: BusinessEntityRecord) -> int:
    store = get_access_store()
    try:
        head = load_head(entity.id)
    except EntityNotFound:
        return 0
    if head.physical is None:
        return 0
    revision = store.revision(entity.id)
    if revision == 0 and not store.profiles(entity.id):
        return 0
    if store.views_revision(entity.id) == revision and store.bindings(entity.id):
        return 0
    enqueue_view_job(
        entity.id,
        policy_revision=revision,
        trigger_kind="system",
        trigger_ref=None,
        created_by=None,
        label=entity.table_name,
    )
    return 1
