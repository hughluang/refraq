"""Management audit event repository ports and adapters."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from sqlalchemy import select

from backend.admin.models import AuditEventRow
from backend.core.config import get_settings
from backend.core.db import session_scope


@dataclass
class AuditEventRecord:
    id: str
    created_at: datetime
    actor_user_id: str | None
    actor_token_id: str | None
    resource_type: str
    resource_id: str
    action: str
    result: str
    detail: dict = field(default_factory=dict)

class MemoryAuditStore:
    def __init__(self) -> None:
        self._by_id: dict[str, AuditEventRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: AuditEventRecord) -> AuditEventRecord:
        with self._lock:
            self._by_id[record.id] = record
            return record

    def get_by_id(self, event_id: str) -> AuditEventRecord | None:
        with self._lock:
            return self._by_id.get(event_id)

    def list_events(
        self,
        *,
        resource_type: str | None = None,
        actor_user_id: str | None = None,
        action: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[AuditEventRecord], str | None]:
        with self._lock:
            items = list(self._by_id.values())
        items.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        cursor_key: tuple[datetime, str] | None = None
        if cursor:
            for item in items:
                if item.id == cursor:
                    cursor_key = (item.created_at, item.id)
                    break
        filtered: list[AuditEventRecord] = []
        for item in items:
            if resource_type and item.resource_type != resource_type:
                continue
            if actor_user_id and item.actor_user_id != actor_user_id:
                continue
            if action and item.action != action:
                continue
            if from_dt and item.created_at < from_dt:
                continue
            if to_dt and item.created_at > to_dt:
                continue
            if cursor_key is not None and (item.created_at, item.id) >= cursor_key:
                continue
            filtered.append(item)
        page = filtered[:limit]
        next_cursor = page[-1].id if len(filtered) > limit else None
        return page, next_cursor

class SqlAuditStore:
    def create(self, record: AuditEventRecord) -> AuditEventRecord:
        with session_scope() as session:
            row = AuditEventRow(
                id=record.id,
                created_at=record.created_at,
                actor_user_id=record.actor_user_id,
                actor_token_id=record.actor_token_id,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                action=record.action,
                result=record.result,
                detail=record.detail,
            )
            session.add(row)
            session.flush()
            return _row_to_event(row)

    def get_by_id(self, event_id: str) -> AuditEventRecord | None:
        with session_scope() as session:
            row = session.get(AuditEventRow, event_id)
            return _row_to_event(row) if row else None

    def list_events(
        self,
        *,
        resource_type: str | None = None,
        actor_user_id: str | None = None,
        action: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[AuditEventRecord], str | None]:

        with session_scope() as session:
            stmt = select(AuditEventRow).order_by(
                AuditEventRow.created_at.desc(), AuditEventRow.id.desc()
            )
            if resource_type:
                stmt = stmt.where(AuditEventRow.resource_type == resource_type)
            if actor_user_id:
                stmt = stmt.where(AuditEventRow.actor_user_id == actor_user_id)
            if action:
                stmt = stmt.where(AuditEventRow.action == action)
            if from_dt:
                stmt = stmt.where(AuditEventRow.created_at >= from_dt)
            if to_dt:
                stmt = stmt.where(AuditEventRow.created_at <= to_dt)
            if cursor:
                cursor_row = session.get(AuditEventRow, cursor)
                if cursor_row is not None:
                    stmt = stmt.where(
                        (AuditEventRow.created_at < cursor_row.created_at)
                        | (
                            (AuditEventRow.created_at == cursor_row.created_at)
                            & (AuditEventRow.id < cursor_row.id)
                        )
                    )
            rows = session.scalars(stmt.limit(limit + 1)).all()
            page_rows = rows[:limit]
            next_cursor = page_rows[-1].id if len(rows) > limit else None
            return [_row_to_event(row) for row in page_rows], next_cursor

def _row_to_event(row: object) -> AuditEventRecord:
    assert isinstance(row, AuditEventRow)
    return AuditEventRecord(
        id=row.id,
        created_at=row.created_at,
        actor_user_id=row.actor_user_id,
        actor_token_id=row.actor_token_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        action=row.action,
        result=row.result,
        detail=dict(row.detail or {}),
    )

def new_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:12]}"

_memory_singleton: MemoryAuditStore | None = None
_memory_lock = threading.Lock()

@lru_cache
def get_audit_store() -> MemoryAuditStore | SqlAuditStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryAuditStore()
            return _memory_singleton
    return SqlAuditStore()

def reset_audit_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_audit_store.cache_clear()
