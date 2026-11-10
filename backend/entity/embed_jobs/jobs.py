"""Active-job probe and index cleanup for entity_embed Jobs."""

from __future__ import annotations

from backend.admin.model_services.records import EmbedScheduleView, EntityIndexView
from backend.entity.embed_jobs.index_state import (
    clear_entity_index_ready,
    get_entity_index_store,
)
from backend.entity.embed_jobs.schedule import (
    ENTITY_EMBED_SCHEDULE_KEY,
    ensure_entity_embed_schedule,
    run_entity_embed_schedule_now,
)
from backend.entity.kinds import KIND_EMBED
from backend.entity.projection import clear_entity_projections
from backend.jobs.store import TERMINAL, get_job_store

_SWEEP_PAGE = 50


def _is_skipped(result: object) -> bool:
    return isinstance(result, dict) and result.get("outcome") == "skipped"


def _latest_sweep():
    offset = 0
    while True:
        records, total = get_job_store().list(
            kind=KIND_EMBED,
            limit=_SWEEP_PAGE,
            offset=offset,
        )
        for record in records:
            if not _is_skipped(record.result):
                return record
        offset += len(records)
        if not records or offset >= total:
            return None


class EntityEmbedJobs:
    def owns_schedule(self, key: str) -> bool:
        return key == ENTITY_EMBED_SCHEDULE_KEY

    def trigger_run(
        self, *, actor_user_id: str, actor_token_id: str | None
    ) -> str:
        job = run_entity_embed_schedule_now(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
        return job.id

    def has_active(self) -> bool:
        records, _ = get_job_store().list(kind=KIND_EMBED)
        return any(record.status not in TERMINAL for record in records)

    def clear_index(self) -> None:
        clear_entity_projections()

    def latest_sweep_status(self) -> str | None:
        sweep = _latest_sweep()
        if sweep is None:
            return None
        return sweep.status

    def index_view(self) -> EntityIndexView:
        return get_entity_index_store().get()

    def clear_index_ready(self, *, rebuild_owed: bool) -> None:
        clear_entity_index_ready(rebuild_owed=rebuild_owed)

    def schedule_view(self) -> EmbedScheduleView:
        record = ensure_entity_embed_schedule()
        return EmbedScheduleView(
            id=record.id,
            enabled=record.enabled,
            cron=record.cron,
            interval_seconds=record.interval_seconds,
            next_run_at=record.next_run_at,
        )
