"""Access-policy store. Persistence only."""

from __future__ import annotations

import threading
from datetime import datetime
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.entity.access.errors import EntityAccessKeyDup
from backend.entity.access.models import (
    AccessGrantRow,
    AccessProfileRow,
    AccessRestrictionRow,
    EntityAccessLogRow,
    PolicyRevisionRow,
    PresentationLadderRow,
    ProfileViewBindingRow,
)
from backend.entity.access.records import (
    AccessLogRecord,
    BindingRecord,
    GrantRecord,
    LadderRecord,
    ProfileRecord,
    RestrictionRecord,
)

__all__ = [
    "AccessStore",
    "MemoryAccessStore",
    "SqlAccessStore",
    "get_access_store",
    "reset_access_store",
]

_TX: ContextVar[Session | None] = ContextVar("entity_access_tx", default=None)


class AccessStore(Protocol):
    def transaction(self) -> Iterator[Session | None]: ...

    def revision(self, entity_id: str) -> int: ...

    def set_revision(self, entity_id: str, revision: int) -> None: ...

    def views_revision(self, entity_id: str) -> int: ...

    def set_views_revision(self, entity_id: str, revision: int) -> None: ...

    def ladders(self, entity_id: str) -> list[LadderRecord]: ...

    def save_ladder(self, record: LadderRecord) -> None: ...

    def profiles(self, entity_id: str) -> list[ProfileRecord]: ...

    def profile(self, profile_id: str) -> ProfileRecord | None: ...

    def profile_by_key(self, entity_id: str, key: str) -> ProfileRecord | None: ...

    def insert_profile(self, record: ProfileRecord) -> None: ...

    def update_profile(self, record: ProfileRecord) -> None: ...

    def delete_profile(self, profile_id: str) -> None: ...

    def grants(self, entity_id: str) -> list[GrantRecord]: ...

    def grant(self, grant_id: str) -> GrantRecord | None: ...

    def grants_for_profile(self, profile_id: str) -> list[GrantRecord]: ...

    def insert_grant(self, record: GrantRecord) -> None: ...

    def update_grant(self, record: GrantRecord) -> None: ...

    def delete_grant(self, grant_id: str) -> None: ...

    def restrictions(self, entity_id: str) -> list[RestrictionRecord]: ...

    def restriction(self, restriction_id: str) -> RestrictionRecord | None: ...

    def insert_restriction(self, record: RestrictionRecord) -> None: ...

    def update_restriction(self, record: RestrictionRecord) -> None: ...

    def delete_restriction(self, restriction_id: str) -> None: ...

    def bindings(self, entity_id: str) -> list[BindingRecord]: ...

    def replace_bindings(self, entity_id: str, records: list[BindingRecord]) -> None: ...

    def append_log(self, record: AccessLogRecord) -> None: ...

    def logs_for_entity(self, entity_id: str) -> list[AccessLogRecord]: ...

    def delete_logs_before(self, instant: datetime) -> int: ...


class MemoryAccessStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision: dict[str, int] = {}
        self._views_revision: dict[str, int] = {}
        self._ladders: dict[tuple[str, str], LadderRecord] = {}
        self._profiles: dict[str, ProfileRecord] = {}
        self._grants: dict[str, GrantRecord] = {}
        self._restrictions: dict[str, RestrictionRecord] = {}
        self._bindings: dict[tuple[str, str], BindingRecord] = {}
        self._logs: list[AccessLogRecord] = []

    @contextmanager
    def transaction(self) -> Iterator[Session | None]:
        with self._lock:
            yield None

    def revision(self, entity_id: str) -> int:
        with self._lock:
            return self._revision.get(entity_id, 0)

    def set_revision(self, entity_id: str, revision: int) -> None:
        with self._lock:
            self._revision[entity_id] = revision

    def views_revision(self, entity_id: str) -> int:
        with self._lock:
            return self._views_revision.get(entity_id, 0)

    def set_views_revision(self, entity_id: str, revision: int) -> None:
        with self._lock:
            self._views_revision[entity_id] = revision

    def ladders(self, entity_id: str) -> list[LadderRecord]:
        with self._lock:
            return [
                item for (owner, _attr), item in self._ladders.items() if owner == entity_id
            ]

    def save_ladder(self, record: LadderRecord) -> None:
        with self._lock:
            self._ladders[(record.entity_id, record.attribute_id)] = record

    def profiles(self, entity_id: str) -> list[ProfileRecord]:
        with self._lock:
            return [item for item in self._profiles.values() if item.entity_id == entity_id]

    def profile(self, profile_id: str) -> ProfileRecord | None:
        with self._lock:
            return self._profiles.get(profile_id)

    def profile_by_key(self, entity_id: str, key: str) -> ProfileRecord | None:
        with self._lock:
            for item in self._profiles.values():
                if item.entity_id == entity_id and item.key == key:
                    return item
            return None

    def insert_profile(self, record: ProfileRecord) -> None:
        with self._lock:
            if self.profile_by_key(record.entity_id, record.key) is not None:
                raise EntityAccessKeyDup()
            self._profiles[record.id] = record

    def update_profile(self, record: ProfileRecord) -> None:
        with self._lock:
            self._profiles[record.id] = record

    def delete_profile(self, profile_id: str) -> None:
        with self._lock:
            self._profiles.pop(profile_id, None)

    def grants(self, entity_id: str) -> list[GrantRecord]:
        with self._lock:
            return [item for item in self._grants.values() if item.entity_id == entity_id]

    def grant(self, grant_id: str) -> GrantRecord | None:
        with self._lock:
            return self._grants.get(grant_id)

    def grants_for_profile(self, profile_id: str) -> list[GrantRecord]:
        with self._lock:
            return [item for item in self._grants.values() if item.profile_id == profile_id]

    def insert_grant(self, record: GrantRecord) -> None:
        with self._lock:
            self._grants[record.id] = record

    def update_grant(self, record: GrantRecord) -> None:
        with self._lock:
            self._grants[record.id] = record

    def delete_grant(self, grant_id: str) -> None:
        with self._lock:
            self._grants.pop(grant_id, None)

    def restrictions(self, entity_id: str) -> list[RestrictionRecord]:
        with self._lock:
            return [
                item for item in self._restrictions.values() if item.entity_id == entity_id
            ]

    def restriction(self, restriction_id: str) -> RestrictionRecord | None:
        with self._lock:
            return self._restrictions.get(restriction_id)

    def insert_restriction(self, record: RestrictionRecord) -> None:
        with self._lock:
            self._restrictions[record.id] = record

    def update_restriction(self, record: RestrictionRecord) -> None:
        with self._lock:
            self._restrictions[record.id] = record

    def delete_restriction(self, restriction_id: str) -> None:
        with self._lock:
            self._restrictions.pop(restriction_id, None)

    def bindings(self, entity_id: str) -> list[BindingRecord]:
        with self._lock:
            return [
                item
                for (owner, _key), item in self._bindings.items()
                if owner == entity_id
            ]

    def replace_bindings(self, entity_id: str, records: list[BindingRecord]) -> None:
        with self._lock:
            for key in [item for item in self._bindings if item[0] == entity_id]:
                del self._bindings[key]
            for record in records:
                self._bindings[(record.entity_id, record.shape_key)] = record

    def append_log(self, record: AccessLogRecord) -> None:
        with self._lock:
            self._logs.append(record)

    def logs_for_entity(self, entity_id: str) -> list[AccessLogRecord]:
        with self._lock:
            return [item for item in self._logs if item.entity_id == entity_id]

    def delete_logs_before(self, instant: datetime) -> int:
        with self._lock:
            kept = [item for item in self._logs if item.created_at >= instant]
            removed = len(self._logs) - len(kept)
            self._logs = kept
            return removed


