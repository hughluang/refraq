"""Tag store ports and adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.tags.errors import TagNameConflict, TagNotFound
from backend.tags.models import TagRow
from backend.tags.records import TagRecord

__all__ = [
    "MemoryTagStore",
    "SqlTagStore",
    "get_tag_store",
    "reset_tag_store",
]

_NAME_UNIQUE = "uq_tags_name_key"


def _search_needle(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "":
        return None
    return stripped


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemoryTagStore:
    def __init__(self) -> None:
        self._rows: dict[str, TagRecord] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def list_tags(
        self,
        *,
        q: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[TagRecord], int]:
        needle = _search_needle(q)
        with self._lock:
            items = list(self._rows.values())
        if needle is not None:
            folded = needle.lower()
            items = [item for item in items if folded in item.name.lower()]
        items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def get(self, tag_id: str) -> TagRecord | None:
        with self._lock:
            return self._rows.get(tag_id)

    def create(self, record: TagRecord) -> TagRecord:
        with self._lock:
            if record.name_key in self._by_key:
                raise TagNameConflict()
            self._rows[record.id] = record
            self._by_key[record.name_key] = record.id
            return record

    def modify(
        self,
        tag_id: str,
        apply: Callable[[TagRecord], TagRecord],
    ) -> TagRecord:
        with self._lock:
            current = self._rows.get(tag_id)
            if current is None:
                raise TagNotFound()
            patched = apply(current)
            if patched.name_key != current.name_key:
                owner = self._by_key.get(patched.name_key)
                if owner is not None and owner != tag_id:
                    raise TagNameConflict()
                self._by_key.pop(current.name_key, None)
                self._by_key[patched.name_key] = tag_id
            self._rows[tag_id] = patched
            return patched

    def delete(self, tag_id: str) -> TagRecord | None:
        with self._lock:
            current = self._rows.pop(tag_id, None)
            if current is None:
                return None
            self._by_key.pop(current.name_key, None)
            return current


class SqlTagStore:
    def list_tags(
        self,
        *,
        q: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[TagRecord], int]:
        needle = _search_needle(q)
        with session_scope() as session:
            stmt = select(TagRow)
            count_stmt = select(func.count()).select_from(TagRow)
            if needle is not None:
                like = f"%{_escape_like_literal(needle)}%"
                filt = TagRow.name.ilike(like, escape="\\")
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)
            total = int(session.execute(count_stmt).scalar_one())
            rows = (
                session.execute(
                    stmt.order_by(TagRow.created_at.desc(), TagRow.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_record(row) for row in rows], total

    def get(self, tag_id: str) -> TagRecord | None:
        with session_scope() as session:
            row = session.get(TagRow, tag_id)
            return _record(row) if row else None

    def create(self, record: TagRecord) -> TagRecord:
        with session_scope() as session:
            session.add(_row(record))
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_name_dup(exc):
                    raise TagNameConflict() from exc
                raise
            return record

    def modify(
        self,
        tag_id: str,
        apply: Callable[[TagRecord], TagRecord],
    ) -> TagRecord:
        with session_scope() as session:
            row = session.get(TagRow, tag_id, with_for_update=True)
            if row is None:
                raise TagNotFound()
            patched = apply(_record(row))
            row.name = patched.name
            row.name_key = patched.name_key
            row.description = patched.description
            row.updated_at = patched.updated_at
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_name_dup(exc):
                    raise TagNameConflict() from exc
                raise
            return _record(row)

    def delete(self, tag_id: str) -> TagRecord | None:
        with session_scope() as session:
            row = session.get(TagRow, tag_id)
            if row is None:
                return None
            record = _record(row)
            session.delete(row)
            session.flush()
            return record


def _record(row: TagRow) -> TagRecord:
    return TagRecord(
        id=row.id,
        name=row.name,
        name_key=row.name_key,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row(record: TagRecord) -> TagRow:
    return TagRow(
        id=record.id,
        name=record.name,
        name_key=record.name_key,
        description=record.description,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _is_name_dup(exc: BaseException) -> bool:
    """True only for psycopg's unique_violation on ``uq_tags_name_key``.

    The platform driver is psycopg 3: ``sqlstate`` and ``diag.constraint_name``.
    Any other unique violation, including the primary key, stays an error.
    """

    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _NAME_UNIQUE


_memory_singleton: MemoryTagStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_tag_store() -> MemoryTagStore | SqlTagStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryTagStore()
            return _memory_singleton
    return SqlTagStore()


def reset_tag_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_tag_store.cache_clear()
