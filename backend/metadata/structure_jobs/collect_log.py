"""Structure collect run-log progress (phase lines + throttled object counts)."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.core.time import utc_now
from backend.jobs.store import append_job_log

OBJECT_PROGRESS_EVERY = 25
OBJECT_PROGRESS_INTERVAL = timedelta(seconds=10)


class StructureCollectLog:
    """Job run-log adapter for ``CollectProgress``.

    After ``listed N`` (N>0) writes ``objects 0/N``. Later ``objects {done}/{total}``
    lines fire every ``OBJECT_PROGRESS_EVERY`` objects, every
    ``OBJECT_PROGRESS_INTERVAL``, and always at ``N/N`` without duplicating the
    last line.
    """

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        self._last_logged_done: int | None = None
        self._last_logged_at: datetime | None = None

    def listing_objects(self, schema: str) -> None:
        append_job_log(
            self._job_id,
            level="info",
            message=f"listing objects in {schema}…",
        )

    def listed_objects(self, total: int) -> None:
        append_job_log(
            self._job_id,
            level="info",
            message=f"listed {total} objects",
        )
        if total > 0:
            self._emit_objects(0, total)

    def object_done(self, done: int, total: int) -> None:
        if self._should_emit(done, total):
            self._emit_objects(done, total)

    def _should_emit(self, done: int, total: int) -> bool:
        if done == self._last_logged_done:
            return False
        if done == total:
            return True
        if done > 0 and done % OBJECT_PROGRESS_EVERY == 0:
            return True
        if self._last_logged_at is None:
            return True
        return utc_now() - self._last_logged_at >= OBJECT_PROGRESS_INTERVAL

    def _emit_objects(self, done: int, total: int) -> None:
        append_job_log(
            self._job_id,
            level="info",
            message=f"objects {done}/{total}",
        )
        self._last_logged_done = done
        self._last_logged_at = utc_now()
