"""Structure snapshot apply: atomic load → plan → persist."""

from __future__ import annotations

from backend.metadata.catalog.records import CatalogObjectRecord


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

    Fail-safe, identity match, FK/index merge, and Join Origin policy live in
    ``structure_merge``; the store adapter only persists the resulting plan
    inside one lock/transaction (load → build plan → apply).
    """
    from backend.metadata.catalog.store import get_catalog_store

    get_catalog_store().apply_structure_plan(
        source_id=source_id,
        job_id=job_id,
        objects=collected,
        schema_scope=schema_scope,
        fail_safe_threshold=fail_safe_threshold,
        engine=engine,
        kind=kind,
        source_key=source_key,
    )
