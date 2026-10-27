"""Tag store ports and adapters."""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, TypeVar

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.tags.errors import TagInUse, TagNameConflict, TagNotFound
from backend.tags.models import TagAssignmentRow, TagRow, TagSubjectRevisionRow
from backend.tags.records import TagRecord

_T = TypeVar("_T")

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
        self._assignments: dict[tuple[str, str], set[str]] = {}
        self._revisions: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def run(
        self,
        fn: Callable[[TagUnit], _T],
        *,
        session: Session | None = None,
    ) -> _T:
        del session
        with self._lock:
            return fn(_MemoryUnit(self))

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
            entity_count, channel_count = _memory_counts(self, tag_id)
            if entity_count or channel_count:
                raise TagInUse(entity_count, channel_count)
            current = self._rows.pop(tag_id, None)
            if current is None:
                return None
            self._by_key.pop(current.name_key, None)
            return current


class SqlTagStore:
    def run(
        self,
        fn: Callable[[TagUnit], _T],
        *,
        session: Session | None = None,
    ) -> _T:
        if session is not None:
            return fn(_SqlUnit(session))
        with session_scope() as owned:
            return fn(_SqlUnit(owned))

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
            row = session.get(TagRow, tag_id, with_for_update=True)
            if row is None:
                return None
            entity_count, channel_count = _sql_counts(session, tag_id)
            if entity_count or channel_count:
                raise TagInUse(entity_count, channel_count)
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


class TagUnit(Protocol):
    def lock_subject(self, kind: str, subject_id: str) -> None: ...

    def get_tag(self, tag_id: str, *, lock: bool) -> TagRecord | None: ...

    def get_by_key(self, name_key: str) -> TagRecord | None: ...

    def insert_tag(self, record: TagRecord) -> TagRecord: ...

    def read_assignment(self, kind: str, subject_id: str) -> tuple[set[str], int]: ...

    def write_assignment(
        self, kind: str, subject_id: str, tag_ids: set[str], revision: int
    ) -> None: ...

    def clear_assignment(self, kind: str, subject_id: str) -> None: ...

    def count_kinds(self, tag_id: str) -> tuple[int, int]: ...

    def assignment_subjects(self, tag_id: str) -> list[tuple[str, str]]: ...

    def subjects_with_any(self, kind: str, tag_ids: set[str]) -> list[str]: ...


def _memory_counts(store: MemoryTagStore, tag_id: str) -> tuple[int, int]:
    entity_count = 0
    channel_count = 0
    for (kind, _subject), ids in store._assignments.items():
        if tag_id not in ids:
            continue
        if kind == "entity":
            entity_count += 1
        elif kind == "channel":
            channel_count += 1
    return entity_count, channel_count


def _sql_counts(session: Session, tag_id: str) -> tuple[int, int]:
    rows = session.execute(
        select(
            TagAssignmentRow.subject_kind,
            func.count(func.distinct(TagAssignmentRow.subject_id)),
        )
        .where(TagAssignmentRow.tag_id == tag_id)
        .group_by(TagAssignmentRow.subject_kind)
    ).all()
    counts = {kind: int(total) for kind, total in rows}
    return counts.get("entity", 0), counts.get("channel", 0)


class _MemoryUnit:
    def __init__(self, store: MemoryTagStore) -> None:
        self._store = store

    def lock_subject(self, kind: str, subject_id: str) -> None:
        del kind, subject_id

    def get_tag(self, tag_id: str, *, lock: bool) -> TagRecord | None:
        del lock
        return self._store._rows.get(tag_id)

    def get_by_key(self, name_key: str) -> TagRecord | None:
        tag_id = self._store._by_key.get(name_key)
        if tag_id is None:
            return None
        return self._store._rows.get(tag_id)

    def insert_tag(self, record: TagRecord) -> TagRecord:
        if record.name_key in self._store._by_key:
            raise TagNameConflict()
        self._store._rows[record.id] = record
        self._store._by_key[record.name_key] = record.id
        return record

    def read_assignment(self, kind: str, subject_id: str) -> tuple[set[str], int]:
        key = (kind, subject_id)
        ids = set(self._store._assignments.get(key, set()))
        return ids, self._store._revisions.get(key, 1)

    def write_assignment(
        self, kind: str, subject_id: str, tag_ids: set[str], revision: int
    ) -> None:
        key = (kind, subject_id)
        self._store._assignments[key] = set(tag_ids)
        self._store._revisions[key] = revision

    def clear_assignment(self, kind: str, subject_id: str) -> None:
        key = (kind, subject_id)
        self._store._assignments.pop(key, None)
        self._store._revisions.pop(key, None)

    def count_kinds(self, tag_id: str) -> tuple[int, int]:
        return _memory_counts(self._store, tag_id)

    def assignment_subjects(self, tag_id: str) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for (kind, subject_id), ids in self._store._assignments.items():
            if tag_id in ids:
                found.append((kind, subject_id))
        return found

    def subjects_with_any(self, kind: str, tag_ids: set[str]) -> list[str]:
        found: list[str] = []
        for (subject_kind, subject_id), ids in self._store._assignments.items():
            if subject_kind == kind and ids & tag_ids:
                found.append(subject_id)
        found.sort()
        return found


