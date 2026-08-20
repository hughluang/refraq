"""Build a join-detection plan from resolved SQL join leaves."""

from __future__ import annotations

from dataclasses import dataclass

from backend.metadata.catalog.join_origin import decide_automatic_insert
from backend.metadata.catalog.records import CatalogJoinRecord
from backend.metadata.join_detection_jobs.resolver import ResolvedJoin


@dataclass(frozen=True)
class JoinDetectionUpsert:
    from_column_id: str
    to_column_id: str
    evidence: str
    join_expression: str
    join_kind: str


@dataclass(frozen=True)
class JoinDetectionPlan:
    upsert_joins: tuple[JoinDetectionUpsert, ...]
    skipped_protected: int
    skipped_rejected: int


def _merge_evidence(hosts: set[str], expression: str) -> str:
    locators = "; ".join(sorted(hosts))
    return f"SQL join in {locators}: {expression}"


def build_join_detection_plan(
    *,
    existing_joins: list[CatalogJoinRecord],
    resolved: list[ResolvedJoin],
) -> JoinDetectionPlan:
    expected: dict[tuple[str, str], JoinDetectionUpsert] = {}
    hosts_by_pair: dict[tuple[str, str], set[str]] = {}
    for edge in resolved:
        pair = (edge.from_column_id, edge.to_column_id)
        hosts_by_pair.setdefault(pair, set()).add(edge.host_locator_key)
        current = expected.get(pair)
        join_kind = edge.join_kind
        expression = edge.join_expression
        if current is not None:
            if current.join_kind == "IMPLICIT" and join_kind != "IMPLICIT":
                join_kind = join_kind
                expression = edge.join_expression
            else:
                join_kind = current.join_kind
                expression = current.join_expression
        expected[pair] = JoinDetectionUpsert(
            from_column_id=edge.from_column_id,
            to_column_id=edge.to_column_id,
            evidence=_merge_evidence(hosts_by_pair[pair], expression),
            join_expression=expression,
            join_kind=join_kind,
        )

    existing_by_pair = {
        (join.from_column_id, join.to_column_id): join for join in existing_joins
    }
    upserts: list[JoinDetectionUpsert] = []
    skipped_protected = 0
    skipped_rejected = 0
    for pair, upsert in expected.items():
        existing = existing_by_pair.get(pair)
        existing_rejected = None if existing is None else existing.is_rejected
        decision = decide_automatic_insert(existing_rejected=existing_rejected)
        if decision == "skip_rejected":
            skipped_rejected += 1
            continue
        if decision == "skip_protected":
            skipped_protected += 1
            continue
        upserts.append(upsert)

    return JoinDetectionPlan(
        upsert_joins=tuple(upserts),
        skipped_protected=skipped_protected,
        skipped_rejected=skipped_rejected,
    )
