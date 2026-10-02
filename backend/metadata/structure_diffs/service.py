"""Structure Diff use-case helpers."""

from __future__ import annotations

from backend.metadata.errors import SourceNotFound, StructureDiffNotFound
from backend.metadata.sources.store import get_source_store
from backend.metadata.structure_diffs.store import (
    StructureDiffRecord,
    get_structure_diff_store,
)


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
]
