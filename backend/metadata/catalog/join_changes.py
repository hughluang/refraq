"""Join Change append helpers (write-only ledger)."""

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
