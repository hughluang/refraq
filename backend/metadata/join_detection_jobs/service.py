"""Join-detection Job orchestration."""

from __future__ import annotations

from collections import Counter

from backend.jobs.store import append_job_log, mark_succeeded
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.join_detection_jobs.parser import parse_definition_joins
from backend.metadata.join_detection_jobs.reconcile import build_join_detection_plan
from backend.metadata.join_detection_jobs.resolver import (
    PARSEABLE_OBJECT_TYPES,
    CatalogJoinResolver,
    UnresolvedReason,
)
from backend.metadata.source_job_runner import (
    fail_job,
    run_source_work_job,
    stopped_result,
)
from backend.metadata.sources.access import (
    decrypt_access_blob,
    endpoint_from_access,
)
from backend.metadata.sources.store import SourceRecord


def _parse_failure_types(*, tokenize_errors: int, parse_errors: int) -> str:
    parts: list[str] = []
    if tokenize_errors:
        parts.append(f"cannot tokenize ×{tokenize_errors}")
    if parse_errors:
        parts.append(f"cannot parse ×{parse_errors}")
    return ", ".join(parts)


def _source_database_name(source: SourceRecord) -> str | None:
    """Source catalog/database name for same-catalog defense.

    Returns None when the Source has no access blob or the assembled endpoint
    has no database name. Decrypt and assembly errors propagate so the Job does
    not fail-open catalog-qualified leaves as same-Source edges.
    """
    if not source.engine or not source.access_ciphertext:
        return None
    access = decrypt_access_blob(source.access_ciphertext)
    endpoint = endpoint_from_access(engine=source.engine, access=access)
    name = (endpoint.database_name or "").strip()
    return name or None


def run_join_detection_job(job_id: str) -> dict[str, str]:
    return run_source_work_job(
        job_id,
        kind="join_detection",
        start_message="join detection job started",
        body=_detect_joins,
    )


def _detect_joins(job_id: str, source: SourceRecord) -> dict[str, str]:
    source_id = source.id

    if not source.engine:
        return fail_job(
            job_id,
            error_code="JOB_INPUT_INVALID",
            error_summary="Source has no engine",
        )

    stopped = stopped_result(job_id)
    if stopped is not None:
        return stopped

    try:
        source_database = _source_database_name(source)
    except Exception as exc:  # noqa: BLE001 — unusable secret; do not fail-open
        return fail_job(
            job_id,
            error_code="JOB_SECRET_MISSING",
            error_summary=f"Access decrypt failed: {exc}",
        )

    store = get_catalog_store()
    objects = store.list_present_for_source(source_id)
    resolver = CatalogJoinResolver(objects, source_database=source_database)
    default_schema = objects[0].schema_name if objects else None
    resolved = []
    objects_eligible = 0
    objects_parsed = 0
    objects_parse_failed = 0
    unresolved_counts: Counter[str] = Counter()
    for obj in objects:
        if obj.object_type not in PARSEABLE_OBJECT_TYPES:
            continue
        ddl = (obj.ddl or "").strip()
        if not ddl:
            continue
        objects_eligible += 1
        parsed = parse_definition_joins(
            ddl, engine=source.engine, default_schema=obj.schema_name or default_schema
        )
        leaves = parsed.leaves
        if parsed.fragment_errors:
            objects_parse_failed += 1
            types = _parse_failure_types(
                tokenize_errors=parsed.tokenize_errors,
                parse_errors=parsed.parse_errors,
            )
            append_job_log(
                job_id,
                level="warn",
                message=f"parse failed for {obj.locator_key}: {types}",
            )
        if parsed.fragment_errors and not leaves and not parsed.alias_unresolved:
            continue
        objects_parsed += 1
        unresolved_counts[UnresolvedReason.ALIAS_UNRESOLVED] += parsed.alias_unresolved
        object_unresolved = parsed.alias_unresolved
        for leaf in leaves:
            outcome = resolver.resolve_leaf(leaf, host_locator_key=obj.locator_key)
            if outcome.join is not None:
                resolved.append(outcome.join)
                continue
            if outcome.reason is None:
                continue
            unresolved_counts[outcome.reason] += 1
            object_unresolved += 1
        if object_unresolved:
            append_job_log(
                job_id,
                level="warn",
                message=(
                    f"unresolved join endpoints for {obj.locator_key} "
                    f"({object_unresolved} leaf(s))"
                ),
            )

    stopped = stopped_result(job_id)
    if stopped is not None:
        return stopped

    try:
        with store.catalog_write(source_id) as write:
            _existing_objects, existing_joins = write.load_baseline()
            plan = build_join_detection_plan(
                existing_joins=existing_joins,
                resolved=resolved,
            )
            joins_upserted = write.persist_join_detection_plan(plan)
    except Exception as exc:  # noqa: BLE001
        stopped = stopped_result(job_id)
        if stopped is not None:
            return stopped
        return fail_job(
            job_id,
            error_code="JOB_EXECUTION_FAILED",
            error_summary=str(exc),
        )

    unresolved_total = sum(unresolved_counts.values())
    result = {
        "schema": "join_detection.v1",
        "objects_eligible": objects_eligible,
        "objects_parsed": objects_parsed,
        "objects_parse_failed": objects_parse_failed,
        "joins_upserted": joins_upserted,
        "joins_deleted_stale": 0,
        "joins_skipped_unresolved": unresolved_total,
        "joins_skipped_unresolved_alias": unresolved_counts[
            UnresolvedReason.ALIAS_UNRESOLVED
        ],
        "joins_skipped_unresolved_external": unresolved_counts[
            UnresolvedReason.EXTERNAL_CATALOG
        ],
        "joins_skipped_unresolved_object": unresolved_counts[
            UnresolvedReason.OBJECT_NOT_IN_CATALOG
        ],
        "joins_skipped_unresolved_column": unresolved_counts[
            UnresolvedReason.COLUMN_NOT_IN_OBJECT
        ],
        "joins_skipped_protected": plan.skipped_protected,
        "joins_skipped_rejected": plan.skipped_rejected,
    }
    append_job_log(
        job_id,
        level="info",
        message=(
            "succeeded "
            f"eligible={result['objects_eligible']} "
            f"parsed={result['objects_parsed']} "
            f"parse_failed={result['objects_parse_failed']} "
            f"upserted={result['joins_upserted']} "
            f"unresolved={unresolved_total} "
            f"alias={result['joins_skipped_unresolved_alias']} "
            f"external={result['joins_skipped_unresolved_external']} "
            f"object={result['joins_skipped_unresolved_object']} "
            f"column={result['joins_skipped_unresolved_column']}"
        ),
    )
    final = mark_succeeded(job_id, result=result)
    if final is None:
        return {"status": "missing"}
    return {"status": final.status}


