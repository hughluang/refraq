"""Single User lifecycle seam for disable, enable, and instant session/OAuth revocation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.admin.errors import (
    UserLastLocalSuperAdmin,
    UserNotFound,
    UserSelfDisableForbidden,
    UserSystemImmutable,
)
from backend.admin.federation.binding_store import BindingStore
from backend.admin.oauth.runtime_store import OAuthRuntimeStore
from backend.admin.role_store import RoleStore
from backend.admin.roles import is_last_local_active_super_admin
from backend.admin.session_store import SessionStore
from backend.admin.user_store import UserRecord, UserStore
from backend.core.time import utc_now


def disable_user(
    *,
    user_id: str,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
    bindings: BindingStore | None = None,
    caller_user_id: str | None = None,
    actor_token_id: str | None = None,
    mark_scim_deprovisioned: bool = False,
    audit_detail: dict[str, Any] | None = None,
    enforce_last_super_admin: bool = True,
) -> UserRecord:
    """Disable a User, stamp optional SCIM deprovision barrier, and purge active sessions/OAuth tokens."""
    if caller_user_id is not None and user_id == caller_user_id:
        raise UserSelfDisableForbidden()

    record = users.get_by_id(user_id)
    if record is None:
        raise UserNotFound()
    if record.identity_source == "system":
        raise UserSystemImmutable()
    if enforce_last_super_admin and is_last_local_active_super_admin(record, users, roles):
        raise UserLastLocalSuperAdmin()

    updated = users.update_status(user_id, "disabled")
    if updated is None:
        raise UserNotFound()

    if mark_scim_deprovisioned:
        if bindings is None:
            raise ValueError("bindings is required when mark_scim_deprovisioned=True")
        binding = bindings.get_for_user(user_id)
        if binding is not None and binding.scim_deprovisioned_at is None:
            bindings.save(replace(binding, scim_deprovisioned_at=utc_now()))

    sessions.delete_by_user_id(user_id)
    oauth_runtime.revoke_for_user(user_id)

    persist_audit_event(
        actor_user_id=caller_user_id,
        actor_token_id=actor_token_id,
        resource_type="user",
        resource_id=user_id,
        action="disable",
        result="success",
        detail=audit_detail or {},
    )
    return updated


def enable_user(
    *,
    user_id: str,
    users: UserStore,
    bindings: BindingStore | None = None,
    caller_user_id: str | None = None,
    actor_token_id: str | None = None,
    clear_scim_deprovisioned: bool = False,
    audit_detail: dict[str, Any] | None = None,
) -> UserRecord:
    """Re-enable a User and optionally clear the SCIM soft-deprovision barrier."""
    record = users.get_by_id(user_id)
    if record is None:
        raise UserNotFound()
    if record.identity_source == "system":
        raise UserSystemImmutable()

    updated = users.update_status(user_id, "active")
    if updated is None:
        raise UserNotFound()

    if clear_scim_deprovisioned:
        if bindings is None:
            raise ValueError("bindings is required when clear_scim_deprovisioned=True")
        binding = bindings.get_for_user(user_id)
        if binding is not None and binding.scim_deprovisioned_at is not None:
            bindings.save(replace(binding, scim_deprovisioned_at=None))

    if audit_detail is not None or caller_user_id is not None:
        persist_audit_event(
            actor_user_id=caller_user_id,
            actor_token_id=actor_token_id,
            resource_type="user",
            resource_id=user_id,
            action="enable",
            result="success",
            detail=audit_detail or {},
        )
    return updated
