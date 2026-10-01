"""Dictionary store ports and adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.entity.dictionaries.records import DictionaryEntryRecord, DictionaryRecord
from backend.entity.dictionaries.status import DictionaryListStatus
from backend.entity.errors import DictionaryInvalid, DictionaryNameDup, DictionaryNotFound
from backend.entity.models import DictionaryEntryRow, DictionaryRow

__all__ = [
    "MemoryDictionaryStore",
    "SqlDictionaryStore",
    "get_dictionary_store",
    "reset_dictionary_store",
]

_NAME_UNIQUE = "uq_dictionaries_name"


def _escape_like_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemoryDictionaryStore:
    def __init__(self) -> None:
        self._rows: dict[str, DictionaryRecord] = {}
        self._by_name: dict[str, str] = {}
        self._lock = threading.Lock()

    def list_dictionaries(
        self,
        *,
        q: str | None,
        statuses: frozenset[DictionaryListStatus] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DictionaryRecord], int]:
        with self._lock:
            items = list(self._rows.values())
        if q and q.strip():
            needle = q.strip().lower()
            items = [
                item
                for item in items
                if needle in item.name.lower() or needle in item.display_name.lower()
            ]
        if statuses is not None:
            items = [item for item in items if _memory_status_match(item, statuses)]
        items.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def get(self, dictionary_id: str) -> DictionaryRecord | None:
        with self._lock:
            return self._rows.get(dictionary_id)

    def create(self, record: DictionaryRecord) -> DictionaryRecord:
        with self._lock:
            if record.name in self._by_name:
                raise DictionaryNameDup()
            self._rows[record.id] = record
            self._by_name[record.name] = record.id
            return record

    def modify(
        self,
        dictionary_id: str,
        apply: Callable[[DictionaryRecord], DictionaryRecord],
    ) -> DictionaryRecord:
        with self._lock:
            current = self._rows.get(dictionary_id)
            if current is None:
                raise DictionaryNotFound()
            patched = _bound_patch(current, apply(current))
            self._rows[dictionary_id] = patched
            return patched

    def delete(self, dictionary_id: str) -> bool:
        with self._lock:
            current = self._rows.pop(dictionary_id, None)
            if current is None:
                return False
            self._by_name.pop(current.name, None)
            return True


class SqlDictionaryStore:
    def list_dictionaries(
        self,
        *,
        q: str | None,
        statuses: frozenset[DictionaryListStatus] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DictionaryRecord], int]:
        with session_scope() as session:
            stmt = select(DictionaryRow)
            count_stmt = select(func.count()).select_from(DictionaryRow)
            if q and q.strip():
                needle = f"%{_escape_like_literal(q.strip())}%"
                filt = or_(
                    DictionaryRow.name.ilike(needle, escape="\\"),
                    DictionaryRow.display_name.ilike(needle, escape="\\"),
                )
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)
            if statuses is not None:
                status_filt = _dictionary_status_filter(statuses)
                stmt = stmt.where(status_filt)
                count_stmt = count_stmt.where(status_filt)
            total = int(session.execute(count_stmt).scalar_one())
            rows = (
                session.execute(
                    stmt.order_by(DictionaryRow.created_at.desc(), DictionaryRow.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_record(session, row) for row in rows], total

    def get(self, dictionary_id: str) -> DictionaryRecord | None:
        with session_scope() as session:
            row = session.get(DictionaryRow, dictionary_id)
            return _record(session, row) if row else None

    def create(self, record: DictionaryRecord) -> DictionaryRecord:
        with session_scope() as session:
            row = _row(record)
            row.entries = _entry_rows(record)
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                if _is_name_dup(exc):
                    raise DictionaryNameDup() from exc
                raise
            return record

    def modify(
        self,
        dictionary_id: str,
        apply: Callable[[DictionaryRecord], DictionaryRecord],
    ) -> DictionaryRecord:
        with session_scope() as session:
            row = session.get(DictionaryRow, dictionary_id, with_for_update=True)
            if row is None:
                raise DictionaryNotFound()
            current = _record(session, row)
            patched = _bound_patch(current, apply(current))
            row.display_name = patched.display_name
            row.description = patched.description
            row.revision = patched.revision
            row.deprecated_at = patched.deprecated_at
            row.updated_at = patched.updated_at
            if patched.entries != current.entries:
                session.execute(
                    delete(DictionaryEntryRow).where(
                        DictionaryEntryRow.dictionary_id == dictionary_id
                    )
                )
                session.add_all(_entry_rows(patched))
            session.flush()
            return _record(session, row)

    def delete(self, dictionary_id: str) -> bool:
        with session_scope() as session:
            row = session.get(DictionaryRow, dictionary_id)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True


def _memory_status_match(
    item: DictionaryRecord, statuses: frozenset[DictionaryListStatus]
) -> bool:
    if item.deprecated_at is not None:
        return "deprecated" in statuses
    return "available" in statuses


def _dictionary_status_filter(
    statuses: frozenset[DictionaryListStatus],
) -> ColumnElement[bool]:
    """SQL form of dictionary list status."""
    clauses = []
    if "deprecated" in statuses:
        clauses.append(DictionaryRow.deprecated_at.is_not(None))
    if "available" in statuses:
        clauses.append(DictionaryRow.deprecated_at.is_(None))
    return or_(*clauses)


def _bound_patch(current: DictionaryRecord, updated: DictionaryRecord) -> DictionaryRecord:
    if updated.id != current.id or updated.name != current.name:
        raise DictionaryInvalid("Dictionary name is immutable")
    return DictionaryRecord(
        id=current.id,
        name=current.name,
        display_name=updated.display_name,
        description=updated.description,
        revision=updated.revision,
        deprecated_at=updated.deprecated_at,
        entries=updated.entries,
        created_at=current.created_at,
        updated_at=updated.updated_at,
    )


def _record(session: Session, row: DictionaryRow) -> DictionaryRecord:
    entries = session.execute(
        select(DictionaryEntryRow)
        .where(DictionaryEntryRow.dictionary_id == row.id)
        .order_by(DictionaryEntryRow.position.asc(), DictionaryEntryRow.code.asc())
    ).scalars()
    return DictionaryRecord(
        id=row.id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        revision=int(row.revision),
        deprecated_at=row.deprecated_at,
        entries=tuple(
            DictionaryEntryRecord(
                code=entry.code,
                label=entry.label,
                active=bool(entry.active),
                position=int(entry.position),
            )
            for entry in entries
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row(record: DictionaryRecord) -> DictionaryRow:
    return DictionaryRow(
        id=record.id,
        name=record.name,
        display_name=record.display_name,
        description=record.description,
        revision=record.revision,
        deprecated_at=record.deprecated_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _entry_rows(record: DictionaryRecord) -> list[DictionaryEntryRow]:
    return [
        DictionaryEntryRow(
            dictionary_id=record.id,
            code=entry.code,
            label=entry.label,
            active=entry.active,
            position=entry.position,
        )
        for entry in record.entries
    ]


def _is_name_dup(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    if code != "23505":
        return False
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if not isinstance(name, str) or not name:
        name = getattr(orig, "constraint_name", None)
    if not isinstance(name, str) or not name:
        return False
    return name == _NAME_UNIQUE


_memory_singleton: MemoryDictionaryStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_dictionary_store() -> MemoryDictionaryStore | SqlDictionaryStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryDictionaryStore()
            return _memory_singleton
    return SqlDictionaryStore()


def reset_dictionary_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_dictionary_store.cache_clear()