class _SqlUnit:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_subject(self, kind: str, subject_id: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"tag-subject:{kind}:{subject_id}"},
        )

    def get_tag(self, tag_id: str, *, lock: bool) -> TagRecord | None:
        row = self._session.get(TagRow, tag_id, with_for_update=lock)
        return _record(row) if row else None

    def get_by_key(self, name_key: str) -> TagRecord | None:
        row = self._session.execute(
            select(TagRow).where(TagRow.name_key == name_key)
        ).scalar_one_or_none()
        return _record(row) if row else None

    def insert_tag(self, record: TagRecord) -> TagRecord:
        nested = self._session.begin_nested()
        self._session.add(_row(record))
        try:
            self._session.flush()
        except IntegrityError as exc:
            nested.rollback()
            if _is_name_dup(exc):
                raise TagNameConflict() from exc
            raise
        else:
            nested.commit()
        return record

    def read_assignment(self, kind: str, subject_id: str) -> tuple[set[str], int]:
        revision_row = self._session.get(TagSubjectRevisionRow, (kind, subject_id))
        rows = self._session.execute(
            select(TagAssignmentRow).where(
                TagAssignmentRow.subject_kind == kind,
                TagAssignmentRow.subject_id == subject_id,
            )
        ).scalars().all()
        revision = revision_row.revision if revision_row is not None else 1
        return {row.tag_id for row in rows}, revision

    def write_assignment(
        self, kind: str, subject_id: str, tag_ids: set[str], revision: int
    ) -> None:
        rows = self._session.execute(
            select(TagAssignmentRow).where(
                TagAssignmentRow.subject_kind == kind,
                TagAssignmentRow.subject_id == subject_id,
            )
        ).scalars().all()
        present = {row.tag_id for row in rows}
        for row in rows:
            if row.tag_id not in tag_ids:
                self._session.delete(row)
        for tag_id in tag_ids:
            if tag_id not in present:
                self._session.add(
                    TagAssignmentRow(
                        subject_kind=kind,
                        subject_id=subject_id,
                        tag_id=tag_id,
                    )
                )
        revision_row = self._session.get(TagSubjectRevisionRow, (kind, subject_id))
        if revision_row is None:
            self._session.add(
                TagSubjectRevisionRow(
                    subject_kind=kind,
                    subject_id=subject_id,
                    revision=revision,
                )
            )
        else:
            revision_row.revision = revision
        self._session.flush()

    def clear_assignment(self, kind: str, subject_id: str) -> None:
        self._session.execute(
            delete(TagAssignmentRow).where(
                TagAssignmentRow.subject_kind == kind,
                TagAssignmentRow.subject_id == subject_id,
            )
        )
        revision_row = self._session.get(TagSubjectRevisionRow, (kind, subject_id))
        if revision_row is not None:
            self._session.delete(revision_row)
        self._session.flush()

    def count_kinds(self, tag_id: str) -> tuple[int, int]:
        return _sql_counts(self._session, tag_id)

    def assignment_subjects(self, tag_id: str) -> list[tuple[str, str]]:
        rows = self._session.execute(
            select(TagAssignmentRow.subject_kind, TagAssignmentRow.subject_id).where(
                TagAssignmentRow.tag_id == tag_id
            )
        ).all()
        return [(kind, subject_id) for kind, subject_id in rows]

    def subjects_with_any(self, kind: str, tag_ids: set[str]) -> list[str]:
        rows = self._session.execute(
            select(TagAssignmentRow.subject_id)
            .where(
                TagAssignmentRow.subject_kind == kind,
                TagAssignmentRow.tag_id.in_(tag_ids),
            )
            .distinct()
        ).scalars().all()
        return sorted(rows)


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
