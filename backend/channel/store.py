"""Data Channel store ports and adapters."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.channel.errors import ChannelDraftConflict, ChannelNotFound
from backend.channel.models import ChannelRow, ChannelVersionRow
from backend.core.config import get_settings
from backend.core.db import session_scope

__all__ = [
    "ChannelRecord",
    "ChannelStore",
    "ChannelVersionRecord",
    "MemoryChannelStore",
    "SqlChannelStore",
    "empty_graph",
    "get_channel_store",
    "reset_channel_store",
]


def empty_graph() -> dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }


@dataclass
class ChannelRecord:
    id: str
    name: str
    description: str | None
    active: bool
    draft_graph: dict[str, Any]
    draft_revision: int
    draft_updated_at: datetime
    created_at: datetime
    updated_at: datetime
    failure_streak: int = 0


@dataclass
class ChannelVersionRecord:
    channel_id: str
    number: int
    graph: dict[str, Any]
    published_at: datetime
    published_by_user_id: str


class ChannelStore(Protocol):
    def create(
        self,
        record: ChannelRecord,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> ChannelRecord: ...

    def get(self, channel_id: str) -> ChannelRecord | None: ...

    def list_channels(
        self,
        *,
        q: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChannelRecord], int]: ...

    def save(self, record: ChannelRecord) -> ChannelRecord: ...

    def delete(
        self,
        channel_id: str,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> bool: ...

    def replace_draft(
        self,
        channel_id: str,
        *,
        base_revision: int,
        graph: dict[str, Any],
        now: datetime,
    ) -> ChannelRecord: ...

    def publish_version(
        self,
        channel_id: str,
        *,
        draft_revision: int,
        published_at: datetime,
        published_by_user_id: str,
    ) -> ChannelVersionRecord: ...

    def latest_versions(
        self, channel_ids: list[str]
    ) -> dict[str, tuple[int, datetime]]: ...

    def list_versions(
        self, channel_id: str, *, limit: int, offset: int
    ) -> tuple[list[ChannelVersionRecord], int]: ...

    def get_version(
        self, channel_id: str, number: int
    ) -> ChannelVersionRecord | None: ...


def _clone_channel(record: ChannelRecord) -> ChannelRecord:
    return ChannelRecord(
        id=record.id,
        name=record.name,
        description=record.description,
        active=record.active,
        draft_graph=copy.deepcopy(record.draft_graph),
        draft_revision=record.draft_revision,
        draft_updated_at=record.draft_updated_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        failure_streak=record.failure_streak,
    )


def _clone_version(record: ChannelVersionRecord) -> ChannelVersionRecord:
    return ChannelVersionRecord(
        channel_id=record.channel_id,
        number=record.number,
        graph=copy.deepcopy(record.graph),
        published_at=record.published_at,
        published_by_user_id=record.published_by_user_id,
    )


class MemoryChannelStore:
    def __init__(self) -> None:
        self._channels: dict[str, ChannelRecord] = {}
        self._versions: dict[tuple[str, int], ChannelVersionRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        record: ChannelRecord,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> ChannelRecord:
        with self._lock:
            self._channels[record.id] = _clone_channel(record)
            if after is not None:
                try:
                    after(None)
                except Exception:
                    self._channels.pop(record.id, None)
                    raise
            return _clone_channel(self._channels[record.id])

    def get(self, channel_id: str) -> ChannelRecord | None:
        with self._lock:
            record = self._channels.get(channel_id)
            return None if record is None else _clone_channel(record)

    def list_channels(
        self,
        *,
        q: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChannelRecord], int]:
        with self._lock:
            rows = list(self._channels.values())
        needle = (q or "").strip()
        if needle:
            folded = needle.lower()
            rows = [row for row in rows if folded in row.name.lower()]
        if active is not None:
            rows = [row for row in rows if row.active is active]
        rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        return [_clone_channel(row) for row in page], total

    def save(self, record: ChannelRecord) -> ChannelRecord:
        with self._lock:
            if record.id not in self._channels:
                raise ChannelNotFound()
            self._channels[record.id] = _clone_channel(record)
            return _clone_channel(self._channels[record.id])

    @contextmanager
    def lock_channel(
        self, channel_id: str
    ) -> Iterator[tuple[Session | None, ChannelRecord | None]]:
        with self._lock:
            record = self._channels.get(channel_id)
            yield None, None if record is None else _clone_channel(record)

    def delete(
        self,
        channel_id: str,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> bool:
        with self._lock:
            existing = self._channels.pop(channel_id, None)
            if existing is None:
                return False
            removed = {
                key: self._versions.pop(key)
                for key in [key for key in self._versions if key[0] == channel_id]
            }
            if after is not None:
                try:
                    after(None)
                except Exception:
                    self._channels[channel_id] = existing
                    self._versions.update(removed)
                    raise
            return True

    def replace_draft(
        self,
        channel_id: str,
        *,
        base_revision: int,
        graph: dict[str, Any],
        now: datetime,
    ) -> ChannelRecord:
        with self._lock:
            record = self._channels.get(channel_id)
            if record is None:
                raise ChannelNotFound()
            if record.draft_revision != base_revision:
                raise ChannelDraftConflict()
            record.draft_graph = copy.deepcopy(graph)
            record.draft_revision += 1
            record.draft_updated_at = now
            record.updated_at = now
            return _clone_channel(record)

    def publish_version(
        self,
        channel_id: str,
        *,
        draft_revision: int,
        published_at: datetime,
        published_by_user_id: str,
    ) -> ChannelVersionRecord:
        with self._lock:
            record = self._channels.get(channel_id)
            if record is None:
                raise ChannelNotFound()
            if record.draft_revision != draft_revision:
                raise ChannelDraftConflict()
            numbers = [
                number for (cid, number) in self._versions if cid == channel_id
            ]
            number = (max(numbers) if numbers else 0) + 1
            version = ChannelVersionRecord(
                channel_id=channel_id,
                number=number,
                graph=copy.deepcopy(record.draft_graph),
                published_at=published_at,
                published_by_user_id=published_by_user_id,
            )
            self._versions[(channel_id, number)] = version
            record.updated_at = published_at
            return _clone_version(version)

    def latest_versions(
        self, channel_ids: list[str]
    ) -> dict[str, tuple[int, datetime]]:
        wanted = set(channel_ids)
        best: dict[str, ChannelVersionRecord] = {}
        with self._lock:
            versions = list(self._versions.values())
        for version in versions:
            if version.channel_id not in wanted:
                continue
            current = best.get(version.channel_id)
            if current is None or version.number > current.number:
                best[version.channel_id] = version
        return {
            channel_id: (version.number, version.published_at)
            for channel_id, version in best.items()
        }

    def list_versions(
        self, channel_id: str, *, limit: int, offset: int
    ) -> tuple[list[ChannelVersionRecord], int]:
        with self._lock:
            rows = [
                version
                for version in self._versions.values()
                if version.channel_id == channel_id
            ]
        rows.sort(key=lambda version: version.number, reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        return [_clone_version(row) for row in page], total

    def get_version(
        self, channel_id: str, number: int
    ) -> ChannelVersionRecord | None:
        with self._lock:
            record = self._versions.get((channel_id, number))
            return None if record is None else _clone_version(record)


def _channel_from_row(row: ChannelRow) -> ChannelRecord:
    return ChannelRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        active=bool(row.active),
        draft_graph=copy.deepcopy(dict(row.draft_graph)),
        draft_revision=int(row.draft_revision),
        draft_updated_at=row.draft_updated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        failure_streak=int(row.failure_streak),
    )


def _version_from_row(row: ChannelVersionRow) -> ChannelVersionRecord:
    return ChannelVersionRecord(
        channel_id=row.channel_id,
        number=int(row.number),
        graph=copy.deepcopy(dict(row.graph)),
        published_at=row.published_at,
        published_by_user_id=row.published_by_user_id,
    )


class SqlChannelStore:
    def create(
        self,
        record: ChannelRecord,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> ChannelRecord:
        with session_scope() as session:
            session.add(
                ChannelRow(
                    id=record.id,
                    name=record.name,
                    description=record.description,
                    active=record.active,
                    draft_graph=copy.deepcopy(record.draft_graph),
                    draft_revision=record.draft_revision,
                    draft_updated_at=record.draft_updated_at,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                    failure_streak=record.failure_streak,
                )
            )
            session.flush()
            if after is not None:
                after(session)
            return _clone_channel(record)

    def get(self, channel_id: str) -> ChannelRecord | None:
        with session_scope() as session:
            row = session.get(ChannelRow, channel_id)
            return None if row is None else _channel_from_row(row)

    def list_channels(
        self,
        *,
        q: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ChannelRecord], int]:
        with session_scope() as session:
            stmt = select(ChannelRow)
            needle = (q or "").strip()
            if needle:
                stmt = stmt.where(ChannelRow.name.icontains(needle, autoescape=True))
            if active is not None:
                stmt = stmt.where(ChannelRow.active.is_(active))
            total = int(
                session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            rows = session.scalars(
                stmt.order_by(ChannelRow.created_at.desc(), ChannelRow.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return [_channel_from_row(row) for row in rows], total

    def save(self, record: ChannelRecord) -> ChannelRecord:
        with session_scope() as session:
            row = session.get(ChannelRow, record.id)
            if row is None:
                raise ChannelNotFound()
            row.name = record.name
            row.description = record.description
            row.active = record.active
            row.failure_streak = record.failure_streak
            row.updated_at = record.updated_at
            session.flush()
            return _channel_from_row(row)

    @contextmanager
    def lock_channel(
        self, channel_id: str
    ) -> Iterator[tuple[Session | None, ChannelRecord | None]]:
        with session_scope() as session:
            row = session.get(ChannelRow, channel_id, with_for_update=True)
            yield session, None if row is None else _channel_from_row(row)

    def delete(
        self,
        channel_id: str,
        *,
        after: Callable[[Session | None], None] | None = None,
    ) -> bool:
        with session_scope() as session:
            row = session.get(ChannelRow, channel_id)
            if row is None:
                return False
            session.delete(row)
            if after is not None:
                after(session)
            return True

    def replace_draft(
        self,
        channel_id: str,
        *,
        base_revision: int,
        graph: dict[str, Any],
        now: datetime,
    ) -> ChannelRecord:
        with session_scope() as session:
            row = _locked_channel(session, channel_id)
            if row.draft_revision != base_revision:
                raise ChannelDraftConflict()
            row.draft_graph = copy.deepcopy(graph)
            row.draft_revision = int(row.draft_revision) + 1
            row.draft_updated_at = now
            row.updated_at = now
            session.flush()
            return _channel_from_row(row)

    def publish_version(
        self,
        channel_id: str,
        *,
        draft_revision: int,
        published_at: datetime,
        published_by_user_id: str,
    ) -> ChannelVersionRecord:
        with session_scope() as session:
            row = _locked_channel(session, channel_id)
            if row.draft_revision != draft_revision:
                raise ChannelDraftConflict()
            current = session.scalar(
                select(func.max(ChannelVersionRow.number)).where(
                    ChannelVersionRow.channel_id == channel_id
                )
            )
            number = int(current or 0) + 1
            version = ChannelVersionRow(
                channel_id=channel_id,
                number=number,
                graph=copy.deepcopy(dict(row.draft_graph)),
                published_at=published_at,
                published_by_user_id=published_by_user_id,
            )
            session.add(version)
            row.updated_at = published_at
            session.flush()
            return _version_from_row(version)

    def latest_versions(
        self, channel_ids: list[str]
    ) -> dict[str, tuple[int, datetime]]:
        if not channel_ids:
            return {}
        with session_scope() as session:
            rows = session.execute(
                select(
                    ChannelVersionRow.channel_id,
                    ChannelVersionRow.number,
                    ChannelVersionRow.published_at,
                )
                .where(ChannelVersionRow.channel_id.in_(channel_ids))
                .distinct(ChannelVersionRow.channel_id)
                .order_by(
                    ChannelVersionRow.channel_id,
                    ChannelVersionRow.number.desc(),
                )
            ).all()
        return {
            str(channel_id): (int(number), published_at)
            for channel_id, number, published_at in rows
        }

    def list_versions(
        self, channel_id: str, *, limit: int, offset: int
    ) -> tuple[list[ChannelVersionRecord], int]:
        with session_scope() as session:
            stmt = select(ChannelVersionRow).where(
                ChannelVersionRow.channel_id == channel_id
            )
            total = int(
                session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            )
            rows = session.scalars(
                stmt.order_by(ChannelVersionRow.number.desc()).limit(limit).offset(offset)
            ).all()
            return [_version_from_row(row) for row in rows], total

    def get_version(
        self, channel_id: str, number: int
    ) -> ChannelVersionRecord | None:
        with session_scope() as session:
            row = session.get(ChannelVersionRow, (channel_id, number))
            return None if row is None else _version_from_row(row)


def _locked_channel(session: Session, channel_id: str) -> ChannelRow:
    row = session.scalar(
        select(ChannelRow).where(ChannelRow.id == channel_id).with_for_update()
    )
    if row is None:
        raise ChannelNotFound()
    return row


_memory_singleton: MemoryChannelStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_channel_store() -> MemoryChannelStore | SqlChannelStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryChannelStore()
            return _memory_singleton
    return SqlChannelStore()


def reset_channel_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_channel_store.cache_clear()
