"""Structure Diff use-case helpers."""

from __future__ import annotations

from typing import Any

from backend.core.time import utc_now
from backend.metadata.errors import SourceNotFound, StructureDiffNotFound
from backend.metadata.sources.store import get_source_store
from backend.metadata.structure_diffs.store import (
    StructureDiffRecord,
    get_structure_diff_store,
    new_structure_diff_id,
)


def persist_structure_diff(
    *,
    source_id: str,
    job_id: str,
    diff_class: str,
    counts: dict[str, int],
    changes: list[dict[str, Any]],
) -> StructureDiffRecord:
    record = StructureDiffRecord(
        id=new_structure_diff_id(),
        source_id=source_id,
        job_id=job_id,
        diff_class=diff_class,
        counts=dict(counts),
        changes=list(changes),
        created_at=utc_now(),
    )
    return get_structure_diff_store().create(record)


def list_structure_diffs(
    source_id: str, *, limit: int = 50, offset: int = 0
) -> tuple[list[StructureDiffRecord], int]:
    if get_source_store().get_source(source_id) is None:
        raise SourceNotFound()
    return get_structure_diff_store().list_for_source(
        source_id, limit=limit, offset=offset
    )


def get_structure_diff(diff_id: str) -> StructureDiffRecord:
    record = get_structure_diff_store().get(diff_id)
    if record is None:
        raise StructureDiffNotFound()
    return record


__all__ = [
    "get_structure_diff",
    "list_structure_diffs",
    "persist_structure_diff",
]
