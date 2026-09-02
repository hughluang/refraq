"""Source structure refresh: load → plan → persist catalog + Structure Diff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.core.time import utc_now
from backend.metadata.catalog.index_embeddings import refresh_source_embeddings
from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog.structure_diff import StructureDiffFacts
from backend.metadata.catalog.structure_merge import build_structure_refresh_plan
from backend.metadata.sources.store import SourceRecord
from backend.metadata.structure_diffs.service import persist_structure_diff
from backend.metadata.structure_diffs.store import get_structure_diff_store


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
    fail_safe_threshold: float,
) -> StructureRefreshCommit:
    """Commit Current catalog and Structure Diff after a complete collect.

    Identity (engine / kind / key) is taken from ``source``; the fail-safe
    threshold is supplied by the caller. Fail-safe, identity match, FK/index
    merge, Join Origin, and Object Semantics survival live in
    ``structure_merge``. This module loads one baseline under a catalog write
    unit, builds the plan, persists the delta and Structure Diff facts from
    that same baseline, then returns the commit outcome.
    """
    try:
        with get_catalog_store().catalog_write(source.id) as write:
            existing_objects, existing_joins = write.load_baseline()
            plan = build_structure_refresh_plan(
                source_id=source.id,
                job_id=job_id,
                existing_objects=existing_objects,
                existing_joins=existing_joins,
                incoming=collected,
                schema_scope=schema_scope,
                fail_safe_threshold=fail_safe_threshold,
                engine=source.engine,
                kind=source.kind,
                source_key=source.key,
                now=utc_now(),
            )
            write.persist_plan(plan)
            record = persist_structure_diff(
                source_id=source.id,
                job_id=job_id,
                diff_class=plan.diff.diff_class,
                counts=plan.diff.counts,
                changes=plan.diff.changes_document(),
                session=write.session,
            )
        commit = StructureRefreshCommit(
            facts=plan.diff, structure_diff_id=record.id
        )
        refresh_source_embeddings(source.id)
        return commit
    except Exception:
        # Memory Diff store is a separate dict; undo any Diff that landed for
        # this Job when the write unit rolls back catalog. SQL Diff rows share
        # the write session and are already rolled back.
        get_structure_diff_store().delete_for_job(job_id)
        raise
