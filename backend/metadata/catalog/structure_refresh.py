"""Source structure refresh: load → plan → persist (deep module)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from backend.metadata.catalog.records import CatalogJoinRecord, CatalogObjectRecord
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.catalog.structure_merge import (
    StructureRefreshPlan,
    build_structure_refresh_plan,
)


def bind_structure_refresh_plan(
    *,
    source_id: str,
    job_id: str,
    collected: list[CatalogObjectRecord],
    schema_scope: str | None,
    fail_safe_threshold: float,
    engine: str | None,
    kind: str,
    source_key: str,
) -> Callable[
    [list[CatalogObjectRecord], list[CatalogJoinRecord], datetime],
    StructureRefreshPlan,
]:
    """Bind collect-time inputs into the store ``build_plan`` callback."""

    def build_plan(
        existing_objects: list[CatalogObjectRecord],
        existing_joins: list[CatalogJoinRecord],
        now: datetime,
    ) -> StructureRefreshPlan:
        return build_structure_refresh_plan(
            source_id=source_id,
            job_id=job_id,
            existing_objects=existing_objects,
            existing_joins=existing_joins,
            incoming=collected,
            schema_scope=schema_scope,
            fail_safe_threshold=fail_safe_threshold,
            engine=engine,
            kind=kind,
            source_key=source_key,
            now=now,
        )

    return build_plan


def apply_structure_snapshot(
    *,
    source_id: str,
    job_id: str,
    collected: list[CatalogObjectRecord],
    schema_scope: str | None,
    fail_safe_threshold: float,
    engine: str | None,
    kind: str,
    source_key: str,
) -> None:
    """Commit structure upsert/absent only after a complete successful collect.

    Fail-safe, identity match, FK/index merge, Join Origin, and Object Semantics
    survival live in ``structure_merge``; the store adapter only loads inputs and
    persists the resulting ``StructureRefreshPlan`` inside one lock/transaction.
    """
    get_catalog_store().run_structure_refresh(
        source_id,
        bind_structure_refresh_plan(
            source_id=source_id,
            job_id=job_id,
            collected=collected,
            schema_scope=schema_scope,
            fail_safe_threshold=fail_safe_threshold,
            engine=engine,
            kind=kind,
            source_key=source_key,
        ),
    )
