"""Pending federated identity persistence."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.admin.federation.spec import PendingRecord
from backend.admin.models import PendingFederationRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.pagination import apply_offset_page, apply_sql_page
from backend.core.time import utc_now


class PendingStore(Protocol):
    def list_pending(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[PendingRecord], int]: ...

    def get(self, pending_id: str) -> PendingRecord | None: ...

    def get_by_subject(self, issuer: str, subject: str) -> PendingRecord | None: ...

    def save(
        self, record: PendingRecord, *, session: Session | None = None
    ) -> PendingRecord: ...

    def delete(self, pending_id: str, *, session: Session | None = None) -> None: ...


def _alive(record: PendingRecord) -> bool:
    return record.expires_at > utc_now()


class MemoryPendingStore:
    def __init__(self) -> None:
        self._items: dict[str, PendingRecord] = {}
        self._lock = threading.Lock()

    def list_pending(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[PendingRecord], int]:
        with self._lock:
            items = [item for item in self._items.values() if _alive(item)]
            items.sort(key=lambda item: item.last_attempt_at, reverse=True)
            return apply_offset_page(items, limit=limit, offset=offset)

    def get(self, pending_id: str) -> PendingRecord | None:
        with self._lock:
            return self._items.get(pending_id)

    def get_by_subject(self, issuer: str, subject: str) -> PendingRecord | None:
        with self._lock:
            for item in self._items.values():
                if item.issuer == issuer and item.subject == subject:
                    return item
            return None

    def save(
        self, record: PendingRecord, *, session: Session | None = None
    ) -> PendingRecord:
        del session
        with self._lock:
            self._items[record.id] = record
            return record

    def delete(self, pending_id: str, *, session: Session | None = None) -> None:
        del session
        with self._lock:
            self._items.pop(pending_id, None)


class SqlPendingStore:
    def list_pending(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[PendingRecord], int]:
        now = utc_now()
        with session_scope() as session:
            total = int(
                session.scalar(
                    select(func.count())
                    .select_from(PendingFederationRow)
                    .where(PendingFederationRow.expires_at > now)
                )
                or 0
            )
            stmt = apply_sql_page(
                select(PendingFederationRow)
                .where(PendingFederationRow.expires_at > now)
                .order_by(PendingFederationRow.last_attempt_at.desc()),
                limit=limit,
                offset=offset,
            )
            return [_row_to_pending(row) for row in session.scalars(stmt).all()], total

    def get(self, pending_id: str) -> PendingRecord | None:
        with session_scope() as session:
            return _row_to_pending(session.get(PendingFederationRow, pending_id))

    def get_by_subject(self, issuer: str, subject: str) -> PendingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(PendingFederationRow).where(
                    PendingFederationRow.issuer == issuer,
                    PendingFederationRow.subject == subject,
                )
            )
            return _row_to_pending(row)

    def save(
        self, record: PendingRecord, *, session: Session | None = None
    ) -> PendingRecord:
        if session is not None:
            return self._save_on(session, record)
        with session_scope() as owned:
            return self._save_on(owned, record)

    def _save_on(self, session: Session, record: PendingRecord) -> PendingRecord:
        row = session.get(PendingFederationRow, record.id) or session.scalar(
            select(PendingFederationRow).where(
                PendingFederationRow.issuer == record.issuer,
                PendingFederationRow.subject == record.subject,
            )
        )
        if row is None:
            row = PendingFederationRow(id=record.id)
        row.provider_id = record.provider_id
        row.issuer = record.issuer
        row.subject = record.subject
        row.account_hint = record.account_hint
        row.email = record.email
        row.display_name = record.display_name
        row.groups = list(record.groups)
        row.admission_reason = record.admission_reason
        row.attempt_count = record.attempt_count
        row.claims = dict(record.claims)
        row.first_seen_at = record.first_seen_at
        row.last_attempt_at = record.last_attempt_at
        row.expires_at = record.expires_at
        session.add(row)
        session.flush()
        return _row_to_pending(row)  # type: ignore[return-value]

    def delete(self, pending_id: str, *, session: Session | None = None) -> None:
        if session is not None:
            self._delete_on(session, pending_id)
            return
        with session_scope() as owned:
            self._delete_on(owned, pending_id)

    def _delete_on(self, session: Session, pending_id: str) -> None:
        row = session.get(PendingFederationRow, pending_id)
        if row is not None:
            session.delete(row)


def _row_to_pending(row: PendingFederationRow | None) -> PendingRecord | None:
    if row is None:
        return None
    return PendingRecord(
        id=row.id,
        issuer=row.issuer,
        subject=row.subject,
        account_hint=row.account_hint,
        admission_reason=row.admission_reason,
        attempt_count=row.attempt_count,
        first_seen_at=row.first_seen_at,
        last_attempt_at=row.last_attempt_at,
        expires_at=row.expires_at,
        provider_id=row.provider_id,
        email=row.email,
        display_name=row.display_name,
        groups=tuple(row.groups or []),
        claims=dict(row.claims or {}),
    )


_memory: MemoryPendingStore | None = None
_lock = threading.Lock()


@lru_cache
def get_pending_store() -> PendingStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryPendingStore()
            return _memory
    return SqlPendingStore()


def reset_pending_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_pending_store.cache_clear()