class SqlAccessStore:
    @contextmanager
    def transaction(self) -> Iterator[Session | None]:
        if _TX.get() is not None:
            yield _TX.get()
            return
        with session_scope() as session:
            token = _TX.set(session)
            try:
                yield session
            finally:
                _TX.reset(token)

    def _run(self, fn):
        current = _TX.get()
        if current is not None:
            return fn(current)
        with session_scope() as session:
            return fn(session)

    def revision(self, entity_id: str) -> int:
        def read(session: Session) -> int:
            row = session.get(PolicyRevisionRow, entity_id)
            return int(row.revision) if row is not None else 0

        return self._run(read)

    def set_revision(self, entity_id: str, revision: int) -> None:
        def write(session: Session) -> None:
            row = session.get(PolicyRevisionRow, entity_id)
            if row is None:
                session.add(
                    PolicyRevisionRow(
                        entity_id=entity_id, revision=revision, views_revision=0
                    )
                )
            else:
                row.revision = revision

        self._run(write)

    def views_revision(self, entity_id: str) -> int:
        def read(session: Session) -> int:
            row = session.get(PolicyRevisionRow, entity_id)
            return int(row.views_revision) if row is not None else 0

        return self._run(read)

    def set_views_revision(self, entity_id: str, revision: int) -> None:
        def write(session: Session) -> None:
            row = session.get(PolicyRevisionRow, entity_id)
            if row is None:
                session.add(
                    PolicyRevisionRow(
                        entity_id=entity_id, revision=0, views_revision=revision
                    )
                )
            else:
                row.views_revision = revision

        self._run(write)

    def ladders(self, entity_id: str) -> list[LadderRecord]:
        def read(session: Session) -> list[LadderRecord]:
            rows = session.scalars(
                select(PresentationLadderRow).where(
                    PresentationLadderRow.entity_id == entity_id
                )
            ).all()
            return [_ladder(row) for row in rows]

        return self._run(read)

    def save_ladder(self, record: LadderRecord) -> None:
        def write(session: Session) -> None:
            row = session.get(
                PresentationLadderRow, (record.entity_id, record.attribute_id)
            )
            if row is None:
                session.add(
                    PresentationLadderRow(
                        entity_id=record.entity_id,
                        attribute_id=record.attribute_id,
                        levels=list(record.levels),
                        updated_at=record.updated_at,
                    )
                )
            else:
                row.levels = list(record.levels)
                row.updated_at = record.updated_at

        self._run(write)

    def profiles(self, entity_id: str) -> list[ProfileRecord]:
        def read(session: Session) -> list[ProfileRecord]:
            rows = session.scalars(
                select(AccessProfileRow).where(AccessProfileRow.entity_id == entity_id)
            ).all()
            return [_profile(row) for row in rows]

        return self._run(read)

    def profile(self, profile_id: str) -> ProfileRecord | None:
        def read(session: Session) -> ProfileRecord | None:
            row = session.get(AccessProfileRow, profile_id)
            return _profile(row) if row is not None else None

        return self._run(read)

    def profile_by_key(self, entity_id: str, key: str) -> ProfileRecord | None:
        def read(session: Session) -> ProfileRecord | None:
            row = session.scalar(
                select(AccessProfileRow).where(
                    AccessProfileRow.entity_id == entity_id,
                    AccessProfileRow.key == key,
                )
            )
            return _profile(row) if row is not None else None

        return self._run(read)

    def insert_profile(self, record: ProfileRecord) -> None:
        def write(session: Session) -> None:
            session.add(_profile_row(record))

        try:
            self._run(write)
        except IntegrityError as exc:
            raise EntityAccessKeyDup() from exc

    def update_profile(self, record: ProfileRecord) -> None:
        def write(session: Session) -> None:
            row = session.get(AccessProfileRow, record.id)
            if row is None:
                return
            row.name = record.name
            row.description = record.description
            row.columns = list(record.columns)
            row.updated_at = record.updated_at

        self._run(write)

    def delete_profile(self, profile_id: str) -> None:
        def write(session: Session) -> None:
            session.execute(delete(AccessProfileRow).where(AccessProfileRow.id == profile_id))

        self._run(write)

    def grants(self, entity_id: str) -> list[GrantRecord]:
        def read(session: Session) -> list[GrantRecord]:
            rows = session.scalars(
                select(AccessGrantRow).where(AccessGrantRow.entity_id == entity_id)
            ).all()
            return [_grant(row) for row in rows]

        return self._run(read)

    def grant(self, grant_id: str) -> GrantRecord | None:
        def read(session: Session) -> GrantRecord | None:
            row = session.get(AccessGrantRow, grant_id)
            return _grant(row) if row is not None else None

        return self._run(read)

    def grants_for_profile(self, profile_id: str) -> list[GrantRecord]:
        def read(session: Session) -> list[GrantRecord]:
            rows = session.scalars(
                select(AccessGrantRow).where(AccessGrantRow.profile_id == profile_id)
            ).all()
            return [_grant(row) for row in rows]

        return self._run(read)

    def insert_grant(self, record: GrantRecord) -> None:
        self._run(lambda session: session.add(_grant_row(record)))

    def update_grant(self, record: GrantRecord) -> None:
        def write(session: Session) -> None:
            row = session.get(AccessGrantRow, record.id)
            if row is None:
                return
            row.profile_id = record.profile_id
            row.row_rule = record.row_rule
            row.actions = list(record.actions)
            row.status = record.status
            row.valid_until = record.valid_until
            row.updated_at = record.updated_at

        self._run(write)

    def delete_grant(self, grant_id: str) -> None:
        self._run(
            lambda session: session.execute(
                delete(AccessGrantRow).where(AccessGrantRow.id == grant_id)
            )
        )

    def restrictions(self, entity_id: str) -> list[RestrictionRecord]:
        def read(session: Session) -> list[RestrictionRecord]:
            rows = session.scalars(
                select(AccessRestrictionRow).where(
                    AccessRestrictionRow.entity_id == entity_id
                )
            ).all()
            return [_restriction(row) for row in rows]

        return self._run(read)

    def restriction(self, restriction_id: str) -> RestrictionRecord | None:
        def read(session: Session) -> RestrictionRecord | None:
            row = session.get(AccessRestrictionRow, restriction_id)
            return _restriction(row) if row is not None else None

        return self._run(read)

    def insert_restriction(self, record: RestrictionRecord) -> None:
        self._run(lambda session: session.add(_restriction_row(record)))

    def update_restriction(self, record: RestrictionRecord) -> None:
        def write(session: Session) -> None:
            row = session.get(AccessRestrictionRow, record.id)
            if row is None:
                return
            row.applies_to = dict(record.applies_to)
            row.row_rule = record.row_rule
            row.deny_columns = list(record.deny_columns)
            row.ceilings = list(record.ceilings)
            row.actions = list(record.actions)
            row.updated_at = record.updated_at

        self._run(write)

    def delete_restriction(self, restriction_id: str) -> None:
        self._run(
            lambda session: session.execute(
                delete(AccessRestrictionRow).where(
                    AccessRestrictionRow.id == restriction_id
                )
            )
        )

    def bindings(self, entity_id: str) -> list[BindingRecord]:
        def read(session: Session) -> list[BindingRecord]:
            rows = session.scalars(
                select(ProfileViewBindingRow).where(
                    ProfileViewBindingRow.entity_id == entity_id
                )
            ).all()
            return [_binding(row) for row in rows]

        return self._run(read)

    def replace_bindings(self, entity_id: str, records: list[BindingRecord]) -> None:
        def write(session: Session) -> None:
            session.execute(
                delete(ProfileViewBindingRow).where(
                    ProfileViewBindingRow.entity_id == entity_id
                )
            )
            session.add_all(_binding_row(item) for item in records)

        self._run(write)

    def append_log(self, record: AccessLogRecord) -> None:
        self._run(lambda session: session.add(_log_row(record)))

    def logs_for_entity(self, entity_id: str) -> list[AccessLogRecord]:
        def read(session: Session) -> list[AccessLogRecord]:
            rows = session.scalars(
                select(EntityAccessLogRow)
                .where(EntityAccessLogRow.entity_id == entity_id)
                .order_by(EntityAccessLogRow.created_at)
            ).all()
            return [_log(row) for row in rows]

        return self._run(read)

    def delete_logs_before(self, instant: datetime) -> int:
        def write(session: Session) -> int:
            result = session.execute(
                delete(EntityAccessLogRow).where(EntityAccessLogRow.created_at < instant)
            )
            return int(result.rowcount or 0)

        return self._run(write)


