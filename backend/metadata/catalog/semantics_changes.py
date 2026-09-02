"""Semantics Change records — append when a semantics field actually changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.metadata.catalog.records import new_semantics_change_id


@dataclass(frozen=True)
class CatalogSemanticsChangeRecord:
    id: str
    object_id: str
    column_id: str | None
    field_name: str
    old_value: Any
    new_value: Any
    semantic_source: str
    actor_user_id: str | None
    created_at: datetime


def semantics_change_for_field(
    *,
    object_id: str,
    field_name: str,
    old_value: Any,
    new_value: Any,
    semantic_source: str,
    created_at: datetime,
    column_id: str | None = None,
    actor_user_id: str | None = None,
) -> CatalogSemanticsChangeRecord:
    return CatalogSemanticsChangeRecord(
        id=new_semantics_change_id(),
        object_id=object_id,
        column_id=column_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        semantic_source=semantic_source,
        actor_user_id=actor_user_id,
        created_at=created_at,
    )
