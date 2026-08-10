"""Structure snapshot apply: fail-safe gate then persistence replace."""

from __future__ import annotations

from backend.metadata.catalog.identity import _incoming_covers_existing
from backend.metadata.catalog.records import CatalogObjectRecord, CatalogWriteAborted


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

    Fail-safe: if the fraction of currently-present in-scope objects that would
    become absent exceeds the threshold, abort without writes.
    """
    from backend.metadata.catalog.store import get_catalog_store

    store = get_catalog_store()
    present = store.list_present_for_source(source_id)
    in_scope_present = [
        o
        for o in present
        if schema_scope is None or o.schema_name == schema_scope
    ]
    incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in collected}
    would_absent = [
        o
        for o in in_scope_present
        if not _incoming_covers_existing(
            existing_schema=o.schema_name,
            existing_name=o.name,
            existing_type=o.object_type,
            incoming_keys=incoming_keys,
        )
    ]
    if in_scope_present:
        ratio = len(would_absent) / len(in_scope_present)
        if ratio > fail_safe_threshold:
            raise CatalogWriteAborted(
                "JOB_FAIL_SAFE",
                f"Absent ratio {ratio:.2f} exceeds fail-safe threshold "
                f"{fail_safe_threshold:.2f}",
            )
    store.replace_structure_snapshot(
        source_id=source_id,
        job_id=job_id,
        objects=collected,
        schema_scope=schema_scope,
        engine=engine,
        kind=kind,
        source_key=source_key,
    )
