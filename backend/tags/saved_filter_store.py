"""Saved Filter store. The comparison form is not an HTTP field."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.tags.errors import SavedFilterLimit, SavedFilterNameConflict, SavedFilterNotFound
from backend.tags.models import SavedFilterDefaultRow, SavedFilterRow

__all__ = [
    "FILTER_CAP",
    "MemorySavedFilterStore",
    "SavedFilterRecord",
    "SqlSavedFilterStore",
    "get_saved_filter_store",
    "reset_saved_filter_store",
]

FILTER_CAP = 20
_NAME_UNIQUE = "uq_saved_filters_user_list_name"


@dataclass(frozen=True, slots=True)
class SavedFilterRecord:
    id: str
    user_id: str
    list_name: str
    name: str
    name_key: str
    query: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _copy_query(query: dict[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in query.items()
    }


def _copy(record: SavedFilterRecord) -> SavedFilterRecord:
    return SavedFilterRecord(
        id=record.id,
        user_id=record.user_id,
        list_name=record.list_name,
        name=record.name,
        name_key=record.name_key,
        query=_copy_query(record.query),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _row(record: SavedFilterRecord) -> SavedFilterRow:
    return SavedFilterRow(
        id=record.id,
        user_id=record.user_id,
        list_name=record.list_name,
        name=record.name,
        name_key=record.name_key,
        query=_copy_query(record.query),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _record(row: SavedFilterRow) -> SavedFilterRecord:
    return SavedFilterRecord(
        id=row.id,
        user_id=row.user_id,
        list_name=row.list_name,
        name=row.name,
        name_key=row.name_key,
        query=_copy_query(row.query),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _is_name_dup(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _NAME_UNIQUE


class MemorySavedFilterStore:
    def __init__(self) -> None:
        self._rows: dict[str, SavedFilterRecord] = {}
        self._defaults: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def create(self, record: SavedFilterRecord) -> SavedFilterRecord:
        with self._lock:
            count = sum(
                1
                for item in self._rows.values()
                if item.user_id == record.user_id and item.list_name == record.list_name
            )
            if count >= FILTER_CAP:
                raise SavedFilterLimit()
            if _memory_name_taken(self, record):
                raise SavedFilterNameConflict()
            stored = _copy(record)
            self._rows[record.id] = stored
            return _copy(stored)

    def get(self, filter_id: str) -> SavedFilterRecord | None:
        with self._lock:
            found = self._rows.get(filter_id)
            return _copy(found) if found is not None else None

    def list_for_user(
        self,
        user_id: str,
        list_name: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[SavedFilterRecord], int]:
        with self._lock:
            items = [
                _copy(item)
                for item in self._rows.values()
                if item.user_id == user_id and item.list_name == list_name
            ]
        items.sort(key=lambda item: (item.name_key, item.id))
        return items[offset : offset + limit], len(items)

    def update(self, record: SavedFilterRecord) -> SavedFilterRecord:
        with self._lock:
            current = self._rows.get(record.id)
            if current is None:
                raise SavedFilterNotFound()
            if record.name_key != current.name_key and _memory_name_taken(self, record):
                raise SavedFilterNameConflict()
            stored = _copy(record)
            self._rows[record.id] = stored
            return _copy(stored)

    def delete(self, filter_id: str) -> None:
        with self._lock:
            current = self._rows.pop(filter_id, None)
            if current is None:
                raise SavedFilterNotFound()
            stale = [
                key
                for key, remembered in self._defaults.items()
                if remembered == filter_id
            ]
            for key in stale:
                self._defaults.pop(key, None)

    def get_default(self, user_id: str, list_name: str) -> str | None:
        with self._lock:
            return self._defaults.get((user_id, list_name))

    def set_default(self, user_id: str, list_name: str, filter_id: str | None) -> None:
        with self._lock:
            key = (user_id, list_name)
            if filter_id is None:
                self._defaults.pop(key, None)
                return
            self._defaults[key] = filter_id


def _memory_name_taken(store: MemorySavedFilterStore, record: SavedFilterRecord) -> bool:
    for other in store._rows.values():
        if other.id == record.id:
            continue
        if (
            other.user_id == record.user_id
            and other.list_name == record.list_name
            and other.name_key == record.name_key
        ):
            return True
    return False


class SqlSavedFilterStore:
    def create(self, record: SavedFilterRecord) -> SavedFilterRecord:
        with session_scope() as session:
            _lock_user_list(session, record.user_id, record.list_name)
            count = session.scalar(
                select(func.count())
                .select_from(SavedFilterRow)
                .where(
                    SavedFilterRow.user_id == record.user_id,
                    SavedFilterRow.list_name == record.list_name,
                )
            )
            if int(count or 0) >= FILTER_CAP:
                raise SavedFilterLimit()
            session.add(_row(record))
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_name_dup(exc):
                    raise SavedFilterNameConflict() from exc
                raise
            return _copy(record)

    def get(self, filter_id: str) -> SavedFilterRecord | None:
        with session_scope() as session:
            row = session.get(SavedFilterRow, filter_id)
            return _record(row) if row is not None else None

    def list_for_user(
        self,
        user_id: str,
        list_name: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[SavedFilterRecord], int]:
        with session_scope() as session:
            pred = (
                SavedFilterRow.user_id == user_id,
                SavedFilterRow.list_name == list_name,
            )
            total = int(
                session.scalar(
                    select(func.count()).select_from(SavedFilterRow).where(*pred)
                )
                or 0
            )
            stmt = (
                select(SavedFilterRow)
                .where(*pred)
                .order_by(SavedFilterRow.name_key.asc(), SavedFilterRow.id.asc())
                .limit(limit)
                .offset(offset)
            )
            return [_record(row) for row in session.scalars(stmt).all()], total

    def update(self, record: SavedFilterRecord) -> SavedFilterRecord:
        with session_scope() as session:
            row = session.get(SavedFilterRow, record.id, with_for_update=True)
            if row is None:
                raise SavedFilterNotFound()
            row.name = record.name
            row.name_key = record.name_key
            row.query = _copy_query(record.query)
            row.updated_at = record.updated_at
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_name_dup(exc):
                    raise SavedFilterNameConflict() from exc
                raise
            return _record(row)

    def delete(self, filter_id: str) -> None:
        with session_scope() as session:
            row = session.get(SavedFilterRow, filter_id, with_for_update=True)
            if row is None:
                raise SavedFilterNotFound()
            session.delete(row)
            session.flush()

    def get_default(self, user_id: str, list_name: str) -> str | None:
        with session_scope() as session:
            row = session.get(SavedFilterDefaultRow, (user_id, list_name))
            return row.saved_filter_id if row is not None else None

    def set_default(self, user_id: str, list_name: str, filter_id: str | None) -> None:
        with session_scope() as session:
            row = session.get(SavedFilterDefaultRow, (user_id, list_name))
            if filter_id is None:
                if row is not None:
                    session.delete(row)
                    session.flush()
                return
            if row is None:
                session.add(
                    SavedFilterDefaultRow(
                        user_id=user_id,
                        list_name=list_name,
                        saved_filter_id=filter_id,
                    )
                )
            else:
                row.saved_filter_id = filter_id
            session.flush()


def _lock_user_list(session: Session, user_id: str, list_name: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
        {"key": f"saved-filter:{user_id}:{list_name}"},
    )


_memory_singleton: MemorySavedFilterStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_saved_filter_store() -> MemorySavedFilterStore | SqlSavedFilterStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemorySavedFilterStore()
            return _memory_singleton
    return SqlSavedFilterStore()


def reset_saved_filter_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_saved_filter_store.cache_clear()
