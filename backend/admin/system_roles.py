"""System Role ensure for Foundation Upgrade (not Site Bootstrap)."""

from __future__ import annotations

from backend.repositories.role_store import RoleRecord, RoleStore, get_role_store


def ensure_system_role(roles: RoleStore | None = None) -> RoleRecord:
    """Ensure the locked System Role `super_admin` matches the Permission catalog.

    Idempotent. Safe to re-run. Does not touch `operator` or custom roles.
    """
    store = roles or get_role_store()
    return store.ensure_super_admin()
