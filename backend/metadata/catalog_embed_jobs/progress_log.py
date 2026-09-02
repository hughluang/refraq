"""catalog_embed run-log progress and deduplicated embed failures."""

from __future__ import annotations

from backend.jobs.store import append_job_log
from backend.metadata.catalog.index_embeddings import EmbeddingRefreshCounts

PROGRESS_EVERY = 512
LOAD_EVERY = 128
MAX_DISTINCT_REASONS = 8


class CatalogEmbedLog:
    """Job run-log adapter for ``EmbedRefreshProgress``."""

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        self._source_key = ""
        self._emitted_at = 0
        self._logged_first_progress = False
        self._reasons: dict[str, int] = {}
        self._logged_counts: dict[str, int] = {}
        self._omitted = 0
        self._logged_omitted = 0

    def start_source(self, source_key: str) -> None:
        self._source_key = source_key
        self._emitted_at = 0
        self._logged_first_progress = False
        append_job_log(
            self._job_id,
            level="info",
            message=f"indexing {source_key}…",
        )

    def loading(self, *, objects: int, loaded: int) -> None:
        if loaded <= 0:
            append_job_log(
                self._job_id,
                level="info",
                message=f"loading {self._source_key}: {objects} objects…",
            )
            return
        append_job_log(
            self._job_id,
            level="info",
            message=f"loading {self._source_key}: {loaded}/{objects} objects",
        )

    def planned(self, *, objects: int, columns: int) -> None:
        append_job_log(
            self._job_id,
            level="info",
            message=f"indexing {self._source_key}: {objects} objects, {columns} columns",
        )

    def progressed(
        self,
        counts: EmbeddingRefreshCounts,
        *,
        processed: int,
        total: int,
    ) -> None:
        if processed <= 0 or total <= 0:
            return
        is_first = not self._logged_first_progress
        is_last = processed >= total
        crossed = processed // PROGRESS_EVERY > self._emitted_at // PROGRESS_EVERY
        if not (is_first or is_last or crossed):
            return
        written = counts.objects_written + counts.columns_written
        failed = counts.objects_failed + counts.columns_failed
        skipped = counts.objects_skipped + counts.columns_skipped
        append_job_log(
            self._job_id,
            level="info",
            message=(
                f"{self._source_key} {processed}/{total} "
                f"written={written} failed={failed} skipped={skipped}"
            ),
        )
        self._logged_first_progress = True
        self._emitted_at = processed

    def failed(self, *, reason: str, n: int) -> None:
        if reason in self._reasons:
            self._reasons[reason] += n
            return
        if len(self._reasons) >= MAX_DISTINCT_REASONS:
            self._omitted += 1
            return
        self._reasons[reason] = n
        append_job_log(
            self._job_id,
            level="warn",
            message=f"embed failed ×{n}: {reason}",
        )
        self._logged_counts[reason] = n

    def flush_reason_counts(self) -> None:
        for reason, count in self._reasons.items():
            logged = self._logged_counts.get(reason, 0)
            if count > logged:
                append_job_log(
                    self._job_id,
                    level="warn",
                    message=f"embed failed ×{count}: {reason}",
                )
                self._logged_counts[reason] = count
        if self._omitted > self._logged_omitted:
            append_job_log(
                self._job_id,
                level="warn",
                message=f"+{self._omitted} distinct embed errors omitted",
            )
            self._logged_omitted = self._omitted

    def finish_source(self, counts: EmbeddingRefreshCounts) -> None:
        self.flush_reason_counts()
        append_job_log(
            self._job_id,
            level="info",
            message=(
                f"finished {self._source_key}: "
                f"written {counts.objects_written} objects, "
                f"{counts.columns_written} columns "
                f"(failed {counts.objects_failed}/{counts.columns_failed})"
            ),
        )

    def failure_reasons(self) -> list[dict[str, object]]:
        items = [
            {"message": message, "count": count}
            for message, count in self._reasons.items()
        ]
        items.sort(key=lambda item: (-int(item["count"]), str(item["message"])))
        return items

    def dominant_reason(self) -> str | None:
        reasons = self.failure_reasons()
        if not reasons:
            return None
        return str(reasons[0]["message"])

    def dominant_count(self) -> int:
        reasons = self.failure_reasons()
        if not reasons:
            return 0
        return int(reasons[0]["count"])
