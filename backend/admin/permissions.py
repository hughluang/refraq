"""Permission catalog and evaluation for the Management Foundation."""

from __future__ import annotations

from typing import Literal

Permission = Literal[
    "console:access",
    "dashboard:read",
    "users:read",
    "users:write",
    "roles:read",
    "roles:write",
]

ALL_PERMISSIONS: tuple[Permission, ...] = (
    "console:access",
    "dashboard:read",
    "users:read",
    "users:write",
    "roles:read",
    "roles:write",
)

PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    "console:access": "Sign in to the Management Console",
    "dashboard:read": "View the console home",
    "users:read": "List and view users",
    "users:write": "Create users and change user status",
    "roles:read": "List roles and the permission catalog",
    "roles:write": "Create, update, and delete roles",
}

CATALOG_SET: frozenset[str] = frozenset(ALL_PERMISSIONS)


def is_known_permission(permission: str) -> bool:
    return permission in CATALOG_SET


def normalize_permissions(permissions: list[str]) -> list[str]:
    """Deduplicate while preserving catalog order; reject unknown keys."""
    from backend.admin.errors import RoleInvalidPermission

    seen: set[str] = set()
    ordered: list[str] = []
    for key in permissions:
        if not is_known_permission(key):
            raise RoleInvalidPermission()
        if key in seen:
            continue
        seen.add(key)
    for key in ALL_PERMISSIONS:
        if key in seen:
            ordered.append(key)
    return ordered


def permissions_include(permissions: list[str] | tuple[str, ...], permission: str) -> bool:
    return permission in permissions
