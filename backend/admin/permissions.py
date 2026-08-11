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
    "settings:read",
    "settings:write",
    "sources:read",
    "sources:write",
    "metadata:read",
    "metadata:write",
    "jobs:run",
    "query:run",
    "catalog:sample",
    "tokens:read",
    "tokens:write",
    "audit:read",
]

ALL_PERMISSIONS: tuple[Permission, ...] = (
    "console:access",
    "dashboard:read",
    "users:read",
    "users:write",
    "roles:read",
    "roles:write",
    "settings:read",
    "settings:write",
    "sources:read",
    "sources:write",
    "metadata:read",
    "metadata:write",
    "jobs:run",
    "query:run",
    "catalog:sample",
    "tokens:read",
    "tokens:write",
    "audit:read",
)

PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    "console:access": "Sign in to the Management Console",
    "dashboard:read": "View the console home",
    "users:read": "List and view users",
    "users:write": "Create users and change user status",
    "roles:read": "List roles and the permission catalog",
    "roles:write": "Create, update, and delete roles",
    "settings:read": "View platform system parameters",
    "settings:write": "Change platform system parameters",
    "sources:read": "List and view Sources (non-secret fields)",
    "sources:write": "Create, update, and hard-delete (disabled only) Sources; set secrets; run reachability tests",
    "metadata:read": "Browse catalog objects, semantics, and joins",
    "metadata:write": "Write semantics and join edges",
    "jobs:run": "Enqueue and manage Jobs (structure and later kinds)",
    "query:run": "Run controlled read-only SQL against a Source endpoint",
    "catalog:sample": "Run Catalog Sample (structured live peek) on a Catalog Object",
    "tokens:read": "List own User PAT metadata",
    "tokens:write": "Create, deactivate, restore, and soft-delete (deactivated only) own User PATs",
    "audit:read": "Read management audit events",
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
