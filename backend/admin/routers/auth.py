"""Auth router implementing docs/api-contracts-auth.md."""

from __future__ import annotations

from backend.core.time import utc_now
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Response

from backend.admin.deps import (
    SESSION_COOKIE_NAME,
    get_current_user,
    resolve_user_permissions,
    session_cookie_attrs,
)
from backend.admin.errors import (
    AuthAccountDisabled,
    AuthConsoleAccessRequired,
    AuthInvalidCredentials,
)
from backend.admin.security import verify_password
from backend.admin.settings_override import get_effective_admin_session_ttl_hours
from backend.admin.user_payload import build_current_user
from backend.core.config import Settings, get_settings
from backend.admin.role_store import RoleStore, get_role_store
from backend.admin.session_store import SessionStore, get_session_store
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.admin.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    record = users.get_by_account(payload.account)
    if record is None or not verify_password(payload.password, record.password_hash):
        raise AuthInvalidCredentials()
    if record.status != "active":
        raise AuthAccountDisabled()

    permissions = resolve_user_permissions(record, roles)
    if "console:access" not in permissions:
        raise AuthConsoleAccessRequired()

    ttl_seconds = get_effective_admin_session_ttl_hours(settings) * 3600
    session_id = sessions.create(record.id, ttl_seconds)
    cookie_attrs = session_cookie_attrs(settings)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=ttl_seconds,
        **cookie_attrs,
    )

    users.update_last_login(record.id, utc_now())
    return LoginResponse(user=build_current_user(record, roles))


@router.get("/me", response_model=LoginResponse)
def me(
    user: UserRecord = Depends(get_current_user),
    roles: RoleStore = Depends(get_role_store),
) -> LoginResponse:
    return LoginResponse(user=build_current_user(user, roles))


@router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    refraq_sid: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sessions: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    if refraq_sid:
        sessions.delete(refraq_sid)
    response.delete_cookie(SESSION_COOKIE_NAME, **session_cookie_attrs(settings))
    return LogoutResponse(success=True)
