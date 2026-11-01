"""Refused calls to a published inbound path."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select

from backend.channel.models import InboundRejectionRow
from backend.core.config import get_settings
from backend.core.db import session_scope

__all__ = [
    "InboundRejectionRecord",
    "get_inbound_rejection_store",
    "new_inbound_rejection_id",
    "reset_inbound_rejection_store",
]


def new_inbound_rejection_id() -> str:
    return f"irj_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class InboundRejectionRecord:
    id: str
    channel_id: str
    node_id: str
    path: str
    received_at: datetime
    reason: str
    method: str
    headers: dict[str, str]
    query: dict[str, str]
    body: str | None


def _copy(record: InboundRejectionRecord) -> InboundRejectionRecord:
    return InboundRejectionRecord(
        id=record.id,
        channel_id=record.channel_id,
        node_id=record.node_id,
        path=record.path,
        received_at=record.received_at,
        reason=record.reason,
        method=record.method,
        headers=dict(record.headers),
        query=dict(record.query),
        body=record.body,
    )


class MemoryInboundRejectionStore:
    def __init__(self) -> None:
        self._rows: dict[str, InboundRejectionRecord] = {}
        self._lock = threading.Lock()

    def insert(self, record: InboundRejectionRecord) -> InboundRejectionRecord:
        stored = _copy(record)
        with self._lock:
            self._rows[stored.id] = stored
        return _copy(stored)

    def list_for_channel(
        self, channel_id: str, *, limit: int, offset: int
    ) -> tuple[list[InboundRejectionRecord], int]:
        with self._lock:
            rows = [
                row for row in self._rows.values() if row.channel_id == channel_id
            ]
        rows.sort(key=lambda row: (row.received_at, row.id), reverse=True)
        page = rows[offset : offset + limit]
        return [_copy(row) for row in page], len(rows)

    def delete_received_before(self, cutoff: datetime) -> int:
        with self._lock:
            doomed = [
                key
                for key, row in self._rows.items()
                if row.received_at < cutoff
            ]
            for key in doomed:
                del self._rows[key]
        return len(doomed)


class SqlInboundRejectionStore:
    def insert(self, record: InboundRejectionRecord) -> InboundRejectionRecord:
        stored = _copy(record)
        with session_scope() as session:
            session.add(
                InboundRejectionRow(
                    id=stored.id,
                    channel_id=stored.channel_id,
                    node_id=stored.node_id,
                    path=stored.path,
                    received_at=stored.received_at,
                    reason=stored.reason,
                    method=stored.method,
                    headers=dict(stored.headers),
                    query=dict(stored.query),
                    body=stored.body,
                )
            )
        return _copy(stored)

    def list_for_channel(
        self, channel_id: str, *, limit: int, offset: int
    ) -> tuple[list[InboundRejectionRecord], int]:
        with session_scope() as session:
            total = session.scalar(
                select(func.count())
                .select_from(InboundRejectionRow)
                .where(InboundRejectionRow.channel_id == channel_id)
            )
            rows = session.scalars(
                select(InboundRejectionRow)
                .where(InboundRejectionRow.channel_id == channel_id)
                .order_by(
                    InboundRejectionRow.received_at.desc(),
                    InboundRejectionRow.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
            return [_from_row(row) for row in rows], int(total or 0)

    def delete_received_before(self, cutoff: datetime) -> int:
        with session_scope() as session:
            result = session.execute(
                delete(InboundRejectionRow).where(
                    InboundRejectionRow.received_at < cutoff
                )
            )
            return int(result.rowcount or 0)


def _from_row(row: InboundRejectionRow) -> InboundRejectionRecord:
    headers = row.headers if isinstance(row.headers, dict) else {}
    query = row.query if isinstance(row.query, dict) else {}
    return InboundRejectionRecord(
        id=row.id,
        channel_id=row.channel_id,
        node_id=row.node_id,
        path=row.path,
        received_at=row.received_at,
        reason=row.reason,
        method=row.method,
        headers={str(key): str(value) for key, value in headers.items()},
        query={str(key): str(value) for key, value in query.items()},
        body=row.body,
    )


_memory: MemoryInboundRejectionStore | None = None
_lock = threading.Lock()


def get_inbound_rejection_store() -> (
    MemoryInboundRejectionStore | SqlInboundRejectionStore
):
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryInboundRejectionStore()
            return _memory
    return SqlInboundRejectionStore()


def reset_inbound_rejection_store() -> None:
    global _memory
    with _lock:
        _memory = None
