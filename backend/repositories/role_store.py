"""In-memory Role repository for the Management Foundation."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from backend.admin.permissions import ALL_PERMISSIONS, normalize_permissions

ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPER_ADMIN_KEY = "super_admin"
OPERATOR_KEY = "operator"


@dataclass
class RoleRecord:
    id: str
    key: str
    name: str
    permissions: list[str]
    locked: bool = False
    created_at: float = field(default_factory=time.time)


class RoleStore:
    def __init__(self) -> None:
        self._by_id: dict[str, RoleRecord] = {}
        self._by_key: dict[str, str] = {}
        self._lock = threading.Lock()

    def seed_defaults(self) -> None:
        with self._lock:
            if self._by_id:
                return
            self._insert_locked(
                RoleRecord(
                    id="role_super_admin",
                    key=SUPER_ADMIN_KEY,
                    name="Super Admin",
                    permissions=list(ALL_PERMISSIONS),
                    locked=True,
                )
            )
            self._insert_locked(
                RoleRecord(
                    id="role_operator",
                    key=OPERATOR_KEY,
                    name="Operator",
                    permissions=["console:access", "dashboard:read"],
                    locked=False,
                )
            )

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


_store_singleton: RoleStore | None = None
_store_lock = threading.Lock()


def get_role_store() -> RoleStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = RoleStore()
            _store_singleton.seed_defaults()
        return _store_singleton


def reset_role_store() -> None:
    global _store_singleton
    with _store_lock:
        _store_singleton = None
