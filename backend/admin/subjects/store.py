"""User Group, membership, and Subject Attribute persistence."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Protocol

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from backend.admin.models import (
    SubjectAttributeDefRow,
    SubjectAttributeValueRow,
    UserGroupMemberRow,
    UserGroupRow,
    UserRow,
)
from backend.admin.subjects.errors import (
    SubjectAttributeKeyDuplicate,
    UserGroupKeyDuplicate,
)
from backend.admin.subjects.records import (
    SubjectAttributeRecord,
    SubjectType,
    UserGroupRecord,
)
from backend.admin.user_store import get_user_store
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.pagination import apply_offset_page, apply_sql_page
from backend.core.time import utc_now

StoredValues = dict[str, tuple[str, ...]]


class SubjectStore(Protocol):
    def list_groups(
        self, *, q: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[UserGroupRecord], int]: ...

    def get_group(self, group_id: str) -> UserGroupRecord | None: ...

    def create_group(self, record: UserGroupRecord) -> UserGroupRecord: ...

    def update_group(self, record: UserGroupRecord) -> UserGroupRecord: ...

    def delete_group(self, group_id: str) -> bool: ...

    def existing_group_ids(self, group_ids: Iterable[str]) -> frozenset[str]: ...

    def member_counts(self, group_ids: Iterable[str]) -> dict[str, int]: ...

    def list_member_ids(
        self, group_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[str], int]:
        """Member user ids ordered by user account, then id; total counts all members."""
        ...

    def add_member(self, group_id: str, user_id: str) -> None: ...

    def remove_member(self, group_id: str, user_id: str) -> None: ...

    def group_ids_of(self, user_id: str) -> list[str]: ...

    def replace_user_groups(self, user_id: str, group_ids: Iterable[str]) -> None: ...

    def list_definitions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[SubjectAttributeRecord], int]: ...

    def get_definition(self, definition_id: str) -> SubjectAttributeRecord | None: ...

    def get_definition_by_key(self, key: str) -> SubjectAttributeRecord | None: ...

    def create_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord: ...

    def update_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord: ...

    def delete_definition(self, definition_id: str) -> bool: ...

    def values_for(
        self, subject_type: SubjectType, subject_ids: Iterable[str]
    ) -> dict[str, StoredValues]: ...

    def replace_values(
        self,
        subject_type: SubjectType,
        subject_id: str,
        values: Mapping[str, tuple[str, ...]],
    ) -> None: ...


def _group_sort_key(record: UserGroupRecord) -> tuple[str, str]:
    return (record.key, record.id)


def _definition_sort_key(record: SubjectAttributeRecord) -> tuple[str, str]:
    return (record.key, record.id)


class MemorySubjectStore:
    def __init__(self) -> None:
        self._groups: dict[str, UserGroupRecord] = {}
        self._members: set[tuple[str, str]] = set()
        self._definitions: dict[str, SubjectAttributeRecord] = {}
        self._values: dict[tuple[str, str], StoredValues] = {}
        self._lock = threading.Lock()

    def list_groups(
        self, *, q: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[UserGroupRecord], int]:
        with self._lock:
            items = sorted(self._groups.values(), key=_group_sort_key)
        if q:
            needle = q.lower()
            items = [
                item
                for item in items
                if needle in item.key.lower() or needle in item.name.lower()
            ]
        return apply_offset_page(items, limit=limit, offset=offset)

    def get_group(self, group_id: str) -> UserGroupRecord | None:
        with self._lock:
            return self._groups.get(group_id)

    def create_group(self, record: UserGroupRecord) -> UserGroupRecord:
        with self._lock:
            if any(item.key == record.key for item in self._groups.values()):
                raise UserGroupKeyDuplicate()
            self._groups[record.id] = record
            return record

    def update_group(self, record: UserGroupRecord) -> UserGroupRecord:
        with self._lock:
            self._groups[record.id] = record
            return record

    def delete_group(self, group_id: str) -> bool:
        with self._lock:
            if self._groups.pop(group_id, None) is None:
                return False
            self._members = {pair for pair in self._members if pair[0] != group_id}
            self._values.pop(("group", group_id), None)
            return True

    def existing_group_ids(self, group_ids: Iterable[str]) -> frozenset[str]:
        with self._lock:
            return frozenset(item for item in group_ids if item in self._groups)

    def member_counts(self, group_ids: Iterable[str]) -> dict[str, int]:
        wanted = set(group_ids)
        counts = {group_id: 0 for group_id in wanted}
        with self._lock:
            for group_id, _user_id in self._members:
                if group_id in wanted:
                    counts[group_id] += 1
        return counts

    def list_member_ids(
        self, group_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[str], int]:
        with self._lock:
            ids = [user_id for gid, user_id in self._members if gid == group_id]
        users = get_user_store()
        found = [user for user in map(users.get_by_id, ids) if user is not None]
        found.sort(key=lambda user: (user.account, user.id))
        return apply_offset_page([user.id for user in found], limit=limit, offset=offset)

    def add_member(self, group_id: str, user_id: str) -> None:
        with self._lock:
            self._members.add((group_id, user_id))

    def remove_member(self, group_id: str, user_id: str) -> None:
        with self._lock:
            self._members.discard((group_id, user_id))

    def group_ids_of(self, user_id: str) -> list[str]:
        with self._lock:
            return [gid for gid, uid in self._members if uid == user_id]

    def replace_user_groups(self, user_id: str, group_ids: Iterable[str]) -> None:
        wanted = set(group_ids)
        with self._lock:
            self._members = {pair for pair in self._members if pair[1] != user_id}
            self._members.update((group_id, user_id) for group_id in wanted)

    def list_definitions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[SubjectAttributeRecord], int]:
        with self._lock:
            items = sorted(self._definitions.values(), key=_definition_sort_key)
        return apply_offset_page(items, limit=limit, offset=offset)

    def get_definition(self, definition_id: str) -> SubjectAttributeRecord | None:
        with self._lock:
            return self._definitions.get(definition_id)

    def get_definition_by_key(self, key: str) -> SubjectAttributeRecord | None:
        with self._lock:
            for item in self._definitions.values():
                if item.key == key:
                    return item
            return None

    def create_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord:
        with self._lock:
            if any(item.key == record.key for item in self._definitions.values()):
                raise SubjectAttributeKeyDuplicate()
            self._definitions[record.id] = record
            return record

    def update_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord:
        with self._lock:
            self._definitions[record.id] = record
            return record

    def delete_definition(self, definition_id: str) -> bool:
        with self._lock:
            if self._definitions.pop(definition_id, None) is None:
                return False
            for values in self._values.values():
                values.pop(definition_id, None)
            return True

    def values_for(
        self, subject_type: SubjectType, subject_ids: Iterable[str]
    ) -> dict[str, StoredValues]:
        with self._lock:
            return {
                subject_id: dict(self._values.get((subject_type, subject_id), {}))
                for subject_id in subject_ids
            }

    def replace_values(
        self,
        subject_type: SubjectType,
        subject_id: str,
        values: Mapping[str, tuple[str, ...]],
    ) -> None:
        with self._lock:
            self._values[(subject_type, subject_id)] = {
                key: tuple(items) for key, items in values.items() if items
            }


class SqlSubjectStore:
    def list_groups(
        self, *, q: str | None = None, limit: int | None = None, offset: int = 0
    ) -> tuple[list[UserGroupRecord], int]:
        with session_scope() as session:
            count_stmt = select(func.count()).select_from(UserGroupRow)
            stmt = select(UserGroupRow)
            if q:
                match = or_(
                    UserGroupRow.key.icontains(q, autoescape=True),
                    UserGroupRow.name.icontains(q, autoescape=True),
                )
                count_stmt = count_stmt.where(match)
                stmt = stmt.where(match)
            total = int(session.scalar(count_stmt) or 0)
            stmt = apply_sql_page(
                stmt.order_by(UserGroupRow.key, UserGroupRow.id),
                limit=limit,
                offset=offset,
            )
            return [_group(row) for row in session.scalars(stmt).all()], total

    def get_group(self, group_id: str) -> UserGroupRecord | None:
        with session_scope() as session:
            row = session.get(UserGroupRow, group_id)
            return _group(row) if row is not None else None

    def create_group(self, record: UserGroupRecord) -> UserGroupRecord:
        try:
            with session_scope() as session:
                existing = session.scalar(
                    select(UserGroupRow.id).where(UserGroupRow.key == record.key)
                )
                if existing is not None:
                    raise UserGroupKeyDuplicate()
                session.add(
                    UserGroupRow(
                        id=record.id,
                        key=record.key,
                        name=record.name,
                        description=record.description,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
                session.flush()
        except IntegrityError as exc:
            raise UserGroupKeyDuplicate() from exc
        return record

    def update_group(self, record: UserGroupRecord) -> UserGroupRecord:
        with session_scope() as session:
            row = session.get(UserGroupRow, record.id)
            if row is not None:
                row.name = record.name
                row.description = record.description
                row.updated_at = record.updated_at
            session.flush()
        return record

    def delete_group(self, group_id: str) -> bool:
        with session_scope() as session:
            row = session.get(UserGroupRow, group_id)
            if row is None:
                return False
            session.execute(
                delete(SubjectAttributeValueRow).where(
                    SubjectAttributeValueRow.subject_type == "group",
                    SubjectAttributeValueRow.subject_id == group_id,
                )
            )
            session.execute(
                delete(UserGroupMemberRow).where(UserGroupMemberRow.group_id == group_id)
            )
            session.delete(row)
            session.flush()
            return True

    def existing_group_ids(self, group_ids: Iterable[str]) -> frozenset[str]:
        wanted = list(set(group_ids))
        if not wanted:
            return frozenset()
        with session_scope() as session:
            return frozenset(
                session.scalars(
                    select(UserGroupRow.id).where(UserGroupRow.id.in_(wanted))
                ).all()
            )

    def member_counts(self, group_ids: Iterable[str]) -> dict[str, int]:
        wanted = list(set(group_ids))
        counts = {group_id: 0 for group_id in wanted}
        if not wanted:
            return counts
        with session_scope() as session:
            rows = session.execute(
                select(UserGroupMemberRow.group_id, func.count())
                .where(UserGroupMemberRow.group_id.in_(wanted))
                .group_by(UserGroupMemberRow.group_id)
            ).all()
        for group_id, count in rows:
            counts[group_id] = int(count)
        return counts

    def list_member_ids(
        self, group_id: str, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[str], int]:
        members = (
            select(UserGroupMemberRow.user_id)
            .join(UserRow, UserRow.id == UserGroupMemberRow.user_id)
            .where(UserGroupMemberRow.group_id == group_id)
        )
        with session_scope() as session:
            total = int(
                session.scalar(select(func.count()).select_from(members.subquery())) or 0
            )
            stmt = apply_sql_page(
                members.order_by(UserRow.account, UserRow.id),
                limit=limit,
                offset=offset,
            )
            return list(session.scalars(stmt).all()), total

    def add_member(self, group_id: str, user_id: str) -> None:
        with session_scope() as session:
            if session.get(UserGroupMemberRow, (group_id, user_id)) is None:
                session.add(
                    UserGroupMemberRow(
                        group_id=group_id, user_id=user_id, created_at=utc_now()
                    )
                )
            session.flush()

    def remove_member(self, group_id: str, user_id: str) -> None:
        with session_scope() as session:
            session.execute(
                delete(UserGroupMemberRow).where(
                    UserGroupMemberRow.group_id == group_id,
                    UserGroupMemberRow.user_id == user_id,
                )
            )

    def group_ids_of(self, user_id: str) -> list[str]:
        with session_scope() as session:
            return list(
                session.scalars(
                    select(UserGroupMemberRow.group_id).where(
                        UserGroupMemberRow.user_id == user_id
                    )
                ).all()
            )

    def replace_user_groups(self, user_id: str, group_ids: Iterable[str]) -> None:
        wanted = set(group_ids)
        now = utc_now()
        with session_scope() as session:
            session.execute(
                delete(UserGroupMemberRow).where(UserGroupMemberRow.user_id == user_id)
            )
            for group_id in sorted(wanted):
                session.add(
                    UserGroupMemberRow(group_id=group_id, user_id=user_id, created_at=now)
                )
            session.flush()

    def list_definitions(
        self, *, limit: int | None = None, offset: int = 0
    ) -> tuple[list[SubjectAttributeRecord], int]:
        with session_scope() as session:
            total = int(
                session.scalar(select(func.count()).select_from(SubjectAttributeDefRow))
                or 0
            )
            stmt = apply_sql_page(
                select(SubjectAttributeDefRow).order_by(
                    SubjectAttributeDefRow.key, SubjectAttributeDefRow.id
                ),
                limit=limit,
                offset=offset,
            )
            return [_definition(row) for row in session.scalars(stmt).all()], total

    def get_definition(self, definition_id: str) -> SubjectAttributeRecord | None:
        with session_scope() as session:
            row = session.get(SubjectAttributeDefRow, definition_id)
            return _definition(row) if row is not None else None

    def get_definition_by_key(self, key: str) -> SubjectAttributeRecord | None:
        with session_scope() as session:
            row = session.scalar(
                select(SubjectAttributeDefRow).where(SubjectAttributeDefRow.key == key)
            )
            return _definition(row) if row is not None else None

    def create_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord:
        try:
            with session_scope() as session:
                existing = session.scalar(
                    select(SubjectAttributeDefRow.id).where(
                        SubjectAttributeDefRow.key == record.key
                    )
                )
                if existing is not None:
                    raise SubjectAttributeKeyDuplicate()
                session.add(
                    SubjectAttributeDefRow(
                        id=record.id,
                        key=record.key,
                        name=record.name,
                        description=record.description,
                        value_type=record.value_type,
                        dictionary_id=record.dictionary_id,
                        multi_value=record.multi_value,
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
                session.flush()
        except IntegrityError as exc:
            raise SubjectAttributeKeyDuplicate() from exc
        return record

    def update_definition(self, record: SubjectAttributeRecord) -> SubjectAttributeRecord:
        with session_scope() as session:
            row = session.get(SubjectAttributeDefRow, record.id)
            if row is not None:
                row.name = record.name
                row.description = record.description
                row.multi_value = record.multi_value
                row.updated_at = record.updated_at
            session.flush()
        return record

    def delete_definition(self, definition_id: str) -> bool:
        with session_scope() as session:
            row = session.get(SubjectAttributeDefRow, definition_id)
            if row is None:
                return False
            session.execute(
                delete(SubjectAttributeValueRow).where(
                    SubjectAttributeValueRow.definition_id == definition_id
                )
            )
            session.delete(row)
            session.flush()
            return True

    def values_for(
        self, subject_type: SubjectType, subject_ids: Iterable[str]
    ) -> dict[str, StoredValues]:
        wanted = list(dict.fromkeys(subject_ids))
        out: dict[str, dict[str, list[str]]] = {subject_id: {} for subject_id in wanted}
        if not wanted:
            return {}
        with session_scope() as session:
            rows = session.scalars(
                select(SubjectAttributeValueRow)
                .where(
                    SubjectAttributeValueRow.subject_type == subject_type,
                    SubjectAttributeValueRow.subject_id.in_(wanted),
                )
                .order_by(
                    SubjectAttributeValueRow.subject_id,
                    SubjectAttributeValueRow.definition_id,
                    SubjectAttributeValueRow.position,
                )
            ).all()
            for row in rows:
                out[row.subject_id].setdefault(row.definition_id, []).append(row.value)
        return {
            subject_id: {key: tuple(items) for key, items in values.items()}
            for subject_id, values in out.items()
        }

    def replace_values(
        self,
        subject_type: SubjectType,
        subject_id: str,
        values: Mapping[str, tuple[str, ...]],
    ) -> None:
        with session_scope() as session:
            session.execute(
                delete(SubjectAttributeValueRow).where(
                    SubjectAttributeValueRow.subject_type == subject_type,
                    SubjectAttributeValueRow.subject_id == subject_id,
                )
            )
            for definition_id, items in values.items():
                for position, value in enumerate(items):
                    session.add(
                        SubjectAttributeValueRow(
                            definition_id=definition_id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                            value=value,
                            position=position,
                        )
                    )
            session.flush()


def _group(row: UserGroupRow) -> UserGroupRecord:
    return UserGroupRecord(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _definition(row: SubjectAttributeDefRow) -> SubjectAttributeRecord:
    return SubjectAttributeRecord(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        value_type=row.value_type,  # type: ignore[arg-type]
        dictionary_id=row.dictionary_id,
        multi_value=row.multi_value,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_memory: MemorySubjectStore | None = None
_lock = threading.Lock()


@lru_cache
def get_subject_store() -> SubjectStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemorySubjectStore()
            return _memory
    return SqlSubjectStore()


def reset_subject_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_subject_store.cache_clear()
