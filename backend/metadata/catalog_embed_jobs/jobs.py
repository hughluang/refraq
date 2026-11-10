"""Active-job probe and index cleanup for catalog_embed Jobs."""

from __future__ import annotations

from backend.admin.model_services.records import CatalogIndexView
from backend.jobs.store import TERMINAL, get_job_store
from backend.metadata.catalog.index_state import (
    clear_catalog_index_ready,
    get_catalog_index_store,
    note_catalog_index_failure,
    publish_catalog_index,
)
from backend.metadata.catalog.store import get_catalog_store

CATALOG_EMBED_KIND = "catalog_embed"
_SWEEP_PAGE = 50


def _is_skipped(result: object) -> bool:
    return isinstance(result, dict) and result.get("outcome") == "skipped"


def _latest_sweep():
    """Newest catalog_embed Job that attempted a sweep.

    A succeeded Job with result outcome ``skipped`` did not sweep. Failed and
    cancelled Jobs leave result null and still count.
    """
    offset = 0
    while True:
        records, total = get_job_store().list(
            kind=CATALOG_EMBED_KIND,
            limit=_SWEEP_PAGE,
            offset=offset,
        )
        for record in records:
            if not _is_skipped(record.result):
                return record
        offset += len(records)
        if not records or offset >= total:
            return None
    return None


class CatalogEmbedJobs:
    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str:
        from backend.metadata.catalog_embed_jobs.schedule import (
            run_catalog_embed_schedule_now,
        )

        job = run_catalog_embed_schedule_now(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
        return job.id

    def has_active(self) -> bool:
        records, _ = get_job_store().list(kind=CATALOG_EMBED_KIND)
        return any(record.status not in TERMINAL for record in records)

    def clear_index(self) -> None:
        get_catalog_store().delete_embeddings()

    def latest_sweep_status(self) -> str | None:
        sweep = _latest_sweep()
        if sweep is None:
            return None
        return sweep.status

    def index_view(self) -> CatalogIndexView:
        return get_catalog_index_store().get()

    def publish_index(
        self,
        *,
        generation: int,
        objects_written: int = 0,
        columns_written: int = 0,
        objects_failed: int = 0,
        columns_failed: int = 0,
        objects_attempted: int = 0,
        columns_attempted: int = 0,
        progress: str | None = None,
        failure_summary: str | None = None,
    ) -> None:
        publish_catalog_index(
            generation=generation,
            objects_written=objects_written,
            columns_written=columns_written,
            objects_failed=objects_failed,
            columns_failed=columns_failed,
            objects_attempted=objects_attempted,
            columns_attempted=columns_attempted,
            progress=progress,
            failure_summary=failure_summary,
        )

    def clear_index_ready(self, *, rebuild_owed: bool) -> None:
        clear_catalog_index_ready(rebuild_owed=rebuild_owed)

    def note_index_failure(
        self,
        *,
        failure_summary: str,
        objects_written: int = 0,
        columns_written: int = 0,
        objects_failed: int = 0,
        columns_failed: int = 0,
        objects_attempted: int = 0,
        columns_attempted: int = 0,
        progress: str | None = None,
    ) -> None:
        note_catalog_index_failure(
            failure_summary=failure_summary,
            objects_written=objects_written,
            columns_written=columns_written,
            objects_failed=objects_failed,
            columns_failed=columns_failed,
            objects_attempted=objects_attempted,
            columns_attempted=columns_attempted,
            progress=progress,
        )

    def schedule_view(self):
        from backend.admin.model_services.records import EmbedScheduleView
        from backend.metadata.catalog_embed_jobs.schedule import (
            ensure_catalog_embed_schedule,
        )

        record = ensure_catalog_embed_schedule()
        return EmbedScheduleView(
            id=record.id,
            enabled=record.enabled,
            cron=record.cron,
            interval_seconds=record.interval_seconds,
            next_run_at=record.next_run_at,
        )
