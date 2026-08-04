"""Role repository ports and adapters for the Management Foundation."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from backend.admin.permissions import ALL_PERMISSIONS, normalize_permissions
from backend.core.config import get_settings

ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPER_ADMIN_KEY = "super_admin"
SUPER_ADMIN_ID = "role_super_admin"
SUPER_ADMIN_NAME = "Super Admin"
OPERATOR_KEY = "operator"
OPERATOR_ID = "role_operator"
OPERATOR_NAME = "Operator"
OPERATOR_DEFAULT_PERMISSIONS: tuple[str, ...] = ("console:access", "dashboard:read")


@dataclass
class RoleRecord:
    id: str
    key: str
    name: str
    permissions: list[str]
    locked: bool = False
    created_at: float = field(default_factory=time.time)


class RoleStore(Protocol):
    def seed_defaults(self) -> None: ...

    def ensure_super_admin(self) -> RoleRecord: ...

    def count(self) -> int: ...

    def get_by_id(self, role_id: str) -> RoleRecord | None: ...

    def get_by_key(self, key: str) -> RoleRecord | None: ...

    def list_roles(self) -> list[RoleRecord]: ...

    def create_role(
        self,
        *,
        key: str,
        name: str,
        permissions: list[str],
    ) -> RoleRecord: ...

    def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
    ) -> RoleRecord | None: ...

    def delete_role(self, role_id: str) -> RoleRecord | None: ...


class MemoryRoleStore:
    def __init__(self) -> None:
        self._by_id: dict[str, RoleRecord] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def seed_defaults(self) -> None:
        """Site Bootstrap: insert seed roles only when the store is empty."""
        with self._lock:
            if self._by_id:
                return
            self._insert_locked(
                RoleRecord(
                    id=SUPER_ADMIN_ID,
                    key=SUPER_ADMIN_KEY,
                    name=SUPER_ADMIN_NAME,
                    permissions=list(ALL_PERMISSIONS),
                    locked=True,
                )
            )
            self._insert_locked(
                RoleRecord(
                    id=OPERATOR_ID,
                    key=OPERATOR_KEY,
                    name=OPERATOR_NAME,
                    permissions=list(OPERATOR_DEFAULT_PERMISSIONS),
                    locked=False,
                )
            )

    def ensure_super_admin(self) -> RoleRecord:
        """Foundation Upgrade path: upsert locked System Role to full catalog."""
        with self._lock:
            role_id = self._by_key.get(SUPER_ADMIN_KEY)
            if role_id is None:
                record = RoleRecord(
                    id=SUPER_ADMIN_ID,
                    key=SUPER_ADMIN_KEY,
                    name=SUPER_ADMIN_NAME,
                    permissions=list(ALL_PERMISSIONS),
                    locked=True,
                )
                self._insert_locked(record)
                return record
            record = self._by_id[role_id]
            record.name = SUPER_ADMIN_NAME
            record.permissions = list(ALL_PERMISSIONS)
            record.locked = True
            return record

    def _insert_locked(self, record: RoleRecord) -> None:
        self._by_id[record.id] = record
        self._by_key[record.key] = record.id

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

    def create_role(
        self,
        *,
        key: str,
        name: str,
        permissions: list[str],
    ) -> RoleRecord:
        from backend.admin.errors import RoleInvalidKey, RoleKeyDuplicate

        if not ROLE_KEY_RE.match(key):
            raise RoleInvalidKey()
        normalized = normalize_permissions(permissions)
        with self._lock:
            if key in self._by_key:
                raise RoleKeyDuplicate()
            role_id = f"role_{uuid.uuid4().hex[:12]}"
            record = RoleRecord(
                id=role_id,
                key=key,
                name=name,
                permissions=normalized,
                locked=False,
            )
            self._insert_locked(record)
            return record

    def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
    ) -> RoleRecord | None:
        from backend.admin.errors import RoleLocked

        with self._lock:
            record = self._by_id.get(role_id)
            if record is None:
                return None
            if record.locked:
                raise RoleLocked()
            if name is not None:
                record.name = name
            if permissions is not None:
                record.permissions = normalize_permissions(permissions)
            return record

    def delete_role(self, role_id: str) -> RoleRecord | None:
        from backend.admin.errors import RoleLocked

        with self._lock:
            record = self._by_id.get(role_id)
            if record is None:
                return None
            if record.locked:
                raise RoleLocked()
            self._by_id.pop(role_id, None)
            self._by_key.pop(record.key, None)
            return record


class SqlRoleStore:
    def seed_defaults(self) -> None:
        """Site Bootstrap: insert seed roles only when the store is empty."""
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy import select

        with session_scope() as session:
            existing = session.scalar(select(RoleRow.id).limit(1))
            if existing is not None:
                return
            now = time.time()
            session.add(
                RoleRow(
                    id=SUPER_ADMIN_ID,
                    key=SUPER_ADMIN_KEY,
                    name=SUPER_ADMIN_NAME,
                    permissions=list(ALL_PERMISSIONS),
                    locked=True,
                    created_at=now,
                )
            )
            session.add(
                RoleRow(
                    id=OPERATOR_ID,
                    key=OPERATOR_KEY,
                    name=OPERATOR_NAME,
                    permissions=list(OPERATOR_DEFAULT_PERMISSIONS),
                    locked=False,
                    created_at=now,
                )
            )

    def ensure_super_admin(self) -> RoleRecord:
        """Foundation Upgrade path: upsert locked System Role to full catalog."""
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy import select

        with session_scope() as session:
            row = session.scalar(select(RoleRow).where(RoleRow.key == SUPER_ADMIN_KEY))
            if row is None:
                row = RoleRow(
                    id=SUPER_ADMIN_ID,
                    key=SUPER_ADMIN_KEY,
                    name=SUPER_ADMIN_NAME,
                    permissions=list(ALL_PERMISSIONS),
                    locked=True,
                    created_at=time.time(),
                )
                session.add(row)
            else:
                row.name = SUPER_ADMIN_NAME
                row.permissions = list(ALL_PERMISSIONS)
                row.locked = True
            session.flush()
            return _row_to_role(row)

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

    def create_role(
        self,
        *,
        key: str,
        name: str,
        permissions: list[str],
    ) -> RoleRecord:
        from backend.admin.errors import RoleInvalidKey, RoleKeyDuplicate
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        if not ROLE_KEY_RE.match(key):
            raise RoleInvalidKey()
        normalized = normalize_permissions(permissions)
        role_id = f"role_{uuid.uuid4().hex[:12]}"
        created_at = time.time()
        try:
            with session_scope() as session:
                existing = session.scalar(select(RoleRow).where(RoleRow.key == key))
                if existing is not None:
                    raise RoleKeyDuplicate()
                row = RoleRow(
                    id=role_id,
                    key=key,
                    name=name,
                    permissions=normalized,
                    locked=False,
                    created_at=created_at,
                )
                session.add(row)
                session.flush()
                return _row_to_role(row)
        except IntegrityError as exc:
            raise RoleKeyDuplicate() from exc

    def update_role(
        self,
        role_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
    ) -> RoleRecord | None:
        from backend.admin.errors import RoleLocked
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            row = session.get(RoleRow, role_id)
            if row is None:
                return None
            if row.locked:
                raise RoleLocked()
            if name is not None:
                row.name = name
            if permissions is not None:
                row.permissions = normalize_permissions(permissions)
            session.flush()
            return _row_to_role(row)

    def delete_role(self, role_id: str) -> RoleRecord | None:
        from backend.admin.errors import RoleLocked
        from backend.core.db import session_scope
        from backend.admin.models import RoleRow

        with session_scope() as session:
            row = session.get(RoleRow, role_id)
            if row is None:
                return None
            if row.locked:
                raise RoleLocked()
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
                _memory_singleton.seed_defaults()
            return _memory_singleton
    return SqlRoleStore()


def reset_role_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_role_store.cache_clear()
