"""Helpers to build API user payloads from store records."""

from __future__ import annotations

from backend.admin.deps import resolve_user_permissions
from backend.admin.role_store import RoleRecord, RoleStore
from backend.admin.user_store import UserRecord
from backend.admin.schemas.auth import CurrentUser
from backend.admin.schemas.user import UserSummary


def role_fields(role: RoleRecord | None) -> tuple[str | None, str | None, str | None]:
    if role is None:
        return None, None, None
    return role.id, role.key, role.name


def build_current_user(user: UserRecord, roles: RoleStore) -> CurrentUser:
    role = roles.get_by_id(user.role_id) if user.role_id else None
    role_id, role_key, role_name = role_fields(role)
    return CurrentUser(
        id=user.id,
        account=user.account,
        display_name=user.display_name,
        email=user.email,
        locale=user.locale,
        role_id=role_id,
        role_key=role_key,
        role_name=role_name,
        permissions=resolve_user_permissions(user, roles),
        identity_source=user.identity_source,
    )


def build_user_summary(user: UserRecord, roles: RoleStore) -> UserSummary:
    role = roles.get_by_id(user.role_id) if user.role_id else None
    role_id, role_key, role_name = role_fields(role)
    return UserSummary(
        id=user.id,
        account=user.account,
        display_name=user.display_name,
        email=user.email,
        locale=user.locale,
        role_id=role_id,
        role_key=role_key,
        role_name=role_name,
        status=user.status,
        identity_source=user.identity_source,
        last_login_at=user.last_login_at,
    )
