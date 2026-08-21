"""Apply a catalog persist plan — adapters only translate records to storage.

Walk order is the rule: objects, then stamps, then insert-if-missing joins.
Merge and Structure Diff stay in ``structure_refresh`` (ADR 0020).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.metadata.catalog.join_changes import (
    CatalogJoinChangeRecord,
    join_change_for_create,
)
from backend.metadata.catalog.join_origin import (
    SQL_LINEAGE_JOIN_ORIGIN,
    STRUCTURE_JOIN_ORIGIN,
)
from backend.metadata.catalog.records import CatalogJoinRecord, CatalogObjectRecord, new_join_id
from backend.metadata.catalog.structure_merge import StructureJoinUpsert, StructureRefreshPlan
from backend.metadata.join_detection_jobs.reconcile import (
    JoinDetectionPlan,
    JoinDetectionUpsert,
)


class JoinRowPort(Protocol):
    def get_join_by_pair(
        self, from_column_id: str, to_column_id: str
    ) -> CatalogJoinRecord | None: ...

    def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
        """Persist ``record``. Return None when the directed pair already exists."""

    def append_join_change(self, change: CatalogJoinChangeRecord) -> None: ...


class StructureRowPort(JoinRowPort, Protocol):
    def put_object(self, obj: CatalogObjectRecord) -> None: ...

    def stamp_objects(self, plan: StructureRefreshPlan) -> None: ...


def apply_upsert_join(
    port: JoinRowPort,
    *,
    from_column_id: str,
    to_column_id: str,
    evidence: str,
    created_by_user_id: str | None,
    join_kind: str,
    join_expression: str | None,
    attester: str,
    now: datetime,
) -> CatalogJoinRecord:
    existing = port.get_join_by_pair(from_column_id, to_column_id)
    if existing is not None:
        return existing
    record = CatalogJoinRecord(
        id=new_join_id(),
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=evidence,
        join_kind=join_kind,
        join_expression=join_expression,
        created_by_user_id=created_by_user_id,
        created_at=now,
    )
    inserted = port.insert_join(record)
    if inserted is None:
        raced = port.get_join_by_pair(from_column_id, to_column_id)
        if raced is None:
            raise RuntimeError("join pair conflict without an existing row")
        return raced
    port.append_join_change(
        join_change_for_create(
            from_column_id=from_column_id,
            to_column_id=to_column_id,
            created_at=now,
            attester=attester,
            actor_user_id=created_by_user_id,
        )
    )
    return inserted


def apply_insert_join_if_missing(
    port: JoinRowPort,
    *,
    from_column_id: str,
    to_column_id: str,
    evidence: str,
    join_kind: str,
    join_expression: str | None,
    attester: str,
    now: datetime,
) -> bool:
    if port.get_join_by_pair(from_column_id, to_column_id) is not None:
        return False
    record = CatalogJoinRecord(
        id=new_join_id(),
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=evidence,
        join_kind=join_kind,
        join_expression=join_expression,
        created_by_user_id=None,
        created_at=now,
    )
    inserted = port.insert_join(record)
    if inserted is None:
        return False
    port.append_join_change(
        join_change_for_create(
            from_column_id=from_column_id,
            to_column_id=to_column_id,
            created_at=now,
            attester=attester,
        )
    )
    return True


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
        apply_insert_join_if_missing(
            port,
            attester=STRUCTURE_JOIN_ORIGIN,
            now=now,
            **_join_upsert_kwargs(upsert),
        )


def apply_join_detection_plan(
    port: JoinRowPort, plan: JoinDetectionPlan, *, now: datetime
) -> int:
    inserted = 0
    for upsert in plan.upsert_joins:
        if apply_insert_join_if_missing(
            port,
            attester=SQL_LINEAGE_JOIN_ORIGIN,
            now=now,
            **_join_upsert_kwargs(upsert),
        ):
            inserted += 1
    return inserted
