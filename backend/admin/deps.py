"""FastAPI dependencies for auth-aware request handling."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal, TypedDict

from fastapi import Cookie, Depends, Header, Request

from backend.admin.errors import AuthForbidden, AuthPatInvalid, AuthUnauthenticated
from backend.admin.permissions import Permission, permissions_include
from backend.core.config import Settings, get_settings
from backend.repositories.role_store import RoleStore, get_role_store
from backend.repositories.session_store import SessionStore, get_session_store
from backend.repositories.token_store import (
    TokenStore,
    get_token_store,
    hash_token,
)
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


def _user_from_session(
    *,
    request: Request,
    refraq_sid: str | None,
    sessions: SessionStore,
    users: UserStore,
) -> UserRecord | None:
    if not refraq_sid:
        return None
    user_id = sessions.get(refraq_sid)
    if user_id is None:
        return None
    record = users.get_by_id(user_id)
    if record is None or record.status != "active":
        return None
    request.state.session_id = refraq_sid
    request.state.actor_token_id = None
    request.state.current_user = record
    return record


def _user_from_bearer(
    *,
    request: Request,
    authorization: str | None,
    tokens: TokenStore,
    users: UserStore,
) -> UserRecord:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthUnauthenticated()
    secret = authorization[7:].strip()
    if not secret:
        raise AuthPatInvalid()
    record = tokens.get_by_hash(hash_token(secret))
    now = datetime.utcnow()
    if (
        record is None
        or record.revoked_at is not None
        or record.deleted_at is not None
        or record.expires_at <= now
    ):
        raise AuthPatInvalid()
    user = users.get_by_id(record.user_id)
    if user is None or user.status != "active":
        raise AuthPatInvalid()
    tokens.touch_last_used(record.id, now)
    request.state.session_id = None
    request.state.actor_token_id = record.id
    request.state.current_user = user
    return user


def get_current_user(
    request: Request,
    refraq_sid: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    authorization: str | None = Header(default=None),
    sessions: SessionStore = Depends(get_session_store),
    users: UserStore = Depends(get_user_store),
    tokens: TokenStore = Depends(get_token_store),
) -> UserRecord:
    """Resolve User from Session cookie (preferred) or User PAT Bearer."""
    session_user = _user_from_session(
        request=request,
        refraq_sid=refraq_sid,
        sessions=sessions,
        users=users,
    )
    if session_user is not None:
        return session_user
    if authorization:
        return _user_from_bearer(
            request=request,
            authorization=authorization,
            tokens=tokens,
            users=users,
        )
    raise AuthUnauthenticated()


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


def get_actor_token_id(request: Request) -> str | None:
    return getattr(request.state, "actor_token_id", None)


def resolve_pat_bearer(secret: str) -> tuple[UserRecord, str]:
    """Resolve an active User and PAT id from a raw PAT secret (MCP / non-HTTP)."""
    tokens = get_token_store()
    users = get_user_store()
    record = tokens.get_by_hash(hash_token(secret))
    now = datetime.utcnow()
    if (
        record is None
        or record.revoked_at is not None
        or record.deleted_at is not None
        or record.expires_at <= now
    ):
        raise AuthPatInvalid()
    user = users.get_by_id(record.user_id)
    if user is None or user.status != "active":
        raise AuthPatInvalid()
    tokens.touch_last_used(record.id, now)
    return user, record.id

