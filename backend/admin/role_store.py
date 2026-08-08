"""Role repository ports and adapters for the Management Foundation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from backend.core.config import get_settings


@dataclass
class RoleRecord:
    id: str
    key: str
    name: str
    permissions: list[str]
    locked: bool = False
    created_at: float = field(default_factory=time.time)


class RoleStore(Protocol):
    def count(self) -> int: ...

    def get_by_id(self, role_id: str) -> RoleRecord | None: ...

    def get_by_key(self, key: str) -> RoleRecord | None: ...

    def list_roles(self) -> list[RoleRecord]: ...

    def insert(self, record: RoleRecord) -> None: ...

    def save(self, record: RoleRecord) -> None: ...

    def delete(self, role_id: str) -> RoleRecord | None: ...


class MemoryRoleStore:
    def __init__(self) -> None:
        self._by_id: dict[str, RoleRecord] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def get_by_id(self, role_id: str) -> RoleRecord | None:
        with self._lock:
            return self._by_id.get(role_id)

    def get_by_key(self, key: str) -> RoleRecord | None:
        with self._lock:
            role_id = self._by_key.get(key)
            if role_id is None:
                return None
            return self._by_id.get(role_id)

    def list_roles(self) -> list[RoleRecord]:
        with self._lock:
            return sorted(
                self._by_id.values(),
                key=lambda record: (0 if record.locked else 1, record.key),
            )

    def insert(self, record: RoleRecord) -> None:
        from backend.admin.errors import RoleKeyDuplicate

        with self._lock:
            if record.key in self._by_key or record.id in self._by_id:
                raise RoleKeyDuplicate()
            self._by_id[record.id] = record
            self._by_key[record.key] = record.id

    def save(self, record: RoleRecord) -> None:
        with self._lock:
            previous = self._by_id.get(record.id)
            if previous is None:
                return
            previous.name = record.name
            previous.permissions = record.permissions
            previous.locked = record.locked

    def delete(self, role_id: str) -> RoleRecord | None:
        with self._lock:
            record = self._by_id.pop(role_id, None)
            if record is None:
                return None
            self._by_key.pop(record.key, None)
            return record


class SqlRoleStore:
    def count(self) -> int:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            return session.query(RoleRow).count()

    def get_by_id(self, role_id: str) -> RoleRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            row = session.get(RoleRow, role_id)
            return _row_to_role(row) if row else None

    def get_by_key(self, key: str) -> RoleRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy import select

        with session_scope() as session:
            row = session.scalar(select(RoleRow).where(RoleRow.key == key))
            return _row_to_role(row) if row else None

    def list_roles(self) -> list[RoleRecord]:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy import select

        with session_scope() as session:
            rows = session.scalars(select(RoleRow)).all()
            records = [_row_to_role(row) for row in rows]
            return sorted(records, key=lambda record: (0 if record.locked else 1, record.key))

    def insert(self, record: RoleRecord) -> None:
        from backend.admin.errors import RoleKeyDuplicate
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy.exc import IntegrityError

        try:
            with session_scope() as session:
                session.add(
                    RoleRow(
                        id=record.id,
                        key=record.key,
                        name=record.name,
                        permissions=list(record.permissions),
                        locked=record.locked,
                        created_at=record.created_at,
                    )
                )
                session.flush()
        except IntegrityError as exc:
            raise RoleKeyDuplicate() from exc

    def save(self, record: RoleRecord) -> None:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            row = session.get(RoleRow, record.id)
            if row is None:
                return
            row.name = record.name
            row.permissions = list(record.permissions)
            row.locked = record.locked
            session.flush()

    def delete(self, role_id: str) -> RoleRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            row = session.get(RoleRow, role_id)
            if row is None:
                return None
            record = _row_to_role(row)
            session.delete(row)
            return record


def _row_to_role(row: object) -> RoleRecord:
    from backend.admin.models import RoleRow

    assert isinstance(row, RoleRow)
    return RoleRecord(
        id=row.id,
        key=row.key,
        name=row.name,
        permissions=list(row.permissions or []),
        locked=bool(row.locked),
        created_at=float(row.created_at),
    )


RoleStoreImpl = MemoryRoleStore

_memory_singleton: MemoryRoleStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_role_store() -> RoleStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryRoleStore()
            return _memory_singleton
    return SqlRoleStore()


def reset_role_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_role_store.cache_clear()
