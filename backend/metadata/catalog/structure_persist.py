"""Apply a catalog persist plan — adapters only translate records to storage.

Walk order is the rule: objects, then stamps, then insert-if-missing joins.
Join insert admission and persist live in ``join_pair``. Merge and Structure
Diff stay in ``structure_refresh`` (ADR 0020).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.metadata.catalog.join_origin import (
    SQL_LINEAGE_JOIN_ORIGIN,
    STRUCTURE_JOIN_ORIGIN,
)
from backend.metadata.catalog.join_pair import (
    Inserted,
    JoinRowPort,
    apply_insert_join,
)
from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.catalog.structure_merge import StructureJoinUpsert, StructureRefreshPlan
from backend.metadata.join_detection_jobs.reconcile import (
    JoinDetectionPlan,
    JoinDetectionUpsert,
)


class StructureRowPort(JoinRowPort, Protocol):
    def put_object(self, obj: CatalogObjectRecord) -> None: ...

    def stamp_objects(self, plan: StructureRefreshPlan) -> None: ...


def _join_upsert_kwargs(upsert: StructureJoinUpsert | JoinDetectionUpsert) -> dict[str, str | None]:
    return {
        "from_column_id": upsert.from_column_id,
        "to_column_id": upsert.to_column_id,
        "evidence": upsert.evidence,
        "join_kind": upsert.join_kind,
        "join_expression": upsert.join_expression,
    }


def apply_structure_plan(
    port: StructureRowPort, plan: StructureRefreshPlan, *, now: datetime
) -> None:
    for obj in plan.objects:
        port.put_object(obj)
    port.stamp_objects(plan)
    for upsert in plan.upsert_joins:
        apply_insert_join(
            port,
            created_by_user_id=None,
            attester=STRUCTURE_JOIN_ORIGIN,
            now=now,
            **_join_upsert_kwargs(upsert),
        )


def apply_join_detection_plan(
    port: JoinRowPort, plan: JoinDetectionPlan, *, now: datetime
) -> int:
    inserted = 0
    for upsert in plan.upsert_joins:
        result = apply_insert_join(
            port,
            created_by_user_id=None,
            attester=SQL_LINEAGE_JOIN_ORIGIN,
            now=now,
            **_join_upsert_kwargs(upsert),
        )
        if isinstance(result, Inserted):
            inserted += 1
    return inserted
