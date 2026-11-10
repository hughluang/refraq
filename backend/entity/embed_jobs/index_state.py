"""Entity-owned index readiness, coverage, and rebuild intent."""

from __future__ import annotations

import threading
from dataclasses import replace
from functools import lru_cache
from typing import Protocol

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.admin.model_services import get_embedding_runtime
from backend.admin.model_services.records import EntityIndexView
from backend.core.config import get_settings
from backend.core.db import Base, session_scope

ENTITY_INDEX_ID = "entity"


class EntityIndexStateRow(Base):
    """One Entity index. Ready is not Catalog ready and not model health."""

    __tablename__ = "entity_index_state"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    written: Mapped[int] = mapped_column(Integer, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, nullable=False)
    attempted: Mapped[int] = mapped_column(Integer, nullable=False)
    progress: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rebuild_owed: Mapped[bool] = mapped_column(Boolean, nullable=False)


class EntityIndexStore(Protocol):
    def get(self) -> EntityIndexView: ...

    def save(self, state: EntityIndexView) -> EntityIndexView: ...


def _row_to_view(row: EntityIndexStateRow) -> EntityIndexView:
    return EntityIndexView(
        ready=row.ready,
        generation=row.generation,
        written=row.written,
        failed=row.failed,
        attempted=row.attempted,
        progress=row.progress,
        failure_summary=row.failure_summary,
        rebuild_owed=row.rebuild_owed,
    )


def _apply(row: EntityIndexStateRow, state: EntityIndexView) -> None:
    row.ready = state.ready
    row.generation = state.generation
    row.written = state.written
    row.failed = state.failed
    row.attempted = state.attempted
    row.progress = state.progress
    row.failure_summary = state.failure_summary
    row.rebuild_owed = state.rebuild_owed


class MemoryEntityIndexStore:
    def __init__(self) -> None:
        self._state = EntityIndexView()
        self._lock = threading.Lock()

    def get(self) -> EntityIndexView:
        with self._lock:
            return self._state

    def save(self, state: EntityIndexView) -> EntityIndexView:
        with self._lock:
            self._state = state
            return state


class SqlEntityIndexStore:
    def get(self) -> EntityIndexView:
        with session_scope() as session:
            row = session.get(EntityIndexStateRow, ENTITY_INDEX_ID)
            if row is None:
                return EntityIndexView()
            return _row_to_view(row)

    def save(self, state: EntityIndexView) -> EntityIndexView:
        with session_scope() as session:
            row = session.get(EntityIndexStateRow, ENTITY_INDEX_ID)
            if row is None:
                row = EntityIndexStateRow(id=ENTITY_INDEX_ID, ready=False)
                _apply(row, state)
                session.add(row)
            else:
                _apply(row, state)
            session.flush()
            return state


_memory: MemoryEntityIndexStore | None = None
_lock = threading.Lock()


@lru_cache
def get_entity_index_store() -> EntityIndexStore:
    if get_settings().store_backend == "memory":
        global _memory
        with _lock:
            if _memory is None:
                _memory = MemoryEntityIndexStore()
            return _memory
    return SqlEntityIndexStore()


def reset_entity_index_store() -> None:
    global _memory
    with _lock:
        _memory = None
    get_entity_index_store.cache_clear()


def publish_entity_index(
    *,
    generation: int,
    control_revision: int,
    written: int = 0,
    failed: int = 0,
    attempted: int = 0,
    progress: str | None = None,
    failure_summary: str | None = None,
) -> bool:
    """Mark this generation ready when the captured fence still matches."""

    runtime = get_embedding_runtime()
    if (
        runtime is None
        or runtime.closed
        or runtime.generation != generation
        or runtime.control_revision != control_revision
    ):
        return False
    get_entity_index_store().save(
        EntityIndexView(
            ready=True,
            generation=generation,
            written=written,
            failed=failed,
            attempted=attempted,
            progress=progress,
            failure_summary=failure_summary,
            rebuild_owed=False,
        )
    )
    return True


def clear_entity_index_ready(*, rebuild_owed: bool) -> EntityIndexView:
    current = get_entity_index_store().get()
    return get_entity_index_store().save(
        replace(current, ready=False, rebuild_owed=rebuild_owed)
    )


def note_entity_index_gap(
    *,
    written: int,
    failed: int,
    attempted: int,
    failure_summary: str,
    keep_ready: bool,
) -> EntityIndexView:
    """Record a sweep that left a coverage gap.

    ``keep_ready`` is the post-ready incremental case: ready stays, and the
    summary shows which current targets are missing.
    """

    current = get_entity_index_store().get()
    return get_entity_index_store().save(
        replace(
            current,
            ready=current.ready if keep_ready else False,
            written=written,
            failed=failed,
            attempted=attempted,
            progress=failure_summary,
            failure_summary=failure_summary,
            rebuild_owed=False if keep_ready else True,
        )
    )
