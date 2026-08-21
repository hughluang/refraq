"""External identity binding persistence."""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.admin.federation.errors import FederationAlreadyBound
from backend.admin.federation.spec import BindingRecord
from backend.admin.models import FederatedIdentityRow
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now


class BindingStore(Protocol):
    def get(self, issuer: str, subject: str) -> BindingRecord | None: ...

    def get_for_user(self, user_id: str) -> BindingRecord | None: ...

    def list_for_issuer(self, issuer: str) -> list[BindingRecord]: ...

    def save(
        self, record: BindingRecord, *, session: Session | None = None
    ) -> BindingRecord: ...

    def delete_for_user(self, user_id: str, *, session: Session | None = None) -> None: ...


class MemoryBindingStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], BindingRecord] = {}
        self._lock = threading.Lock()

    def get(self, issuer: str, subject: str) -> BindingRecord | None:
        with self._lock:
            return self._items.get((issuer, subject))

    def get_for_user(self, user_id: str) -> BindingRecord | None:
        with self._lock:
            return next(
                (item for item in self._items.values() if item.user_id == user_id),
                None,
            )

    def list_for_issuer(self, issuer: str) -> list[BindingRecord]:
        with self._lock:
            return [item for item in self._items.values() if item.issuer == issuer]

    def save(
        self, record: BindingRecord, *, session: Session | None = None
    ) -> BindingRecord:
        del session
        with self._lock:
            self._items[(record.issuer, record.subject)] = record
            return record

    def delete_for_user(
        self, user_id: str, *, session: Session | None = None
    ) -> None:
        del session
        with self._lock:
            self._items = {
                key: item for key, item in self._items.items() if item.user_id != user_id
            }


class SqlBindingStore:
    def get(self, issuer: str, subject: str) -> BindingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(FederatedIdentityRow).where(
                    FederatedIdentityRow.issuer == issuer,
                    FederatedIdentityRow.subject == subject,
                )
            )
            return _row_to_binding(row)

    def get_for_user(self, user_id: str) -> BindingRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(FederatedIdentityRow).where(FederatedIdentityRow.user_id == user_id)
            )
            return _row_to_binding(row)

    def list_for_issuer(self, issuer: str) -> list[BindingRecord]:
        with session_scope() as session:
            rows = session.scalars(
                select(FederatedIdentityRow).where(FederatedIdentityRow.issuer == issuer)
            ).all()
            return [_row_to_binding(row) for row in rows if row is not None]

    def save(
        self, record: BindingRecord, *, session: Session | None = None
    ) -> BindingRecord:
        if session is not None:
            return self._save_on(session, record)
        with session_scope() as owned:
            return self._save_on(owned, record)

    def _save_on(self, session: Session, record: BindingRecord) -> BindingRecord:
        row = session.get(FederatedIdentityRow, record.id) or FederatedIdentityRow(
            id=record.id,
            linked_at=record.linked_at or utc_now(),
        )
        row.provider_id = record.provider_id
        row.issuer = record.issuer
        row.subject = record.subject
        row.user_id = record.user_id
        row.email = record.email
        row.display_name = record.display_name
        row.last_login_at = record.last_login_at
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise FederationAlreadyBound() from exc
        return _row_to_binding(row)  # type: ignore[return-value]

    def delete_for_user(
        self, user_id: str, *, session: Session | None = None
    ) -> None:
        if session is not None:
            self._delete_for_user_on(session, user_id)
            return
        with session_scope() as owned:
            self._delete_for_user_on(owned, user_id)

    def _delete_for_user_on(self, session: Session, user_id: str) -> None:
        rows = session.scalars(
            select(FederatedIdentityRow).where(FederatedIdentityRow.user_id == user_id)
        ).all()
        for row in rows:
            session.delete(row)


def _row_to_binding(row: FederatedIdentityRow | None) -> BindingRecord | None:
    if row is None:
        return None
    return BindingRecord(
        id=row.id,
        issuer=row.issuer,
        subject=row.subject,
        user_id=row.user_id,
        provider_id=row.provider_id,
        email=row.email,
        display_name=row.display_name,
        linked_at=row.linked_at,
        last_login_at=row.last_login_at,
    )


_memory: MemoryBindingStore | None = None
_lock = threading.Lock()


@lru_cache
def get_binding_store() -> BindingStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryBindingStore()
            return _memory
    return SqlBindingStore()


def reset_binding_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_binding_store.cache_clear()
