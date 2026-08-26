"""Directed join-pair admission and insert-if-missing persist.

Pair state is whether the directed column pair has a row and whether that row
is a Join Rejection. Writers only map that fact to an action; HTTP/MCP error
codes stay in adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from backend.metadata.catalog.join_changes import (
    CatalogJoinChangeRecord,
    join_change_for_create,
)
from backend.metadata.catalog.records import CatalogJoinRecord, new_join_id

PairState = Literal["absent", "asserted", "rejected"]
PairWriter = Literal["automatic", "human_single", "human_batch"]
PairWriteAction = Literal[
    "insert",
    "skip_protected",
    "skip_rejected",
    "refuse_defined",
    "refuse_rejected",
]


@dataclass(frozen=True)
class PairWriteDecision:
    action: PairWriteAction
    existing_id: str | None = None


@dataclass(frozen=True)
class Inserted:
    record: CatalogJoinRecord


@dataclass(frozen=True)
class Occupied:
    record: CatalogJoinRecord


class JoinRowPort(Protocol):
    def get_join_by_pair(
        self, from_column_id: str, to_column_id: str
    ) -> CatalogJoinRecord | None: ...

    def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
        """Persist ``record``. Return None when the directed pair already exists."""

    def append_join_change(self, change: CatalogJoinChangeRecord) -> None: ...


def pair_state(existing: CatalogJoinRecord | None) -> PairState:
    if existing is None:
        return "absent"
    if existing.is_rejected:
        return "rejected"
    return "asserted"


def decide_pair_write(
    state: PairState,
    *,
    writer: PairWriter,
    existing_id: str | None = None,
) -> PairWriteDecision:
    if state == "absent":
        return PairWriteDecision(action="insert")
    if state == "asserted":
        if writer == "human_single":
            return PairWriteDecision(
                action="refuse_defined", existing_id=existing_id
            )
        return PairWriteDecision(action="skip_protected")
    # rejected
    if writer == "human_single":
        return PairWriteDecision(
            action="refuse_rejected", existing_id=existing_id
        )
    return PairWriteDecision(action="skip_rejected")


def apply_insert_join(
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
) -> Inserted | Occupied:
    existing = port.get_join_by_pair(from_column_id, to_column_id)
    if existing is not None:
        return Occupied(record=existing)
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
        return Occupied(record=raced)
    port.append_join_change(
        join_change_for_create(
            from_column_id=from_column_id,
            to_column_id=to_column_id,
            created_at=now,
            attester=attester,
            actor_user_id=created_by_user_id,
        )
    )
    return Inserted(record=inserted)
