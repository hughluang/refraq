"""Mint, cancel, and index cleanup for catalog_embed Jobs."""

from __future__ import annotations

from backend.core.config import get_settings
from backend.jobs.api import revoke_queued_delivery
from backend.jobs.store import (
    TERMINAL,
    create_queued_job,
    format_job_log_line,
    get_job_store,
    mark_cancelled,
)
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.source_jobs import dispatch_queued_job

CATALOG_EMBED_KIND = "catalog_embed"


class CatalogEmbedJobs:
    def mint(
        self,
        *,
        service_id: str,
        display_name: str,
        generation: int,
        actor_user_id: str,
    ) -> str:
        queued_line = format_job_log_line(
            level="info",
            message=f"queued catalog embed generation {generation}",
        )
        job = create_queued_job(
            kind=CATALOG_EMBED_KIND,
            input={"model_service_id": service_id, "generation": generation},
            created_by=actor_user_id,
            summary=f"catalog_embed · {display_name}",
            trigger_kind="user",
            trigger_ref=actor_user_id,
            log_body=queued_line,
        )
        dispatch_queued_job(job)
        return job.id

    def cancel_active(self) -> None:
        records, _ = get_job_store().list(kind=CATALOG_EMBED_KIND)
        settings = get_settings()
        for record in records:
            if record.status in TERMINAL:
                continue
            updated = mark_cancelled(record.id)
            if updated is not None and updated.status == "cancelled":
                revoke_queued_delivery(record.id, settings=settings)

    def clear_index(self) -> None:
        get_catalog_store().delete_embeddings()

    def latest_status(self) -> str | None:
        records, _ = get_job_store().list(kind=CATALOG_EMBED_KIND, limit=1, offset=0)
        if not records:
            return None
        return records[0].status
