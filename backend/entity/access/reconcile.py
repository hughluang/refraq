"""Enqueue profile-view rebuilds for Entities whose views lag the policy revision."""

from __future__ import annotations

from backend.entity.access.jobs import enqueue_view_job
from backend.entity.access.plan import load_head
from backend.entity.access.store import get_access_store
from backend.entity.errors import EntityNotFound
from backend.entity.store import get_entity_store

__all__ = ["enqueue_stale_view_jobs"]


def enqueue_stale_view_jobs() -> int:
    """Startup reconciliation. Does not import admin and does not seed grants."""
    queued = 0
    store = get_access_store()
    for entity in get_entity_store().list_all_entities():
        try:
            head = load_head(entity.id)
        except EntityNotFound:
            continue
        if head.physical is None:
            continue
        revision = store.revision(entity.id)
        if revision == 0 and not store.profiles(entity.id):
            continue
        if store.views_revision(entity.id) == revision and store.bindings(entity.id):
            continue
        enqueue_view_job(
            entity.id,
            policy_revision=revision,
            trigger_kind="system",
            trigger_ref=None,
            created_by=None,
            label=entity.table_name,
        )
        queued += 1
    return queued
