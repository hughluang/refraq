"""Join Change records — what to append when a join row mutates.

Adapters persist the record this module returns; they do not decide kind,
attester, or actor. Create / amend / reject / restore are the only events
(ADR 0030 / 0031). Delete of a join row does not append a Change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.metadata.catalog.records import new_join_change_id

JOIN_CHANGE_CREATE = "create"
JOIN_CHANGE_AMEND = "amend"
JOIN_CHANGE_REJECT = "reject"
JOIN_CHANGE_RESTORE = "restore"


@dataclass(frozen=True)
class CatalogJoinChangeRecord:
    id: str
    from_column_id: str
    to_column_id: str
    kind: str
    attester: str | None
    actor_user_id: str | None
    created_at: datetime


def new_join_change(
    *,
    from_column_id: str,
    to_column_id: str,
    kind: str,
    created_at: datetime,
    attester: str | None = None,
    actor_user_id: str | None = None,
) -> CatalogJoinChangeRecord:
    return CatalogJoinChangeRecord(
        id=new_join_change_id(),
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        kind=kind,
        attester=attester,
        actor_user_id=actor_user_id,
        created_at=created_at,
    )


def join_change_for_create(
    *,
    from_column_id: str,
    to_column_id: str,
    created_at: datetime,
    attester: str,
    actor_user_id: str | None = None,
) -> CatalogJoinChangeRecord:
    return new_join_change(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        kind=JOIN_CHANGE_CREATE,
        created_at=created_at,
        attester=attester,
        actor_user_id=actor_user_id,
    )


def join_change_for_amend(
    *,
    from_column_id: str,
    to_column_id: str,
    created_at: datetime,
    actor_user_id: str | None,
) -> CatalogJoinChangeRecord:
    return new_join_change(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        kind=JOIN_CHANGE_AMEND,
        created_at=created_at,
        actor_user_id=actor_user_id,
    )


def join_change_for_rejection_toggle(
    *,
    from_column_id: str,
    to_column_id: str,
    created_at: datetime,
    rejected_at: datetime | None,
    actor_user_id: str | None,
    rejected_by_user_id: str | None,
) -> CatalogJoinChangeRecord:
    kind = JOIN_CHANGE_RESTORE if rejected_at is None else JOIN_CHANGE_REJECT
    actor = actor_user_id if actor_user_id is not None else rejected_by_user_id
    return new_join_change(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        kind=kind,
        created_at=created_at,
        actor_user_id=actor,
    )