def _ladder(row: PresentationLadderRow) -> LadderRecord:
    return LadderRecord(
        entity_id=row.entity_id,
        attribute_id=row.attribute_id,
        levels=list(row.levels),
        updated_at=row.updated_at,
    )


def _profile(row: AccessProfileRow) -> ProfileRecord:
    return ProfileRecord(
        id=row.id,
        entity_id=row.entity_id,
        key=row.key,
        name=row.name,
        description=row.description,
        columns=list(row.columns),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _profile_row(record: ProfileRecord) -> AccessProfileRow:
    return AccessProfileRow(
        id=record.id,
        entity_id=record.entity_id,
        key=record.key,
        name=record.name,
        description=record.description,
        columns=list(record.columns),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _grant(row: AccessGrantRow) -> GrantRecord:
    return GrantRecord(
        id=row.id,
        entity_id=row.entity_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        profile_id=row.profile_id,
        row_rule=row.row_rule,
        actions=list(row.actions),
        status=row.status,
        valid_until=row.valid_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _grant_row(record: GrantRecord) -> AccessGrantRow:
    return AccessGrantRow(
        id=record.id,
        entity_id=record.entity_id,
        subject_type=record.subject_type,
        subject_id=record.subject_id,
        profile_id=record.profile_id,
        row_rule=record.row_rule,
        actions=list(record.actions),
        status=record.status,
        valid_until=record.valid_until,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _restriction(row: AccessRestrictionRow) -> RestrictionRecord:
    return RestrictionRecord(
        id=row.id,
        entity_id=row.entity_id,
        applies_to=dict(row.applies_to),
        row_rule=row.row_rule,
        deny_columns=list(row.deny_columns),
        ceilings=list(row.ceilings),
        actions=list(row.actions),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _restriction_row(record: RestrictionRecord) -> AccessRestrictionRow:
    return AccessRestrictionRow(
        id=record.id,
        entity_id=record.entity_id,
        applies_to=dict(record.applies_to),
        row_rule=record.row_rule,
        deny_columns=list(record.deny_columns),
        ceilings=list(record.ceilings),
        actions=list(record.actions),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _binding(row: ProfileViewBindingRow) -> BindingRecord:
    return BindingRecord(
        entity_id=row.entity_id,
        head_version_id=row.head_version_id,
        policy_revision=row.policy_revision,
        combo_key=row.combo_key,
        shape_key=row.shape_key,
        action=row.action,
        view_name=row.view_name,
        columns=list(row.columns),
        ddl_sha256=row.ddl_sha256,
        status=row.status,
        sql=row.sql,
    )


def _binding_row(record: BindingRecord) -> ProfileViewBindingRow:
    return ProfileViewBindingRow(
        entity_id=record.entity_id,
        shape_key=record.shape_key,
        head_version_id=record.head_version_id,
        policy_revision=record.policy_revision,
        combo_key=record.combo_key,
        action=record.action,
        view_name=record.view_name,
        columns=list(record.columns),
        ddl_sha256=record.ddl_sha256,
        status=record.status,
        sql=record.sql,
    )


def _log(row: EntityAccessLogRow) -> AccessLogRecord:
    return AccessLogRecord(
        id=row.id,
        created_at=row.created_at,
        user_id=row.user_id,
        pat_id=row.pat_id,
        request_id=row.request_id,
        entity_id=row.entity_id,
        verb=row.verb,
        effective_grant_ids=list(row.effective_grant_ids),
        narrowing=row.narrowing,
        view_name=row.view_name,
        policy_revision=row.policy_revision,
        row_count=row.row_count,
        outcome_code=row.outcome_code,
        preview_subject_user_id=row.preview_subject_user_id,
        duration_ms=row.duration_ms,
    )


def _log_row(record: AccessLogRecord) -> EntityAccessLogRow:
    return EntityAccessLogRow(
        id=record.id,
        created_at=record.created_at,
        user_id=record.user_id,
        pat_id=record.pat_id,
        request_id=record.request_id,
        entity_id=record.entity_id,
        verb=record.verb,
        effective_grant_ids=list(record.effective_grant_ids),
        narrowing=record.narrowing,
        view_name=record.view_name,
        policy_revision=record.policy_revision,
        row_count=record.row_count,
        outcome_code=record.outcome_code,
        preview_subject_user_id=record.preview_subject_user_id,
        duration_ms=record.duration_ms,
    )


_memory_singleton: MemoryAccessStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_access_store() -> MemoryAccessStore | SqlAccessStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryAccessStore()
            return _memory_singleton
    return SqlAccessStore()


def reset_access_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_access_store.cache_clear()
