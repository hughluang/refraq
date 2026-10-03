"""Source structure refresh: one write unit for catalog and Structure Diff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.time import utc_now
from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog.structure_diff import StructureDiffFacts
from backend.metadata.catalog.structure_merge import build_structure_refresh_plan
from backend.metadata.sources.store import SourceRecord
from backend.metadata.structure_diffs.store import (
    StructureDiffRecord,
    new_structure_diff_id,
)


@dataclass(frozen=True)
class StructureRefreshCommit:
    """Current catalog and Structure Diff committed for one successful refresh."""

    facts: StructureDiffFacts
    structure_diff_id: str

    def result_envelope(self) -> dict[str, Any]:
        return self.facts.result_envelope(self.structure_diff_id)


def apply_structure_snapshot(
    *,
    source: SourceRecord,
    job_id: str,
    collected: list[CatalogObjectRecord],
    schema_scope: str | None,
) -> StructureRefreshCommit:
    """Commit Current catalog and Structure Diff after a complete collect.

    Identity (engine / kind / key) is taken from ``source``. Identity match,
    FK/index merge, Join Origin, and Object Semantics survival live in
    ``structure_merge``. This module loads one baseline under a catalog write
    unit, builds the plan, and persists the delta and Structure Diff in that
    same unit. Catalog embeddings are refreshed by the site catalog_embed Job.
    """
    with get_catalog_store().catalog_write(source.id) as write:
        existing_objects, existing_joins = write.load_baseline()
        plan = build_structure_refresh_plan(
            source_id=source.id,
            job_id=job_id,
            existing_objects=existing_objects,
            existing_joins=existing_joins,
            incoming=collected,
            schema_scope=schema_scope,
            engine=source.engine,
            kind=source.kind,
            source_key=source.key,
            now=utc_now(),
        )
        write.persist_plan(plan)
        record = StructureDiffRecord(
            id=new_structure_diff_id(),
            source_id=source.id,
            job_id=job_id,
            diff_class=plan.diff.diff_class,
            counts=dict(plan.diff.counts),
            changes=plan.diff.changes_document(),
            created_at=utc_now(),
        )
        write.persist_structure_diff(record)
    return StructureRefreshCommit(
        facts=plan.diff, structure_diff_id=record.id
    )
