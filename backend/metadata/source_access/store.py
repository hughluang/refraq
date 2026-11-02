"""Source Membership persistence. Resolution lives in the Source Access service."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from functools import lru_cache
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.metadata.models import SourceMembershipRow
from backend.metadata.source_access.errors import SourceMembershipDuplicate
from backend.metadata.source_access.records import EVERY_SOURCE_TARGET


@dataclass(frozen=True, slots=True)
class StoredMembership:
    id: str
    subject_type: str
    subject_id: str
    target: str
    level: str
    created_at: datetime
    updated_at: datetime


class SourceMembershipStore(Protocol):
    def list_memberships(self) -> list[StoredMembership]: ...

    def insert(self, record: StoredMembership) -> StoredMembership: ...

    def insert_on(
        self, session: Session | None, record: StoredMembership
    ) -> StoredMembership: ...

    def update_level(
        self, membership_id: str, level: str, updated_at: datetime
    ) -> StoredMembership | None: ...

    def update_level_on(
        self,
        session: Session | None,
        membership_id: str,
        level: str,
        updated_at: datetime,
    ) -> StoredMembership | None: ...

    def delete(self, membership_id: str) -> bool: ...

    def delete_on(self, session: Session | None, membership_id: str) -> bool: ...

    def delete_for_source(self, source_id: str) -> None: ...

    def delete_for_source_on(self, session: Session | None, source_id: str) -> None: ...


def _subject_key(record: StoredMembership) -> tuple[str, str, str]:
    return (record.subject_type, record.subject_id, record.target)


def _row_to_stored(row: SourceMembershipRow) -> StoredMembership:
    return StoredMembership(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        target=row.target,
        level=row.level,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class MemorySourceMembershipStore:
    def __init__(self) -> None:
        self._by_id: dict[str, StoredMembership] = {}
        self._by_subject: dict[tuple[str, str, str], str] = {}
        self._lock = threading.Lock()

    def list_memberships(self) -> list[StoredMembership]:
        with self._lock:
            return list(self._by_id.values())

    def insert(self, record: StoredMembership) -> StoredMembership:
        return self.insert_on(None, record)

    def insert_on(
        self, session: Session | None, record: StoredMembership
    ) -> StoredMembership:
        del session
        key = _subject_key(record)
        with self._lock:
            if key in self._by_subject or record.id in self._by_id:
                raise SourceMembershipDuplicate()
            self._by_id[record.id] = record
            self._by_subject[key] = record.id
            return record

    def update_level(
        self, membership_id: str, level: str, updated_at: datetime
    ) -> StoredMembership | None:
        return self.update_level_on(None, membership_id, level, updated_at)

    def update_level_on(
        self,
        session: Session | None,
        membership_id: str,
        level: str,
        updated_at: datetime,
    ) -> StoredMembership | None:
        del session
        with self._lock:
            current = self._by_id.get(membership_id)
            if current is None:
                return None
            updated = replace(current, level=level, updated_at=updated_at)
            self._by_id[membership_id] = updated
            return updated

    def delete(self, membership_id: str) -> bool:
        return self.delete_on(None, membership_id)

    def delete_on(self, session: Session | None, membership_id: str) -> bool:
        del session
        with self._lock:
            current = self._by_id.pop(membership_id, None)
            if current is None:
                return False
            self._by_subject.pop(_subject_key(current), None)
            return True

    def delete_for_source(self, source_id: str) -> None:
        self.delete_for_source_on(None, source_id)

    def delete_for_source_on(self, session: Session | None, source_id: str) -> None:
        del session
        if source_id == EVERY_SOURCE_TARGET:
            return
        with self._lock:
            doomed = [
                record for record in self._by_id.values() if record.target == source_id
            ]
            for record in doomed:
                self._by_id.pop(record.id, None)
                self._by_subject.pop(_subject_key(record), None)


class SqlSourceMembershipStore:
    def list_memberships(self) -> list[StoredMembership]:
        with session_scope() as session:
            rows = session.scalars(select(SourceMembershipRow)).all()
            return [_row_to_stored(row) for row in rows]

    def insert(self, record: StoredMembership) -> StoredMembership:
        with session_scope() as session:
            return self.insert_on(session, record)

    def insert_on(
        self, session: Session | None, record: StoredMembership
    ) -> StoredMembership:
        if session is None:
            raise RuntimeError("SQL membership insert requires a session")
        self._reject_duplicate(session, record)
        row = SourceMembershipRow(
            id=record.id,
            subject_type=record.subject_type,
            subject_id=record.subject_id,
            target=record.target,
            level=record.level,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise SourceMembershipDuplicate() from exc
        return _row_to_stored(row)

    def update_level(
        self, membership_id: str, level: str, updated_at: datetime
    ) -> StoredMembership | None:
        with session_scope() as session:
            return self.update_level_on(session, membership_id, level, updated_at)

    def update_level_on(
        self,
        session: Session | None,
        membership_id: str,
        level: str,
        updated_at: datetime,
    ) -> StoredMembership | None:
        if session is None:
            raise RuntimeError("SQL membership update requires a session")
        row = session.get(SourceMembershipRow, membership_id)
        if row is None:
            return None
        row.level = level
        row.updated_at = updated_at
        session.flush()
        return _row_to_stored(row)

    def delete(self, membership_id: str) -> bool:
        with session_scope() as session:
            return self.delete_on(session, membership_id)

    def delete_on(self, session: Session | None, membership_id: str) -> bool:
        if session is None:
            raise RuntimeError("SQL membership delete requires a session")
        row = session.get(SourceMembershipRow, membership_id)
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True

    def delete_for_source(self, source_id: str) -> None:
        with session_scope() as session:
            self.delete_for_source_on(session, source_id)

    def delete_for_source_on(self, session: Session | None, source_id: str) -> None:
        if session is None:
            raise RuntimeError("SQL membership delete requires a session")
        if source_id == EVERY_SOURCE_TARGET:
            return
        session.execute(
            delete(SourceMembershipRow).where(SourceMembershipRow.target == source_id)
        )
        session.flush()

    def _reject_duplicate(self, session: Session, record: StoredMembership) -> None:
        existing = session.scalar(
            select(SourceMembershipRow.id).where(
                SourceMembershipRow.subject_type == record.subject_type,
                SourceMembershipRow.subject_id == record.subject_id,
                SourceMembershipRow.target == record.target,
            )
        )
        if existing is not None or session.get(SourceMembershipRow, record.id) is not None:
            raise SourceMembershipDuplicate()


_memory_singleton: MemorySourceMembershipStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_source_access_store() -> MemorySourceMembershipStore | SqlSourceMembershipStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemorySourceMembershipStore()
            return _memory_singleton
    return SqlSourceMembershipStore()


def reset_source_access_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_source_access_store.cache_clear()
