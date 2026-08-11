"""Role domain: System Role ensure, Site Bootstrap seed, and write invariants."""

from __future__ import annotations

import re
import uuid

from backend.admin.errors import RoleInvalidKey, RoleKeyDuplicate, RoleLocked
from backend.admin.permissions import ALL_PERMISSIONS, normalize_permissions
from backend.admin.role_store import RoleRecord, RoleStore

ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SUPER_ADMIN_KEY = "super_admin"
SUPER_ADMIN_ID = "role_super_admin"
SUPER_ADMIN_NAME = "Super Admin"
OPERATOR_KEY = "operator"
OPERATOR_ID = "role_operator"
OPERATOR_NAME = "Operator"
OPERATOR_DEFAULT_PERMISSIONS: tuple[str, ...] = ("console:access", "dashboard:read")


def effective_permissions(role: RoleRecord) -> list[str]:
    """Project authoritative permissions for a Role (ADR 0019).

    System Role `super_admin` is definitional full catalog; stored list is ignored.
    """
    if role.key == SUPER_ADMIN_KEY:
        return list(ALL_PERMISSIONS)
    return list(role.permissions)


def ensure_system_role(roles: RoleStore) -> RoleRecord:
    """Ensure the locked System Role `super_admin` identity row exists.

    Idempotent. Safe to re-run. Does not touch `permissions`, `operator`, or custom roles.
    """
    existing = roles.get_by_key(SUPER_ADMIN_KEY)
    if existing is None:
        record = RoleRecord(
            id=SUPER_ADMIN_ID,
            key=SUPER_ADMIN_KEY,
            name=SUPER_ADMIN_NAME,
            permissions=[],
            locked=True,
        )
        roles.insert(record)
        return record
    existing.name = SUPER_ADMIN_NAME
    existing.locked = True
    roles.save(existing)
    return existing


def seed_roles(roles: RoleStore) -> None:
    """Site Bootstrap: insert seed roles only when the store is empty."""
    if roles.count() > 0:
        return
    roles.insert(
        RoleRecord(
            id=SUPER_ADMIN_ID,
            key=SUPER_ADMIN_KEY,
            name=SUPER_ADMIN_NAME,
            permissions=[],
            locked=True,
        )
    )
    roles.insert(
        RoleRecord(
            id=OPERATOR_ID,
            key=OPERATOR_KEY,
            name=OPERATOR_NAME,
            permissions=list(OPERATOR_DEFAULT_PERMISSIONS),
            locked=False,
        )
    )


def create_role(
    roles: RoleStore,
    *,
    key: str,
    name: str,
    permissions: list[str],
) -> RoleRecord:
    if not ROLE_KEY_RE.match(key):
        raise RoleInvalidKey()
    if roles.get_by_key(key) is not None:
        raise RoleKeyDuplicate()
    record = RoleRecord(
        id=f"role_{uuid.uuid4().hex[:12]}",
        key=key,
        name=name,
        permissions=normalize_permissions(permissions),
        locked=False,
    )
    roles.insert(record)
    return record


def update_role(
    roles: RoleStore,
    role_id: str,
    *,
    name: str | None = None,
    permissions: list[str] | None = None,
) -> RoleRecord | None:
    record = roles.get_by_id(role_id)
    if record is None:
        return None
    if record.locked:
        raise RoleLocked()
    if name is not None:
        record.name = name
    if permissions is not None:
        record.permissions = normalize_permissions(permissions)
    roles.save(record)
    return record


def delete_role(roles: RoleStore, role_id: str) -> RoleRecord | None:
    record = roles.get_by_id(role_id)
    if record is None:
        return None
    if record.locked:
        raise RoleLocked()
    return roles.delete(role_id)
