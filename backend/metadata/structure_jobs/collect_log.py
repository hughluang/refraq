"""Structure collect run-log progress (schema-scoped fetch phases)."""

from __future__ import annotations

from backend.jobs.store import append_job_log

FETCH_PART_LABELS: dict[str, str] = {
    "columns": "columns",
    "primary_keys": "primary key columns",
    "foreign_keys": "foreign key columns",
    "indexes": "index columns",
    "definitions": "view definitions",
}


class StructureCollectLog:
    """Job run-log adapter for ``CollectProgress``."""

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id

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

    def fetched(self, part: str, rows: int) -> None:
        label = FETCH_PART_LABELS.get(part, part)
        append_job_log(
            self._job_id,
            level="info",
            message=f"read {rows} {label}",
        )

    def assembled(self, total: int) -> None:
        append_job_log(
            self._job_id,
            level="info",
            message=f"assembled {total} objects",
        )
