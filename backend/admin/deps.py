"""FastAPI dependencies for auth-aware request handling."""

from __future__ import annotations

from typing import Callable, Literal, TypedDict

from fastapi import Cookie, Depends, Request

from backend.admin.errors import AuthForbidden, AuthUnauthenticated
from backend.admin.permissions import Permission, permissions_include
from backend.admin.session_store import SessionStore, get_session_store
from backend.config import Settings, get_settings
from backend.repositories.role_store import RoleStore, get_role_store
from backend.repositories.user_store import UserRecord, UserStore, get_user_store

SESSION_COOKIE_NAME = "refraq_sid"


class SessionCookieAttrs(TypedDict):
    path: str
    httponly: bool
    samesite: Literal["lax"]
    secure: bool


def session_cookie_attrs(settings: Settings) -> SessionCookieAttrs:
    """Shared cookie attributes for set_cookie and delete_cookie."""
    return {
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": settings.refraq_env != "dev",
    }


def resolve_user_permissions(
    user: UserRecord, roles: RoleStore
) -> list[str]:
    if not user.role_id:
        return []
    role = roles.get_by_id(user.role_id)
    if role is None:
        return []
    return list(role.permissions)


def get_current_user(
    request: Request,
    refraq_sid: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sessions: SessionStore = Depends(get_session_store),
    users: UserStore = Depends(get_user_store),
) -> UserRecord:
    user_id = sessions.get(refraq_sid or "")
    if user_id is None:
        raise AuthUnauthenticated()
    record = users.get_by_id(user_id)
    if record is None:
        raise AuthUnauthenticated()
    if record.status != "active":
        raise AuthUnauthenticated()
    request.state.session_id = refraq_sid
    request.state.current_user = record
    return record


def require_permission(permission: Permission) -> Callable[[UserRecord], UserRecord]:
    def _checker(
        user: UserRecord = Depends(get_current_user),
        roles: RoleStore = Depends(get_role_store),
    ) -> UserRecord:
        perms = resolve_user_permissions(user, roles)
        if not permissions_include(perms, permission):
            raise AuthForbidden()
        return user

    return _checker
